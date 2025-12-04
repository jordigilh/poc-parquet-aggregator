"""Storage aggregator for OCP storage usage data."""

import gc
import uuid as uuid_lib
from typing import Dict

import numpy as np
import pandas as pd

from .utils import get_logger


class StorageAggregator:
    """
    Aggregate OCP storage usage data to daily summary.

    Implements Trino SQL logic for storage aggregation:
    - Joins storage data with pod data to get node/resource_id
    - Groups by PVC (not pod)
    - Converts byte-seconds to gigabyte-months
    - Applies label precedence (Pod > Namespace > Node)
    - Outputs rows with data_source='Storage'
    """

    def __init__(self, config: Dict, logger=None):
        """Initialize storage aggregator.

        Args:
            config: Configuration dictionary
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or get_logger("aggregator_storage")

        # Performance settings
        self.use_arrow_compute = config.get("performance", {}).get("use_arrow_compute", False)

        self.logger.info("Initialized StorageAggregator")

    def _merge_volume_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Merge persistentvolume_labels and persistentvolumeclaim_labels into volume_labels.

        Nise generates two separate label columns:
        - persistentvolume_labels: Labels from the PV
        - persistentvolumeclaim_labels: Labels from the PVC

        Trino/koku expects a single 'volume_labels' column. We prioritize PVC labels over PV labels.

        Args:
            df: Storage usage DataFrame

        Returns:
            DataFrame with volume_labels column
        """
        import json

        def parse_labels(label_str):
            """Parse label string (JSON or empty) into dict."""
            if pd.isna(label_str) or label_str == "" or label_str is None:
                return {}
            if isinstance(label_str, dict):
                return label_str
            try:
                # Handle numeric values (nise sometimes stores NaN as float)
                if isinstance(label_str, float):
                    return {}
                return json.loads(label_str)
            except (json.JSONDecodeError, TypeError):
                return {}

        if "volume_labels" not in df.columns:
            # Merge PV and PVC labels (PVC labels take precedence)
            if "persistentvolume_labels" in df.columns and "persistentvolumeclaim_labels" in df.columns:

                def merge_labels(row):
                    pv_labels = parse_labels(row.get("persistentvolume_labels"))
                    pvc_labels = parse_labels(row.get("persistentvolumeclaim_labels"))
                    merged = {**pv_labels, **pvc_labels}  # PVC overrides PV
                    return json.dumps(merged) if merged else "{}"

                df["volume_labels"] = df.apply(merge_labels, axis=1)
                self.logger.info("✓ Merged persistentvolume_labels + persistentvolumeclaim_labels into volume_labels")
            elif "persistentvolume_labels" in df.columns:
                df["volume_labels"] = df["persistentvolume_labels"]
                self.logger.info("✓ Using persistentvolume_labels as volume_labels")
            elif "persistentvolumeclaim_labels" in df.columns:
                df["volume_labels"] = df["persistentvolumeclaim_labels"]
                self.logger.info("✓ Using persistentvolumeclaim_labels as volume_labels")
            else:
                df["volume_labels"] = "{}"
                self.logger.warning("No label columns found, using empty volume_labels")
        else:
            self.logger.debug("volume_labels column already exists")

        return df

    def aggregate(
        self,
        storage_df: pd.DataFrame,
        pod_df: pd.DataFrame,
        node_labels_df: pd.DataFrame,
        namespace_labels_df: pd.DataFrame,
        cost_category_df: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """
        Aggregate storage usage to daily summary.

        Args:
            storage_df: Storage usage line items
            pod_df: Pod usage line items (for node/resource_id join)
            node_labels_df: Node labels
            namespace_labels_df: Namespace labels
            cost_category_df: Cost category namespace patterns (optional)

        Returns:
            Aggregated storage summary DataFrame with data_source='Storage'
        """
        self.logger.info(f"Starting storage aggregation (input_rows={len(storage_df)})")

        if storage_df.empty:
            self.logger.warning("No storage data to aggregate")
            return self._create_empty_result()

        # Merge persistentvolume_labels and persistentvolumeclaim_labels into volume_labels
        # Nise generates two separate label columns, but Trino/koku expects a single volume_labels column
        storage_df = self._merge_volume_labels(storage_df)

        # Step 1: Join with pod data to get node/resource_id
        # (Storage data doesn't have node info, need to get from pods)
        storage_with_nodes = self._join_with_pods(storage_df, pod_df)

        if storage_with_nodes.empty:
            self.logger.warning("No storage data after joining with pods")
            return self._create_empty_result()

        # Step 2: Group and aggregate by day + PVC
        aggregated = self._group_and_aggregate(storage_with_nodes)

        self.logger.info(f"Grouped storage data (output_rows={len(aggregated)})")

        # Step 3: Join with node labels
        aggregated = self._join_node_labels(aggregated, node_labels_df)

        # Step 4: Join with namespace labels
        aggregated = self._join_namespace_labels(aggregated, namespace_labels_df)

        # Step 5: Process volume labels (with precedence: Volume > Namespace > Node)
        aggregated = self._process_labels(aggregated)

        # Step 6: Join with cost category (Trino SQL lines 406, 428-429)
        if cost_category_df is not None and not cost_category_df.empty:
            aggregated = self._join_cost_category(aggregated, cost_category_df)
        else:
            aggregated["cost_category_id"] = None

        # Step 7: Format output
        result = self._format_output(aggregated)

        self.logger.info(f"Storage aggregation complete (output_rows={len(result)})")

        # Cleanup
        if self.config.get("performance", {}).get("delete_intermediate_dfs", True):
            del storage_with_nodes, aggregated
            if self.config.get("performance", {}).get("gc_after_aggregation", True):
                gc.collect()

        return result

    def _join_with_pods(self, storage_df: pd.DataFrame, pod_df: pd.DataFrame) -> pd.DataFrame:
        """
        Join storage data with pod data to get node/resource_id.

        From Trino SQL (reporting_ocpusagelineitem_daily_summary.sql, lines 183-188):
        JOIN openshift_pod_usage_line_items_daily as uli
            ON uli.source = sli.source
            AND uli.namespace = sli.namespace
            AND uli.pod = sli.pod
            AND date(uli.interval_start) = date(sli.interval_start)

        Args:
            storage_df: Storage usage data
            pod_df: Pod usage data

        Returns:
            Storage data with node/resource_id added
        """
        self.logger.info("Joining storage with pod data to get node/resource_id")

        # Create date columns for joining
        storage_df = storage_df.copy()
        if pd.api.types.is_string_dtype(storage_df["interval_start"]):
            # Handle nise string format: "2025-11-01 00:00:00 +0000 UTC"
            storage_df["interval_start_clean"] = storage_df["interval_start"].str.replace(
                r" \+\d{4} UTC$", "", regex=True
            )
            storage_df["usage_date"] = pd.to_datetime(storage_df["interval_start_clean"]).dt.date
            storage_df.drop("interval_start_clean", axis=1, inplace=True)
        else:
            storage_df["usage_date"] = pd.to_datetime(storage_df["interval_start"]).dt.date

        pod_subset = pod_df.copy()
        if pd.api.types.is_string_dtype(pod_subset["interval_start"]):
            # Handle nise string format
            pod_subset["interval_start_clean"] = pod_subset["interval_start"].str.replace(
                r" \+\d{4} UTC$", "", regex=True
            )
            pod_subset["usage_date"] = pd.to_datetime(pod_subset["interval_start_clean"]).dt.date
            pod_subset.drop("interval_start_clean", axis=1, inplace=True)
        else:
            pod_subset["usage_date"] = pd.to_datetime(pod_subset["interval_start"]).dt.date

        # Select only needed columns from pod_df to reduce memory
        pod_subset = pod_subset[["usage_date", "namespace", "pod", "node", "resource_id"]].drop_duplicates()

        self.logger.debug(
            "Pod subset for join",
            rows=len(pod_subset),
            unique_dates=pod_subset["usage_date"].nunique(),
        )

        # Join
        result = pd.merge(
            storage_df,
            pod_subset,
            on=["usage_date", "namespace", "pod"],
            how="left",  # Keep storage rows even if no pod match
        )

        # Log matching stats
        matched = result["node"].notna().sum()
        total = len(result)
        match_pct = (matched / total * 100) if total > 0 else 0

        self.logger.info(
            "Storage-Pod join complete",
            matched=matched,
            total=total,
            match_pct=f"{match_pct:.1f}%",
        )

        if matched < total:
            self.logger.warning(f"{total - matched} storage rows have no matching pod data (node will be NULL)")

        # Ensure node and resource_id are string type (not float) even if NaN
        # Convert to object type first if categorical to avoid fillna issues
        if hasattr(result["node"].dtype, "categories"):
            result["node"] = result["node"].astype(object)
        result["node"] = result["node"].fillna("").astype(str)
        if hasattr(result["resource_id"].dtype, "categories"):
            result["resource_id"] = result["resource_id"].astype(object)
        result["resource_id"] = result["resource_id"].fillna("").astype(str)

        return result

    def _group_and_aggregate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Group by day + PVC and aggregate storage metrics.

        From Trino SQL (lines 392-449):
        GROUP BY date(interval_start), namespace, persistentvolumeclaim,
                 persistentvolume, storageclass, node, resource_id, volume_labels

        Aggregations:
        - SUM byte-seconds metrics / node_count (Trino lines 410-411)
        - MAX csi_volume_handle
        - FIRST volume_labels (will merge with precedence later)

        Args:
            df: Storage data with node/resource_id

        Returns:
            Aggregated DataFrame
        """
        self.logger.info("Grouping and aggregating storage data")

        # Handle both string and datetime formats for interval_start
        if pd.api.types.is_string_dtype(df["interval_start"]):
            df["interval_start_clean"] = df["interval_start"].str.replace(r" \+\d{4} UTC$", "", regex=True)
            df["usage_start"] = pd.to_datetime(df["interval_start_clean"]).dt.date
            df.drop("interval_start_clean", axis=1, inplace=True)
        else:
            df["usage_start"] = pd.to_datetime(df["interval_start"]).dt.date

        # ====================================================================
        # Step 1: Calculate shared volume node count (Trino lines 205-212)
        # ====================================================================
        # Count distinct nodes per PV per day
        node_counts = df.groupby(["usage_start", "persistentvolume"])["node"].nunique().reset_index()
        node_counts.columns = ["usage_start", "persistentvolume", "node_count"]

        # Join node count back to data
        df = pd.merge(df, node_counts, on=["usage_start", "persistentvolume"], how="left")
        df["node_count"] = df["node_count"].fillna(1)  # Default to 1 if no match

        self.logger.debug(
            "Calculated shared volume node counts",
            unique_pvs=len(node_counts),
            max_nodes_shared=int(node_counts["node_count"].max()) if not node_counts.empty else 0,
        )

        # ====================================================================
        # Step 2: Divide usage metrics by node count (Trino lines 410-411)
        # ====================================================================
        # sum(sli.volume_request_storage_byte_seconds) / max(nc.node_count)
        # sum(sli.persistentvolumeclaim_usage_byte_seconds) / max(nc.node_count)
        df["volume_request_storage_byte_seconds"] = df["volume_request_storage_byte_seconds"] / df["node_count"]
        df["persistentvolumeclaim_usage_byte_seconds"] = (
            df["persistentvolumeclaim_usage_byte_seconds"] / df["node_count"]
        )
        # Note: capacity is NOT divided (Trino line 408 uses sum without division)

        # Group keys
        group_keys = [
            "usage_start",
            "namespace",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "node",
            "resource_id",
        ]

        # Aggregations
        agg_dict = {
            # Storage metrics (byte-seconds) - already divided by node_count
            "persistentvolumeclaim_capacity_byte_seconds": "sum",
            "volume_request_storage_byte_seconds": "sum",
            "persistentvolumeclaim_usage_byte_seconds": "sum",
            # Labels (will process with precedence later)
            "volume_labels": "first",
            # CSI handle (for AWS matching)
            "csi_volume_handle": "max",
        }

        # Add capacity_bytes if present (Trino line 357: max(capacity_bytes) * 2^-30)
        if "persistentvolumeclaim_capacity_bytes" in df.columns:
            agg_dict["persistentvolumeclaim_capacity_bytes"] = "max"

        aggregated = df.groupby(group_keys, dropna=False).agg(agg_dict).reset_index()

        self.logger.info(f"Grouped storage data (input_rows={len(df)}, output_rows={len(aggregated)})")

        # Convert byte-seconds to gigabyte-months
        aggregated = self._convert_metrics_to_gigabyte_months(aggregated)

        return aggregated

    def _convert_metrics_to_gigabyte_months(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert byte-seconds to gigabyte-months.

        Trino SQL formula (lines 358-363):
            capacity_byte_seconds / (86400 * days_in_month) * power(2, -30)

        Where days_in_month = extract(day from last_day_of_month(usage_start))

        This uses actual days in month (28, 29, 30, or 31) for accurate billing.

        Args:
            df: DataFrame with byte-seconds metrics and usage_start

        Returns:
            DataFrame with gigabyte-months metrics
        """
        import calendar

        bytes_to_gb = 1024**3  # power(2, -30) in Trino = 1/2^30 = 1/1024^3
        seconds_per_day = 86400

        # Calculate days in month for each row based on usage_start
        # Trino: extract(day from last_day_of_month(date(usage_start)))
        def get_days_in_month(usage_start):
            """Get number of days in the month of usage_start."""
            if pd.isna(usage_start):
                return 30  # Default fallback
            # Convert to datetime if needed
            if hasattr(usage_start, "year"):
                year = usage_start.year
                month = usage_start.month
            else:
                dt = pd.to_datetime(usage_start)
                year = dt.year
                month = dt.month
            return calendar.monthrange(year, month)[1]

        df["_days_in_month"] = df["usage_start"].apply(get_days_in_month)

        self.logger.debug(
            "Calculated days in month",
            unique_values=df["_days_in_month"].unique().tolist(),
        )

        # Trino formula: byte_seconds / (86400 * days_in_month) * power(2, -30)
        # = byte_seconds / (seconds_per_day * days_in_month * bytes_to_gb)

        # Capacity
        df["persistentvolumeclaim_capacity_gigabyte_months"] = df["persistentvolumeclaim_capacity_byte_seconds"] / (
            seconds_per_day * df["_days_in_month"] * bytes_to_gb
        )

        # Request
        df["volume_request_storage_gigabyte_months"] = df["volume_request_storage_byte_seconds"] / (
            seconds_per_day * df["_days_in_month"] * bytes_to_gb
        )

        # Usage
        df["persistentvolumeclaim_usage_gigabyte_months"] = df["persistentvolumeclaim_usage_byte_seconds"] / (
            seconds_per_day * df["_days_in_month"] * bytes_to_gb
        )

        # Drop intermediate columns
        df = df.drop(
            columns=[
                "persistentvolumeclaim_capacity_byte_seconds",
                "volume_request_storage_byte_seconds",
                "persistentvolumeclaim_usage_byte_seconds",
                "_days_in_month",
            ]
        )

        self.logger.debug("Converted storage metrics to gigabyte-months (using actual days in month)")

        return df

    def _join_node_labels(self, df: pd.DataFrame, node_labels_df: pd.DataFrame) -> pd.DataFrame:
        """
        Join with node labels.

        Args:
            df: Aggregated storage data
            node_labels_df: Node labels

        Returns:
            DataFrame with node labels added
        """
        if node_labels_df.empty:
            self.logger.warning("No node labels available")
            df["node_labels"] = "{}"
            return df

        # Deduplicate node labels to avoid Cartesian product
        node_labels_df = node_labels_df.drop_duplicates(subset=["usage_start", "node"])

        self.logger.debug(f"Joining with node labels (node_label_rows={len(node_labels_df)})")

        before_count = len(df)

        df = pd.merge(
            df,
            node_labels_df[["usage_start", "node", "node_labels"]],
            on=["usage_start", "node"],
            how="left",
        )

        after_count = len(df)

        if after_count != before_count:
            self.logger.error(f"Row count changed after node labels join! Before: {before_count}, After: {after_count}")

        # Fill missing labels
        df["node_labels"] = df["node_labels"].fillna("{}")

        return df

    def _join_namespace_labels(self, df: pd.DataFrame, namespace_labels_df: pd.DataFrame) -> pd.DataFrame:
        """
        Join with namespace labels.

        Args:
            df: Aggregated storage data with node labels
            namespace_labels_df: Namespace labels

        Returns:
            DataFrame with namespace labels added
        """
        if namespace_labels_df.empty:
            self.logger.warning("No namespace labels available")
            df["namespace_labels"] = "{}"
            return df

        # Deduplicate namespace labels to avoid Cartesian product
        namespace_labels_df = namespace_labels_df.drop_duplicates(subset=["usage_start", "namespace"])

        self.logger.debug(
            "Joining with namespace labels",
            namespace_label_rows=len(namespace_labels_df),
        )

        before_count = len(df)

        df = pd.merge(
            df,
            namespace_labels_df[["usage_start", "namespace", "namespace_labels"]],
            on=["usage_start", "namespace"],
            how="left",
        )

        after_count = len(df)

        if after_count != before_count:
            self.logger.error(
                f"Row count changed after namespace labels join! Before: {before_count}, After: {after_count}"
            )

        # Fill missing labels
        df["namespace_labels"] = df["namespace_labels"].fillna("{}")

        return df

    def _process_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Process and merge labels with precedence: Volume > Namespace > Node.

        Similar to Pod > Namespace > Node precedence for pod aggregation.

        Args:
            df: DataFrame with volume_labels, namespace_labels, node_labels

        Returns:
            DataFrame with merged_labels column
        """
        self.logger.info("Processing volume labels with precedence")

        import json

        def parse_labels(labels_str):
            """Parse JSON label string to dict."""
            if pd.isna(labels_str) or labels_str == "" or labels_str is None:
                return {}
            try:
                if isinstance(labels_str, dict):
                    return labels_str
                return json.loads(labels_str)
            except:
                return {}

        def merge_labels_with_precedence(row):
            """Merge labels with precedence: Volume > Namespace > Node."""
            node_labels = parse_labels(row.get("node_labels", "{}"))
            namespace_labels = parse_labels(row.get("namespace_labels", "{}"))
            volume_labels = parse_labels(row.get("volume_labels", "{}"))

            # Apply precedence: start with node, override with namespace, override with volume
            merged = {}
            merged.update(node_labels)
            merged.update(namespace_labels)
            merged.update(volume_labels)

            return json.dumps(merged) if merged else "{}"

        # Apply label merging
        df["merged_labels"] = df.apply(merge_labels_with_precedence, axis=1)

        self.logger.debug("Label precedence applied (Volume > Namespace > Node)")

        return df

    def _join_cost_category(self, aggregated_df: pd.DataFrame, cost_category_df: pd.DataFrame) -> pd.DataFrame:
        """Join with cost category namespace (LIKE matching).

        Trino SQL lines 428-429:
            LEFT JOIN postgres.{{schema}}.reporting_ocp_cost_category_namespace AS cat_ns
                ON sli.namespace LIKE cat_ns.namespace

        Trino SQL line 406:
            max(cat_ns.cost_category_id) as cost_category_id

        Args:
            aggregated_df: Aggregated DataFrame
            cost_category_df: Cost category DataFrame with namespace patterns

        Returns:
            Joined DataFrame with cost_category_id column
        """

        def match_cost_category(namespace):
            matching_ids = []
            for _, row in cost_category_df.iterrows():
                pattern = row["namespace"]
                # Simple pattern match (% wildcard - SQL LIKE)
                if pattern.endswith("%"):
                    if namespace.startswith(pattern[:-1]):
                        matching_ids.append(row["cost_category_id"])
                elif namespace == pattern:
                    matching_ids.append(row["cost_category_id"])

            # Return MAX of matching IDs (Trino SQL line 406)
            return max(matching_ids) if matching_ids else None

        aggregated_df["cost_category_id"] = aggregated_df["namespace"].apply(match_cost_category)

        self.logger.debug(
            "Cost category joined for storage",
            matched=aggregated_df["cost_category_id"].notna().sum(),
            total=len(aggregated_df),
        )

        return aggregated_df

    def _format_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Format storage aggregation output with proper schema.

        Key points:
        - data_source='Storage'
        - CPU/memory columns are NULL
        - Storage columns are populated
        - Same table structure as pod aggregation

        Args:
            df: Aggregated storage data with merged labels

        Returns:
            Formatted DataFrame matching reporting_ocpusagelineitem_daily_summary schema
        """
        self.logger.info("Formatting storage aggregation output")

        result = pd.DataFrame()

        # Standard columns
        result["usage_start"] = pd.to_datetime(df["usage_start"])
        result["usage_end"] = pd.to_datetime(df["usage_start"])  # Same as start for daily
        result["data_source"] = "Storage"  # CRITICAL!

        # Dimensions
        result["namespace"] = df["namespace"]
        # Convert to object type first if categorical to avoid fillna issues
        node_col = df["node"].astype(object) if hasattr(df["node"].dtype, "categories") else df["node"]
        result["node"] = node_col.fillna("")  # Replace NaN with empty string
        result["pod"] = None  # NULL for storage rows
        resource_id_col = (
            df["resource_id"].astype(object) if hasattr(df["resource_id"].dtype, "categories") else df["resource_id"]
        )
        result["resource_id"] = resource_id_col.fillna("")  # Replace NaN with empty string

        # Storage columns (populated)
        result["persistentvolumeclaim"] = df["persistentvolumeclaim"].fillna("")
        result["persistentvolume"] = df["persistentvolume"].fillna("")
        result["storageclass"] = df["storageclass"].fillna("")
        result["volume_labels"] = df["merged_labels"]

        # persistentvolumeclaim_capacity_gigabyte: max(capacity_bytes) * 2^-30
        # Trino SQL line 357: (sua.persistentvolumeclaim_capacity_bytes * power(2, -30))
        if "persistentvolumeclaim_capacity_bytes" in df.columns:
            bytes_to_gb = 1024**3  # 2^30
            result["persistentvolumeclaim_capacity_gigabyte"] = df["persistentvolumeclaim_capacity_bytes"] / bytes_to_gb
        else:
            result["persistentvolumeclaim_capacity_gigabyte"] = None

        result["persistentvolumeclaim_capacity_gigabyte_months"] = df["persistentvolumeclaim_capacity_gigabyte_months"]
        result["volume_request_storage_gigabyte_months"] = df["volume_request_storage_gigabyte_months"]
        result["persistentvolumeclaim_usage_gigabyte_months"] = df["persistentvolumeclaim_usage_gigabyte_months"]
        # NOTE: csi_volume_handle does NOT exist in Koku database - REMOVED (Bug #8)

        # CPU/Memory columns (NULL for storage)
        result["pod_usage_cpu_core_hours"] = None
        result["pod_request_cpu_core_hours"] = None
        result["pod_effective_usage_cpu_core_hours"] = None
        result["pod_limit_cpu_core_hours"] = None
        result["pod_usage_memory_gigabyte_hours"] = None
        result["pod_request_memory_gigabyte_hours"] = None
        result["pod_effective_usage_memory_gigabyte_hours"] = None
        result["pod_limit_memory_gigabyte_hours"] = None
        result["node_capacity_cpu_cores"] = None
        result["node_capacity_cpu_core_hours"] = None
        result["node_capacity_memory_gigabytes"] = None
        result["node_capacity_memory_gigabyte_hours"] = None
        result["cluster_capacity_cpu_core_hours"] = None
        result["cluster_capacity_memory_gigabyte_hours"] = None

        # Labels (use merged labels with precedence)
        result["pod_labels"] = df["merged_labels"]  # Volume labels applied with precedence

        # all_labels = merge(pod_labels, volume_labels) - Trino SQL lines 651-654
        # For Storage data, pod_labels is typically empty, so all_labels ≈ volume_labels
        result["all_labels"] = df["merged_labels"]

        # Metadata columns
        result["cluster_id"] = self.config["ocp"]["cluster_id"]
        result["cluster_alias"] = self.config["ocp"].get("cluster_alias", "")
        result["source_uuid"] = self.config["ocp"]["provider_uuid"]
        result["report_period_id"] = self.config["ocp"].get("report_period_id", 1)
        # Bug #9 fix: Generate UUIDs - Koku DB requires uuid (NOT NULL, no default)
        result["uuid"] = [str(uuid_lib.uuid4()) for _ in range(len(result))]
        result["infrastructure_usage_cost"] = None

        # cost_category_id from _join_cost_category (Trino SQL lines 406, 428-429)
        if "cost_category_id" in df.columns:
            result["cost_category_id"] = df["cost_category_id"]
        else:
            result["cost_category_id"] = None

        # Replace any remaining NaN with None for PostgreSQL NULL
        result = result.replace({np.nan: None})

        self.logger.info(f"Storage output formatted (rows={len(result)}, data_source=Storage)")

        return result

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty result DataFrame with proper schema.

        NOTE: Koku database uses "resource_id" NOT "pod" (Bug #7)
        NOTE: Koku database does NOT have "csi_volume_handle" column (Bug #8)
        """
        return pd.DataFrame(
            columns=[
                "usage_start",
                "usage_end",
                "data_source",
                "namespace",
                "node",
                "resource_id",  # Database column (NOT "pod" - Bug #7)
                "persistentvolumeclaim",
                "persistentvolume",
                "storageclass",
                "volume_labels",
                "all_labels",
                "persistentvolumeclaim_capacity_gigabyte",
                "persistentvolumeclaim_capacity_gigabyte_months",
                "volume_request_storage_gigabyte_months",
                "persistentvolumeclaim_usage_gigabyte_months",
                # "csi_volume_handle" - REMOVED: Column does NOT exist in Koku DB (Bug #8)
                "pod_usage_cpu_core_hours",
                "pod_request_cpu_core_hours",
                "pod_effective_usage_cpu_core_hours",
                "pod_limit_cpu_core_hours",
                "pod_usage_memory_gigabyte_hours",
                "pod_request_memory_gigabyte_hours",
                "pod_effective_usage_memory_gigabyte_hours",
                "pod_limit_memory_gigabyte_hours",
                "node_capacity_cpu_cores",
                "node_capacity_cpu_core_hours",
                "node_capacity_memory_gigabytes",
                "node_capacity_memory_gigabyte_hours",
                "cluster_capacity_cpu_core_hours",
                "cluster_capacity_memory_gigabyte_hours",
                "pod_labels",
                "cluster_id",
                "cluster_alias",
                "source_uuid",
                "report_period_id",
                "uuid",
                "infrastructure_usage_cost",
                "cost_category_id",
            ]
        )
