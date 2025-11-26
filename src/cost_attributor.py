"""
Cost Attributor for OCP-on-AWS

Attributes AWS costs to OCP pods/namespaces based on resource usage.

Key Logic:
1. Join matched AWS resources with OCP pod usage
2. Calculate attribution ratio: Pod CPU/Memory usage / Node capacity
3. Attribute AWS costs to pods based on ratio
4. Handle 4 cost types: Unblended, Blended, Savings Plan, Amortized
5. Apply markup to all cost types

Cost Attribution Methods (configurable via cost.distribution.method):
    - 'cpu': CPU-only attribution (Trino-compatible)
        Pod Cost = AWS Cost × (Pod CPU / Node CPU)

    - 'memory': Memory-only attribution
        Pod Cost = AWS Cost × (Pod Memory / Node Memory)

    - 'weighted': Industry-standard weighted attribution (default)
        Pod Cost = AWS Cost × (CPU_ratio × cpu_weight + Memory_ratio × memory_weight)
        Weights derived from cloud provider pricing (e.g., AWS: 73% CPU, 27% Memory)

Per-provider weights configured in config.yaml under cost.distribution.weights.

Complexity: HIGH (6/10)
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .utils import PerformanceTimer, get_logger


class CostAttributor:
    """
    Attribute AWS costs to OCP pods/namespaces.

    This class implements the core cost attribution logic that distributes
    AWS infrastructure costs (EC2, EBS, RDS, etc.) to OpenShift workloads
    based on their resource usage.
    """

    # Default markup percentage
    DEFAULT_MARKUP = 0.10  # 10%

    # Default distribution weights (AWS M5 family)
    DEFAULT_CPU_WEIGHT = 0.73
    DEFAULT_MEMORY_WEIGHT = 0.27

    def __init__(self, config: Dict, provider: str = "aws"):
        """
        Initialize cost attributor.

        Args:
            config: Configuration dictionary
            provider: Cloud provider (aws, azure, gcp) for weight selection
        """
        self.config = config
        self.provider = provider
        self.logger = get_logger("cost_attributor")

        # Get markup from config (default 10%)
        cost_config = config.get("cost", {})
        self.markup = cost_config.get("markup", self.DEFAULT_MARKUP)

        # Get distribution configuration
        # Default: cpu (Trino-compatible) - change to 'weighted' after dev team approval
        dist_config = cost_config.get("distribution", {})
        self.distribution_method = dist_config.get("method", "cpu")

        # Get per-provider weights
        weights = dist_config.get("weights", {})
        provider_weights = weights.get(provider, weights.get("default", {}))
        self.cpu_weight = provider_weights.get("cpu_weight", self.DEFAULT_CPU_WEIGHT)
        self.memory_weight = provider_weights.get(
            "memory_weight", self.DEFAULT_MEMORY_WEIGHT
        )

        self.logger.info(
            "Initialized cost attributor",
            markup=f"{self.markup * 100:.1f}%",
            distribution_method=self.distribution_method,
            provider=self.provider,
            cpu_weight=self.cpu_weight,
            memory_weight=self.memory_weight,
        )

    def join_ocp_with_aws(
        self, ocp_pod_usage_df: pd.DataFrame, aws_matched_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Join OCP pod usage with matched AWS resources.

        This creates the foundation for cost attribution by linking:
        - OCP pods → AWS EC2 instances (by resource_id)
        - OCP pods → AWS resources with matching tags

        Join Keys:
        - usage_start (date)
        - resource_id (OCP node → AWS instance)
        OR
        - matched_ocp_cluster/node/namespace (from tag matching)

        Args:
            ocp_pod_usage_df: OCP pod usage DataFrame
            aws_matched_df: AWS resources with matching columns

        Returns:
            Joined DataFrame with OCP usage + AWS costs
        """
        with PerformanceTimer("Join OCP with AWS", self.logger):
            if ocp_pod_usage_df.empty:
                self.logger.warning("OCP pod usage DataFrame is empty")
                return pd.DataFrame()

            if aws_matched_df.empty:
                self.logger.warning("AWS matched DataFrame is empty")
                return pd.DataFrame()

            self.logger.info(
                "Starting OCP + AWS join",
                ocp_rows=len(ocp_pod_usage_df),
                aws_rows=len(aws_matched_df),
            )

            # Join Strategy 1: By resource_id (EC2 instances → OCP nodes)
            merged_by_resource_id = pd.DataFrame()

            if "resource_id_matched" in aws_matched_df.columns:
                aws_resource_id_matched = aws_matched_df[
                    aws_matched_df["resource_id_matched"] == True
                ].copy()

                if not aws_resource_id_matched.empty:
                    self.logger.debug(
                        f"Joining {len(aws_resource_id_matched)} AWS resources matched by resource ID"
                    )

                    # Need to map usage_start (date) to interval_start (datetime)
                    # OCP uses 'interval_start', AWS uses 'lineitem_usagestartdate'

                    # Ensure both have a common date column
                    ocp_with_date = ocp_pod_usage_df.copy()

                    # Handle OCP datetime format: "2025-10-02 00:00:00 +0000 UTC"
                    # Strip timezone suffix before parsing
                    # Use HOURLY timestamps (not daily dates) to match Trino behavior
                    if pd.api.types.is_string_dtype(ocp_with_date["interval_start"]):
                        ocp_with_date["interval_start_clean"] = ocp_with_date[
                            "interval_start"
                        ].str.replace(r" \+\d{4} UTC$", "", regex=True)
                        ocp_with_date["usage_start"] = (
                            pd.to_datetime(ocp_with_date["interval_start_clean"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )  # Remove timezone for merge compatibility
                        ocp_with_date.drop("interval_start_clean", axis=1, inplace=True)
                    else:
                        # Already datetime - floor to hour and remove timezone
                        ocp_with_date["usage_start"] = (
                            pd.to_datetime(ocp_with_date["interval_start"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )

                    aws_with_date = aws_resource_id_matched.copy()
                    if "lineitem_usagestartdate" in aws_with_date.columns:
                        aws_with_date["usage_start"] = (
                            pd.to_datetime(aws_with_date["lineitem_usagestartdate"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )  # Remove timezone for merge compatibility
                    else:
                        self.logger.warning("AWS data missing lineitem_usagestartdate")
                        aws_with_date["usage_start"] = (
                            pd.Timestamp.now().floor("H").tz_localize(None)
                        )

                    # DEBUG: Check merge keys before join
                    ocp_resource_ids = ocp_with_date["resource_id"].unique()
                    aws_resource_ids = aws_with_date["matched_resource_id"].unique()
                    ocp_hours = ocp_with_date["usage_start"].unique()
                    aws_hours = aws_with_date["usage_start"].unique()

                    self.logger.info(
                        "DEBUG: Before merge",
                        ocp_rows=len(ocp_with_date),
                        aws_rows=len(aws_with_date),
                        ocp_unique_resource_ids=len(ocp_resource_ids),
                        aws_unique_resource_ids=len(aws_resource_ids),
                        ocp_sample_resource_id=ocp_resource_ids[0]
                        if len(ocp_resource_ids) > 0
                        else None,
                        aws_sample_resource_id=aws_resource_ids[0]
                        if len(aws_resource_ids) > 0
                        else None,
                        ocp_hours_count=len(ocp_hours),
                        aws_hours_count=len(aws_hours),
                        ocp_sample_hour=str(ocp_hours[0])
                        if len(ocp_hours) > 0
                        else None,
                        aws_sample_hour=str(aws_hours[0])
                        if len(aws_hours) > 0
                        else None,
                    )

                    # Join by resource_id and usage_start (hourly) - Trino parity
                    merged_by_resource_id = ocp_with_date.merge(
                        aws_with_date,
                        left_on=["resource_id", "usage_start"],
                        right_on=["matched_resource_id", "usage_start"],
                        how="inner",
                        suffixes=("_ocp", "_aws"),
                    )

                    self.logger.info(
                        f"✓ Joined by resource ID: {len(merged_by_resource_id)} rows"
                    )

                    # DEBUG: Check for cost columns after merge
                    cost_cols = [
                        c for c in merged_by_resource_id.columns if "cost" in c.lower()
                    ]
                    has_aws_suffix = (
                        "lineitem_unblendedcost_aws" in merged_by_resource_id.columns
                    )
                    cost_sum = 0
                    if has_aws_suffix:
                        cost_sum = merged_by_resource_id[
                            "lineitem_unblendedcost_aws"
                        ].sum()
                    elif "lineitem_unblendedcost" in merged_by_resource_id.columns:
                        cost_sum = merged_by_resource_id["lineitem_unblendedcost"].sum()

                    # DEBUG: Check for capacity/usage columns
                    has_pod_cpu = (
                        "pod_usage_cpu_core_hours" in merged_by_resource_id.columns
                    )
                    has_node_cpu = (
                        "node_capacity_cpu_core_hours" in merged_by_resource_id.columns
                    )
                    usage_cols = [
                        c
                        for c in merged_by_resource_id.columns
                        if "usage" in c.lower() or "capacity" in c.lower()
                    ]

                    self.logger.info(
                        "DEBUG: After merge by resource_id",
                        merged_rows=len(merged_by_resource_id),
                        has_lineitem_unblendedcost_aws=has_aws_suffix,
                        cost_sum=cost_sum,
                        cost_columns_count=len(cost_cols),
                        has_pod_usage_cpu=has_pod_cpu,
                        has_node_capacity_cpu=has_node_cpu,
                        usage_capacity_columns=usage_cols[:10],
                    )

            # Join Strategy 2: By tags (cluster/node/namespace)
            merged_by_tags = pd.DataFrame()

            if "tag_matched" in aws_matched_df.columns:
                aws_tag_matched = aws_matched_df[
                    aws_matched_df["tag_matched"] == True
                ].copy()

                if not aws_tag_matched.empty:
                    self.logger.debug(
                        f"Joining {len(aws_tag_matched)} AWS resources matched by tags"
                    )

                    # Tag matching is more complex - can match at cluster/node/namespace level
                    # For now, we'll implement namespace-level tag matching

                    ocp_with_date = ocp_pod_usage_df.copy()
                    # Handle both datetime objects and string formats
                    # Some data has format: "2025-10-01 00:00:00 +0000 UTC"
                    # Pandas doesn't recognize the " UTC" text suffix (timezone already in "+0000")
                    # Use HOURLY timestamps (not daily dates) to avoid Cartesian products
                    if pd.api.types.is_string_dtype(ocp_with_date["interval_start"]):
                        # String column - strip " UTC" suffix and any timezone offset
                        ocp_with_date["interval_start_clean"] = ocp_with_date[
                            "interval_start"
                        ].str.replace(r" \+\d{4} UTC$", "", regex=True)
                        ocp_with_date["usage_start"] = (
                            pd.to_datetime(ocp_with_date["interval_start_clean"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )  # Remove timezone for merge compatibility
                        ocp_with_date.drop("interval_start_clean", axis=1, inplace=True)
                    else:
                        # Already datetime - floor to hour and remove timezone
                        ocp_with_date["usage_start"] = (
                            pd.to_datetime(ocp_with_date["interval_start"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )

                    aws_with_date = aws_tag_matched.copy()
                    if "lineitem_usagestartdate" in aws_with_date.columns:
                        aws_with_date["usage_start"] = (
                            pd.to_datetime(aws_with_date["lineitem_usagestartdate"])
                            .dt.floor("H")
                            .dt.tz_localize(None)
                        )  # Remove timezone for merge compatibility
                    else:
                        aws_with_date["usage_start"] = (
                            pd.Timestamp.now().floor("H").tz_localize(None)
                        )

                    # Trino-style tag matching: Single join with OR conditions
                    # Matches Trino SQL lines 633-643 in 2_summarize_data_by_cluster.sql
                    #
                    # Exclude synthetic namespaces (Trino parity)
                    EXCLUDED_NAMESPACES = [
                        "Worker unallocated",
                        "Platform unallocated",
                        "Storage unattributed",
                        "Network unattributed",
                    ]
                    ocp_filtered = ocp_with_date[
                        ~ocp_with_date["namespace"].isin(EXCLUDED_NAMESPACES)
                    ].copy()

                    if ocp_filtered.empty:
                        self.logger.warning("No OCP data after namespace filtering")
                        merged_by_tags = pd.DataFrame()
                    else:
                        # Join on usage_start (hourly) to prevent Cartesian products
                        # This matches Trino's: JOIN aws ON aws.usage_start = ocp.usage_start AND (tag conditions)
                        merged = ocp_filtered.merge(
                            aws_with_date,
                            on="usage_start",
                            how="inner",
                            suffixes=("_ocp", "_aws"),
                        )

                        if merged.empty:
                            self.logger.warning(
                                "No date overlap between OCP and AWS data"
                            )
                            merged_by_tags = pd.DataFrame()
                        else:
                            # Trino parity: If tag_matched == True, accept the join
                            # The tag_matcher already validated that tags match via:
                            # - openshift_cluster/node/project tags
                            # - OR generic pod_labels/volume_labels
                            # Trino SQL: WHERE azure.matched_tag != '' (our tag_matched == True)
                            #
                            # No additional validation needed - trust the tag_matcher
                            merged_by_tags = merged.copy()

                            self.logger.info(
                                f"✓ Tag matching (Trino-style): {len(merged_by_tags)} rows accepted (tag_matched=True)"
                            )

            # Combine both join strategies
            if not merged_by_resource_id.empty and not merged_by_tags.empty:
                # Combine and deduplicate (resource ID takes precedence)
                merged = pd.concat(
                    [merged_by_resource_id, merged_by_tags], ignore_index=True
                )
                merged = merged.drop_duplicates(
                    subset=["namespace", "pod", "usage_start", "lineitem_resourceid"],
                    keep="first",
                )
                self.logger.info(
                    f"✓ Combined joins: {len(merged)} rows after deduplication"
                )
            elif not merged_by_resource_id.empty:
                merged = merged_by_resource_id
            elif not merged_by_tags.empty:
                merged = merged_by_tags
            else:
                self.logger.warning("No successful joins between OCP and AWS")
                return pd.DataFrame()

            self.logger.info(
                "✓ Join complete",
                input_ocp=len(ocp_pod_usage_df),
                input_aws=len(aws_matched_df),
                output=len(merged),
            )

            return merged

    def calculate_attribution_ratio(self, merged_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate cost attribution ratio for each pod.

        Formula:
            attribution_ratio = max(CPU_ratio, Memory_ratio)

        Where:
            CPU_ratio = pod_usage_cpu / node_capacity_cpu
            Memory_ratio = pod_usage_memory / node_capacity_memory

        We use max() to be conservative (don't over-attribute costs).

        Args:
            merged_df: Joined OCP + AWS DataFrame

        Returns:
            DataFrame with attribution_ratio column added
        """
        with PerformanceTimer("Calculate attribution ratios", self.logger):
            if merged_df.empty:
                return merged_df

            df = merged_df.copy()

            # Calculate CPU ratio
            # OCP uses _seconds columns with _ocp suffix after merge, need to convert to hours
            cpu_usage_col = None
            cpu_capacity_col = None

            # Check for _seconds columns (actual OCP format)
            if "pod_usage_cpu_core_seconds_ocp" in df.columns:
                cpu_usage_col = "pod_usage_cpu_core_seconds_ocp"
            elif "pod_usage_cpu_core_seconds" in df.columns:
                cpu_usage_col = "pod_usage_cpu_core_seconds"
            elif "pod_usage_cpu_core_hours" in df.columns:
                cpu_usage_col = "pod_usage_cpu_core_hours"

            if "node_capacity_cpu_core_seconds_ocp" in df.columns:
                cpu_capacity_col = "node_capacity_cpu_core_seconds_ocp"
            elif "node_capacity_cpu_core_seconds" in df.columns:
                cpu_capacity_col = "node_capacity_cpu_core_seconds"
            elif "node_capacity_cpu_core_hours" in df.columns:
                cpu_capacity_col = "node_capacity_cpu_core_hours"

            if cpu_usage_col and cpu_capacity_col:
                # Convert seconds to hours if needed
                cpu_usage = df[cpu_usage_col]
                cpu_capacity = df[cpu_capacity_col]

                if "_seconds" in cpu_usage_col:
                    cpu_usage = cpu_usage / 3600
                if "_seconds" in cpu_capacity_col:
                    cpu_capacity = cpu_capacity / 3600

                df["cpu_ratio"] = cpu_usage / cpu_capacity.replace(0, np.nan)
                df["cpu_ratio"] = df["cpu_ratio"].fillna(0).clip(0, 1)  # Cap at 100%
            else:
                df["cpu_ratio"] = 0
                self.logger.warning(
                    "Missing CPU columns for attribution",
                    usage_col=cpu_usage_col,
                    capacity_col=cpu_capacity_col,
                )

            # Calculate Memory ratio
            # OCP uses byte_seconds, need to convert to gigabyte-hours
            mem_usage_col = None
            mem_capacity_col = None

            if "pod_usage_memory_byte_seconds_ocp" in df.columns:
                mem_usage_col = "pod_usage_memory_byte_seconds_ocp"
            elif "pod_usage_memory_byte_seconds" in df.columns:
                mem_usage_col = "pod_usage_memory_byte_seconds"
            elif "pod_usage_memory_gigabyte_hours" in df.columns:
                mem_usage_col = "pod_usage_memory_gigabyte_hours"

            if "node_capacity_memory_byte_seconds_ocp" in df.columns:
                mem_capacity_col = "node_capacity_memory_byte_seconds_ocp"
            elif "node_capacity_memory_byte_seconds" in df.columns:
                mem_capacity_col = "node_capacity_memory_byte_seconds"
            elif "node_capacity_memory_gigabyte_hours" in df.columns:
                mem_capacity_col = "node_capacity_memory_gigabyte_hours"

            if mem_usage_col and mem_capacity_col:
                # Convert byte-seconds to gigabyte-hours if needed
                mem_usage = df[mem_usage_col]
                mem_capacity = df[mem_capacity_col]

                if "_byte_seconds" in mem_usage_col:
                    mem_usage = (
                        mem_usage / 3600 / (1024**3)
                    )  # seconds→hours, bytes→GB
                if "_byte_seconds" in mem_capacity_col:
                    mem_capacity = mem_capacity / 3600 / (1024**3)

                df["memory_ratio"] = mem_usage / mem_capacity.replace(0, np.nan)
                df["memory_ratio"] = (
                    df["memory_ratio"].fillna(0).clip(0, 1)
                )  # Cap at 100%
            else:
                df["memory_ratio"] = 0
                self.logger.warning(
                    "Missing memory columns for attribution",
                    usage_col=mem_usage_col,
                    capacity_col=mem_capacity_col,
                )

            # Calculate attribution ratio based on configured method
            if self.distribution_method == "cpu":
                # CPU-only attribution (Trino-compatible)
                df["attribution_ratio"] = df["cpu_ratio"]
            elif self.distribution_method == "memory":
                # Memory-only attribution
                df["attribution_ratio"] = df["memory_ratio"]
            elif self.distribution_method == "weighted":
                # Weighted CPU + Memory (industry standard)
                df["attribution_ratio"] = (
                    df["cpu_ratio"] * self.cpu_weight
                    + df["memory_ratio"] * self.memory_weight
                )
            else:
                # Fallback to max (legacy POC behavior)
                self.logger.warning(
                    f"Unknown distribution method '{self.distribution_method}', using max"
                )
                df["attribution_ratio"] = np.maximum(
                    df["cpu_ratio"], df["memory_ratio"]
                )

            # DEBUG: Check for zero attribution ratios
            zero_ratios = (df["attribution_ratio"] == 0).sum()
            if zero_ratios > 0:
                # Use the actual column names we found
                sample_pod_cpu = None
                sample_node_cpu = None
                if cpu_usage_col and cpu_usage_col in df.columns:
                    sample_pod_cpu = df[cpu_usage_col].head(5).tolist()
                if cpu_capacity_col and cpu_capacity_col in df.columns:
                    sample_node_cpu = df[cpu_capacity_col].head(5).tolist()

                self.logger.warning(
                    f"DEBUG: {zero_ratios} rows have attribution_ratio=0!",
                    sample_cpu_ratio=df["cpu_ratio"].head(5).tolist(),
                    sample_memory_ratio=df["memory_ratio"].head(5).tolist(),
                    sample_pod_cpu=sample_pod_cpu,
                    sample_node_cpu=sample_node_cpu,
                    cpu_usage_col=cpu_usage_col,
                    cpu_capacity_col=cpu_capacity_col,
                )

            # Log statistics
            avg_ratio = df["attribution_ratio"].mean()
            median_ratio = df["attribution_ratio"].median()
            max_ratio = df["attribution_ratio"].max()

            self.logger.info(
                "✓ Attribution ratios calculated",
                avg=f"{avg_ratio:.3f}",
                median=f"{median_ratio:.3f}",
                max=f"{max_ratio:.3f}",
            )

            return df

    def attribute_costs(self, merged_df: pd.DataFrame) -> pd.DataFrame:
        """
        Attribute AWS costs to OCP pods.

        Calculates 4 cost types × 2 (cost + markup) = 8 cost columns:
        1. Unblended cost (standard AWS cost)
        2. Blended cost (reserved instance aware)
        3. Savings Plan effective cost
        4. Calculated amortized cost

        Each with markup applied.

        Formula:
            pod_cost = aws_cost × attribution_ratio
            pod_markup_cost = pod_cost × markup

        Args:
            merged_df: DataFrame with attribution_ratio column

        Returns:
            DataFrame with attributed cost columns
        """
        with PerformanceTimer("Attribute costs", self.logger):
            if merged_df.empty:
                return merged_df

            df = merged_df.copy()

            # Ensure we have attribution_ratio
            if "attribution_ratio" not in df.columns:
                df = self.calculate_attribution_ratio(df)

            # Normalize attribution ratios within each (node, timestamp) group
            # Multiple pods on the same node at the same time should split the cost
            # Example: If 2 pods each have 50% ratio, normalize so each gets 25%
            if (
                "matched_resource_id" in df.columns
                or "lineitem_resourceid_aws" in df.columns
            ):
                # Use AWS timestamp for grouping (hourly granularity)
                # After merge, AWS columns have _aws suffix
                timestamp_col = None
                if "lineitem_usagestartdate_aws" in df.columns:
                    timestamp_col = "lineitem_usagestartdate_aws"
                elif "lineitem_usagestartdate" in df.columns:
                    timestamp_col = "lineitem_usagestartdate"
                elif "usage_date" in df.columns:
                    timestamp_col = "usage_date"

                # For tag matching, use lineitem_resourceid from AWS side
                # For resource ID matching, use matched_resource_id
                resource_col = None

                # Try AWS-side lineitem_resourceid first (works for both tag and resource ID matching)
                if "lineitem_resourceid_aws" in df.columns:
                    # Check if it has non-null values
                    if df["lineitem_resourceid_aws"].notna().any():
                        resource_col = "lineitem_resourceid_aws"

                if not resource_col and "lineitem_resourceid" in df.columns:
                    if df["lineitem_resourceid"].notna().any():
                        resource_col = "lineitem_resourceid"

                # Fallback to matched_resource_id (for resource ID matching only)
                if not resource_col and "matched_resource_id" in df.columns:
                    if df["matched_resource_id"].notna().any():
                        resource_col = "matched_resource_id"

                if timestamp_col and resource_col:
                    # Group by AWS resource and timestamp (same node, same hour)
                    df["ratio_sum"] = df.groupby([resource_col, timestamp_col])[
                        "attribution_ratio"
                    ].transform("sum")
                    # Normalize: each pod gets (its_ratio / sum_of_ratios) × AWS_cost
                    df["attribution_ratio_normalized"] = df["attribution_ratio"] / df[
                        "ratio_sum"
                    ].replace(0, 1)
                    # Use normalized ratio for cost attribution
                    df["attribution_ratio"] = df["attribution_ratio_normalized"]
                    df = df.drop(columns=["ratio_sum", "attribution_ratio_normalized"])

                    self.logger.info(
                        "✓ Normalized attribution ratios within resource groups",
                        groupby_col=timestamp_col,
                        resource_col=resource_col,
                        avg_normalized=f"{df['attribution_ratio'].mean():.3f}",
                        max_normalized=f"{df['attribution_ratio'].max():.3f}",
                    )
                else:
                    self.logger.warning(
                        "Missing columns for normalization",
                        timestamp_col=timestamp_col,
                        resource_col=resource_col,
                        available_cols=list(df.columns[:20]),
                    )

            # Cost Type 1: Unblended Cost
            # After merge with suffixes=('_ocp', '_aws'), AWS columns have _aws suffix
            cost_col = (
                "lineitem_unblendedcost_aws"
                if "lineitem_unblendedcost_aws" in df.columns
                else "lineitem_unblendedcost"
            )
            if cost_col in df.columns:
                df["unblended_cost"] = df[cost_col] * df["attribution_ratio"]
                df["markup_cost"] = df["unblended_cost"] * self.markup
            else:
                df["unblended_cost"] = 0
                df["markup_cost"] = 0

            # Cost Type 2: Blended Cost
            cost_col = (
                "lineitem_blendedcost_aws"
                if "lineitem_blendedcost_aws" in df.columns
                else "lineitem_blendedcost"
            )
            if cost_col in df.columns:
                df["blended_cost"] = df[cost_col] * df["attribution_ratio"]
                df["markup_cost_blended"] = df["blended_cost"] * self.markup
            else:
                df["blended_cost"] = 0
                df["markup_cost_blended"] = 0

            # Cost Type 3: Savings Plan Effective Cost
            cost_col = (
                "savingsplan_savingsplaneffectivecost_aws"
                if "savingsplan_savingsplaneffectivecost_aws" in df.columns
                else "savingsplan_savingsplaneffectivecost"
            )
            if cost_col in df.columns:
                df["savingsplan_effective_cost"] = (
                    df[cost_col] * df["attribution_ratio"]
                )
                df["markup_cost_savingsplan"] = (
                    df["savingsplan_effective_cost"] * self.markup
                )
            else:
                df["savingsplan_effective_cost"] = 0
                df["markup_cost_savingsplan"] = 0

            # Cost Type 4: Calculated Amortized Cost
            # This needs to be derived from public on-demand cost
            cost_col = (
                "pricing_publicondemandcost_aws"
                if "pricing_publicondemandcost_aws" in df.columns
                else "pricing_publicondemandcost"
            )
            if cost_col in df.columns:
                df["calculated_amortized_cost"] = df[cost_col] * df["attribution_ratio"]
                df["markup_cost_amortized"] = (
                    df["calculated_amortized_cost"] * self.markup
                )
            else:
                df["calculated_amortized_cost"] = 0
                df["markup_cost_amortized"] = 0

            # Log cost statistics
            total_unblended = df["unblended_cost"].sum()
            total_markup = df["markup_cost"].sum()

            self.logger.info(
                "✓ Costs attributed",
                total_unblended=f"${total_unblended:,.2f}",
                total_markup=f"${total_markup:,.2f}",
                rows=len(df),
            )

            return df

    def attribute_compute_costs(
        self, ocp_pod_usage_df: pd.DataFrame, aws_matched_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Complete workflow: Join OCP with AWS and attribute compute costs.

        This is the main entry point for compute cost attribution.

        Steps:
        1. Join OCP pod usage with matched AWS resources
        2. Calculate attribution ratios
        3. Attribute costs (4 types + markup)

        Args:
            ocp_pod_usage_df: OCP pod usage DataFrame
            aws_matched_df: Matched AWS resources

        Returns:
            DataFrame with attributed costs
        """
        with PerformanceTimer("Attribute compute costs (complete)", self.logger):
            # Join
            merged = self.join_ocp_with_aws(ocp_pod_usage_df, aws_matched_df)

            if merged.empty:
                self.logger.warning("No joined data, returning empty DataFrame")
                return pd.DataFrame()

            # Calculate ratios
            merged = self.calculate_attribution_ratio(merged)

            # Attribute costs
            merged = self.attribute_costs(merged)

            self.logger.info(
                "✓ Compute cost attribution complete",
                pods=merged["pod"].nunique() if "pod" in merged.columns else 0,
                namespaces=merged["namespace"].nunique()
                if "namespace" in merged.columns
                else 0,
                total_cost=f"${merged['unblended_cost'].sum():,.2f}"
                if "unblended_cost" in merged.columns
                else "$0",
            )

            return merged

    def attribute_storage_costs(
        self,
        ocp_storage_usage_df: pd.DataFrame,
        matched_aws_df: pd.DataFrame,
        disk_capacities: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Attribute AWS storage (EBS) costs to OCP namespaces based on PVC usage.

        Formula (from Trino SQL line 250):
            storage_cost = (pvc_capacity_gb / total_disk_capacity_gb) * aws_volume_cost

        Args:
            ocp_storage_usage_df: OCP storage usage with PVC info
            matched_aws_df: Matched AWS resources (filtered to EBS)
            disk_capacities: Calculated disk capacities (from disk_capacity_calculator)

        Returns:
            DataFrame with attributed storage costs per namespace
        """
        with PerformanceTimer("Attribute storage costs", self.logger):
            if (
                ocp_storage_usage_df.empty
                or matched_aws_df.empty
                or disk_capacities.empty
            ):
                self.logger.info("No storage data to attribute")
                return pd.DataFrame()

            # Filter AWS to only EBS volumes
            ebs_aws = matched_aws_df[
                (matched_aws_df["lineitem_productcode"] == "AmazonEC2")
                & (matched_aws_df["lineitem_usagetype"].str.contains("EBS:", na=False))
            ].copy()

            if ebs_aws.empty:
                self.logger.info("No EBS costs found in matched AWS data")
                return pd.DataFrame()

            self.logger.info(
                f"Found {len(ebs_aws)} EBS line items for storage attribution"
            )

            # Extract usage date from AWS data
            if "usage_date" not in ebs_aws.columns:
                if "lineitem_usagestartdate" in ebs_aws.columns:
                    ebs_aws["usage_date"] = pd.to_datetime(
                        ebs_aws["lineitem_usagestartdate"]
                    ).dt.date
                else:
                    self.logger.error("Cannot find usage date column in AWS data")
                    return pd.DataFrame()

            # Aggregate EBS costs by resource_id and usage date
            ebs_daily = (
                ebs_aws.groupby(["lineitem_resourceid", "usage_date"])
                .agg(
                    {
                        "lineitem_unblendedcost": "sum",
                        "lineitem_blendedcost": "sum",
                        "savingsplan_savingsplaneffectivecost": "sum",
                        "lineitem_normalizedusageamount": "sum",
                        "lineitem_usageamount": "sum",
                    }
                )
                .reset_index()
            )

            ebs_daily.rename(
                columns={"lineitem_resourceid": "resource_id"}, inplace=True
            )

            # Rename usage_start to usage_date for consistency
            if "usage_start" in disk_capacities.columns:
                disk_capacities_with_date = disk_capacities.copy()
                disk_capacities_with_date["usage_date"] = disk_capacities_with_date[
                    "usage_start"
                ]
            else:
                disk_capacities_with_date = disk_capacities.copy()

            # Merge disk capacities with EBS costs
            storage_with_cost = disk_capacities_with_date.merge(
                ebs_daily, on=["resource_id", "usage_date"], how="inner"
            )

            if storage_with_cost.empty:
                self.logger.warning("No matches between disk capacities and EBS costs")
                return pd.DataFrame()

            self.logger.info(
                f"Matched {len(storage_with_cost)} capacity records with EBS costs"
            )

            # Prepare OCP storage data with PVC capacities
            # Aggregate by namespace, PV, and date
            ocp_storage = ocp_storage_usage_df.copy()

            # Convert interval_start to date
            if pd.api.types.is_string_dtype(ocp_storage["interval_start"]):
                ocp_storage["usage_date"] = pd.to_datetime(
                    ocp_storage["interval_start"].str.replace(
                        r" \+\d{4} UTC$", "", regex=True
                    )
                ).dt.date
            else:
                ocp_storage["usage_date"] = pd.to_datetime(
                    ocp_storage["interval_start"]
                ).dt.date

            # Get PVC capacity in GB
            # The column is persistentvolumeclaim_capacity_byte_seconds (not _bytes)
            # Calculate average capacity: byte_seconds / 3600 (hour) / 1024^3 (GB)
            if "persistentvolumeclaim_capacity_byte_seconds" in ocp_storage.columns:
                ocp_storage["pvc_capacity_gb"] = (
                    ocp_storage["persistentvolumeclaim_capacity_byte_seconds"]
                    / 3600
                    / (1024**3)
                )
            elif "persistentvolumeclaim_capacity_gigabyte" in ocp_storage.columns:
                ocp_storage["pvc_capacity_gb"] = ocp_storage[
                    "persistentvolumeclaim_capacity_gigabyte"
                ]
            else:
                self.logger.error("Cannot find PVC capacity column in OCP storage data")
                return pd.DataFrame()

            # Aggregate by namespace, PV, and date
            # IMPORTANT: Fill NaN in csi_volume_handle with empty string to prevent pandas groupby from dropping rows
            # (pandas groupby drops NaN values by default)
            ocp_storage["csi_volume_handle"] = ocp_storage["csi_volume_handle"].fillna(
                ""
            )
            ocp_storage["persistentvolume"] = ocp_storage["persistentvolume"].fillna("")

            agg_cols = [
                "namespace",
                "persistentvolume",
                "csi_volume_handle",
                "usage_date",
            ]
            agg_dict = {"pvc_capacity_gb": "max"}

            # Add cluster_id if available
            if "cluster_id" in ocp_storage.columns:
                agg_dict["cluster_id"] = "first"

            # DEBUG: Check OCP storage data before aggregation
            self.logger.info(
                f"OCP storage before agg: {len(ocp_storage)} rows, "
                f"csi_volume_handle sample: {ocp_storage['csi_volume_handle'].head(3).tolist()}, "
                f"persistentvolume sample: {ocp_storage['persistentvolume'].head(3).tolist()}"
            )

            ocp_storage_agg = ocp_storage.groupby(agg_cols).agg(agg_dict).reset_index()

            # DEBUG: Check after aggregation
            self.logger.info(f"OCP storage after agg: {len(ocp_storage_agg)} rows")

            # Match CSI handle OR PV name to resource_id (Trino parity)
            # Trino: (persistentvolume != '' OR csi_volume_handle != '')
            # Use CSI handle if available, otherwise fall back to PV name
            ocp_storage_agg["resource_id"] = ocp_storage_agg.apply(
                lambda row: row["csi_volume_handle"]
                if (
                    pd.notna(row["csi_volume_handle"])
                    and row["csi_volume_handle"] != ""
                )
                else row["persistentvolume"],
                axis=1,
            )

            # DEBUG: Log resource IDs on both sides
            self.logger.info(
                f"OCP storage resource_ids: {ocp_storage_agg['resource_id'].unique().tolist()}"
            )
            self.logger.info(
                f"AWS EBS resource_ids: {storage_with_cost['resource_id'].unique().tolist()[:10]}"
            )
            self.logger.info(
                f"OCP usage_dates: {ocp_storage_agg['usage_date'].unique().tolist()}"
            )
            self.logger.info(
                f"AWS usage_dates: {storage_with_cost['usage_date'].unique().tolist()[:5]}"
            )

            # Join storage costs with OCP storage using SUFFIX MATCHING (Trino parity)
            # Trino SQL: substr(resource_id, -length(csi_volume_handle)) = csi_volume_handle
            # AWS resource_ids often have prefixes (e.g., 'vol-shared-disk-001' vs 'shared-disk-001')

            # Create suffix matching function
            def suffix_match_storage(ocp_df, aws_df):
                """Match OCP storage to AWS EBS using suffix matching on resource_id."""
                matches = []

                for _, ocp_row in ocp_df.iterrows():
                    ocp_resource_id = ocp_row["resource_id"]
                    ocp_date = ocp_row["usage_date"]

                    # Find AWS records where resource_id ENDS WITH OCP resource_id
                    for _, aws_row in aws_df.iterrows():
                        aws_resource_id = aws_row["resource_id"]
                        aws_date = aws_row["usage_date"]

                        # Suffix matching + date matching
                        if (
                            str(aws_resource_id).endswith(str(ocp_resource_id))
                            and ocp_date == aws_date
                        ):
                            # Create merged row with OCP data first
                            merged_row = ocp_row.to_dict()
                            # Copy AWS cost columns
                            for col in [
                                "capacity",
                                "lineitem_unblendedcost",
                                "lineitem_blendedcost",
                                "savingsplan_savingsplaneffectivecost",
                                "lineitem_normalizedusageamount",
                                "lineitem_usageamount",
                            ]:
                                if col in aws_row:
                                    merged_row[col] = aws_row[col]
                            # Ensure usage_date is preserved for downstream processing
                            merged_row["usage_date"] = ocp_date
                            matches.append(merged_row)
                            break  # Only match once per OCP row

                return pd.DataFrame(matches) if matches else pd.DataFrame()

            # Try exact match first (fast path)
            attributed = ocp_storage_agg.merge(
                storage_with_cost, on=["resource_id", "usage_date"], how="inner"
            )

            # If exact match fails, try suffix matching (Trino parity)
            if attributed.empty:
                self.logger.info(
                    "Exact match failed, trying suffix matching (Trino parity)"
                )
                attributed = suffix_match_storage(ocp_storage_agg, storage_with_cost)

            if attributed.empty:
                self.logger.warning("No matches between OCP storage and EBS costs")
                return pd.DataFrame()

            # Ensure usage_start column exists (required for output formatting)
            if (
                "usage_start" not in attributed.columns
                and "usage_date" in attributed.columns
            ):
                attributed["usage_start"] = attributed["usage_date"]

            # Apply the Trino formula: (pvc_capacity / disk_capacity) * cost
            attributed["unblended_cost"] = (
                attributed["pvc_capacity_gb"] / attributed["capacity"]
            ) * attributed["lineitem_unblendedcost"]
            attributed["blended_cost"] = (
                attributed["pvc_capacity_gb"] / attributed["capacity"]
            ) * attributed["lineitem_blendedcost"]
            attributed["savingsplan_effective_cost"] = (
                attributed["pvc_capacity_gb"] / attributed["capacity"]
            ) * attributed["savingsplan_savingsplaneffectivecost"]
            attributed["calculated_amortized_cost"] = attributed[
                "unblended_cost"
            ]  # Simplified

            # Apply markup
            markup = self.DEFAULT_MARKUP
            attributed["markup_cost"] = attributed["unblended_cost"] * markup
            attributed["markup_cost_blended"] = attributed["blended_cost"] * markup
            attributed["markup_cost_savingsplan"] = (
                attributed["savingsplan_effective_cost"] * markup
            )
            attributed["markup_cost_amortized"] = (
                attributed["calculated_amortized_cost"] * markup
            )

            # SCENARIO 18 FIX: Calculate "Storage unattributed" for unused disk capacity
            # Trino SQL: When sum(pvc_capacity) < disk_capacity, the remainder goes to 'Storage unattributed'
            # Formula: unattributed_cost = (1 - sum(pvc_capacity)/disk_capacity) * disk_cost
            unattributed_records = []

            for _, cost_row in storage_with_cost.iterrows():
                resource_id = cost_row["resource_id"]
                disk_capacity = cost_row["capacity"]
                disk_cost_unblended = cost_row["lineitem_unblendedcost"]
                disk_cost_blended = cost_row["lineitem_blendedcost"]
                disk_cost_savings = cost_row.get(
                    "savingsplan_savingsplaneffectivecost", 0
                )
                usage_date = cost_row["usage_date"]

                # Calculate sum of PVC capacities for this disk
                # Filter attributed records for this disk (by resource_id match)
                disk_attributed = attributed[
                    attributed.apply(
                        lambda row: str(resource_id).endswith(
                            str(row.get("resource_id", ""))
                        ),
                        axis=1,
                    )
                ]

                if not disk_attributed.empty:
                    total_pvc_capacity = disk_attributed["pvc_capacity_gb"].sum()

                    # Calculate unattributed portion
                    unattributed_ratio = max(
                        0, 1 - (total_pvc_capacity / disk_capacity)
                    )

                    if (
                        unattributed_ratio > 0.001
                    ):  # Only create record if >0.1% unattributed
                        unattributed_cost = unattributed_ratio * disk_cost_unblended
                        unattributed_blended = unattributed_ratio * disk_cost_blended
                        unattributed_savings = unattributed_ratio * disk_cost_savings

                        # Get cluster_ids from attributed records (for multi-cluster split)
                        cluster_ids = (
                            disk_attributed["cluster_id"].dropna().unique().tolist()
                            if "cluster_id" in disk_attributed.columns
                            else []
                        )

                        # If multiple clusters, split unattributed equally
                        num_clusters = max(1, len(cluster_ids))
                        cost_per_cluster = unattributed_cost / num_clusters
                        blended_per_cluster = unattributed_blended / num_clusters
                        savings_per_cluster = unattributed_savings / num_clusters

                        for cluster_id in cluster_ids if cluster_ids else [None]:
                            unattributed_records.append(
                                {
                                    "namespace": "Storage unattributed",
                                    "persistentvolume": "",
                                    "csi_volume_handle": "",
                                    "usage_date": usage_date,
                                    "usage_start": usage_date,
                                    "pvc_capacity_gb": unattributed_ratio
                                    * disk_capacity
                                    / num_clusters,
                                    "capacity": disk_capacity,
                                    "unblended_cost": cost_per_cluster,
                                    "blended_cost": blended_per_cluster,
                                    "savingsplan_effective_cost": savings_per_cluster,
                                    "calculated_amortized_cost": cost_per_cluster,
                                    "markup_cost": cost_per_cluster * markup,
                                    "markup_cost_blended": blended_per_cluster * markup,
                                    "markup_cost_savingsplan": savings_per_cluster
                                    * markup,
                                    "markup_cost_amortized": cost_per_cluster * markup,
                                    "cluster_id": cluster_id,
                                    "resource_id": resource_id,
                                }
                            )

                        self.logger.info(
                            f"Storage unattributed: {unattributed_ratio*100:.1f}% of {resource_id} "
                            f"(${unattributed_cost:.2f}) split across {num_clusters} cluster(s)"
                        )

            # Append unattributed records to attributed
            if unattributed_records:
                unattributed_df = pd.DataFrame(unattributed_records)
                attributed = pd.concat([attributed, unattributed_df], ignore_index=True)

            self.logger.info(
                "✓ Storage cost attribution complete",
                namespaces=attributed["namespace"].nunique(),
                volumes=attributed["persistentvolume"].nunique(),
                total_storage_cost=f"${attributed['unblended_cost'].sum():,.2f}",
            )

            return attributed

    def attribute_tag_matched_storage(
        self, matched_aws_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Attribute tag-matched EBS storage costs directly to namespaces.

        SCENARIO 19 FIX: When EBS volumes are tagged with 'openshift_project' but there's
        no CSI handle match (non-CSI storage), attribute costs directly to the namespace.

        Trino SQL: json_query(aws.resourcetags, '$.openshift_project') = ocp.namespace

        Args:
            matched_aws_df: AWS DataFrame with tag_matched and matched_tag_namespace columns

        Returns:
            DataFrame with tag-matched storage costs attributed to namespaces
        """
        with PerformanceTimer("Attribute tag-matched storage", self.logger):
            if matched_aws_df.empty:
                self.logger.info("No AWS data for tag-matched storage attribution")
                return pd.DataFrame()

            # Filter to tag-matched EBS storage only
            # Must have: tag_matched=True, matched_ocp_namespace set, and be EBS storage
            is_tag_matched = matched_aws_df.get(
                "tag_matched", pd.Series([False] * len(matched_aws_df))
            ).fillna(False)
            # Check for matched_ocp_namespace (from openshift_project tag)
            has_namespace = (
                matched_aws_df.get(
                    "matched_ocp_namespace", pd.Series([""] * len(matched_aws_df))
                )
                .fillna("")
                .astype(str)
                .str.len()
                > 0
            )

            # Check for EBS storage
            is_ebs = pd.Series([False] * len(matched_aws_df))
            if "lineitem_usagetype" in matched_aws_df.columns:
                is_ebs = matched_aws_df["lineitem_usagetype"].str.contains(
                    "EBS:", na=False
                )
            elif "product_productfamily" in matched_aws_df.columns:
                is_ebs = matched_aws_df["product_productfamily"].str.contains(
                    "Storage", na=False
                )

            tag_matched_storage = matched_aws_df[
                is_tag_matched & has_namespace & is_ebs
            ].copy()

            if tag_matched_storage.empty:
                self.logger.info("No tag-matched EBS storage to attribute")
                return pd.DataFrame()

            self.logger.info(
                f"Found {len(tag_matched_storage)} tag-matched EBS storage records"
            )

            # Extract namespace from tag
            tag_matched_storage["namespace"] = tag_matched_storage[
                "matched_ocp_namespace"
            ]

            # Extract usage_start
            if "lineitem_usagestartdate" in tag_matched_storage.columns:
                tag_matched_storage["usage_start"] = pd.to_datetime(
                    tag_matched_storage["lineitem_usagestartdate"]
                ).dt.tz_localize(None)

            # Aggregate by namespace and date
            # Tag-matched storage gets FULL cost (no PVC proportioning)
            agg_cols = ["namespace"]
            if "usage_start" in tag_matched_storage.columns:
                agg_cols.append("usage_start")

            agg_dict = {
                "lineitem_unblendedcost": "sum",
                "lineitem_blendedcost": "sum",
            }

            if "savingsplan_savingsplaneffectivecost" in tag_matched_storage.columns:
                agg_dict["savingsplan_savingsplaneffectivecost"] = "sum"

            attributed = tag_matched_storage.groupby(agg_cols, as_index=False).agg(
                agg_dict
            )

            # Rename cost columns
            attributed.rename(
                columns={
                    "lineitem_unblendedcost": "unblended_cost",
                    "lineitem_blendedcost": "blended_cost",
                },
                inplace=True,
            )

            # Add savingsplan if present
            if "savingsplan_savingsplaneffectivecost" in attributed.columns:
                attributed.rename(
                    columns={
                        "savingsplan_savingsplaneffectivecost": "savingsplan_effective_cost"
                    },
                    inplace=True,
                )
            else:
                attributed["savingsplan_effective_cost"] = 0.0

            attributed["calculated_amortized_cost"] = attributed["unblended_cost"]

            # Apply markup
            markup = self.DEFAULT_MARKUP
            attributed["markup_cost"] = attributed["unblended_cost"] * markup
            attributed["markup_cost_blended"] = attributed["blended_cost"] * markup
            attributed["markup_cost_savingsplan"] = (
                attributed["savingsplan_effective_cost"] * markup
            )
            attributed["markup_cost_amortized"] = (
                attributed["calculated_amortized_cost"] * markup
            )

            # Add data_source indicator
            attributed["data_source"] = "Storage"

            self.logger.info(
                "✓ Tag-matched storage attribution complete",
                namespaces=attributed["namespace"].nunique(),
                total_storage_cost=f"${attributed['unblended_cost'].sum():,.2f}",
            )

            return attributed

    def attribute_untagged_storage(
        self,
        matched_aws_df: pd.DataFrame,
        csi_attributed_resource_ids: set = None,
        tag_attributed_resource_ids: set = None,
    ) -> pd.DataFrame:
        """
        Attribute untagged EBS storage costs to 'Storage unattributed' namespace.

        SCENARIO 19 FIX: EBS volumes that are matched to a cluster but:
        1. Were NOT attributed via CSI matching
        2. Were NOT attributed via openshift_project tag matching
        Should go to "Storage unattributed" namespace.

        Args:
            matched_aws_df: AWS DataFrame with matching info
            csi_attributed_resource_ids: Set of resource_ids already attributed via CSI
            tag_attributed_resource_ids: Set of resource_ids already attributed via tag

        Returns:
            DataFrame with untagged storage costs attributed to 'Storage unattributed'
        """
        with PerformanceTimer("Attribute untagged storage", self.logger):
            if matched_aws_df.empty:
                return pd.DataFrame()

            csi_attributed_resource_ids = csi_attributed_resource_ids or set()
            tag_attributed_resource_ids = tag_attributed_resource_ids or set()

            # Filter to EBS storage only
            is_ebs = pd.Series([False] * len(matched_aws_df))
            if "lineitem_usagetype" in matched_aws_df.columns:
                is_ebs = matched_aws_df["lineitem_usagetype"].str.contains(
                    "EBS:", na=False
                )

            # Must be tag-matched (has openshift_cluster tag)
            # EBS without any openshift tags should remain unmatched
            is_tag_matched = matched_aws_df.get(
                "tag_matched", pd.Series([False] * len(matched_aws_df))
            ).fillna(False)

            # NOT attributed to a specific namespace (no openshift_project tag)
            has_namespace = (
                matched_aws_df.get(
                    "matched_ocp_namespace", pd.Series([""] * len(matched_aws_df))
                )
                .fillna("")
                .astype(str)
                .str.len()
                > 0
            )

            # Exclude already attributed resources
            already_attributed = matched_aws_df["lineitem_resourceid"].isin(
                csi_attributed_resource_ids | tag_attributed_resource_ids
            )

            # Untagged = EBS + TAG_MATCHED + NO namespace + NOT already attributed
            # Only EBS that was tag-matched to cluster but has no openshift_project
            untagged_ebs = matched_aws_df[
                is_ebs & is_tag_matched & ~has_namespace & ~already_attributed
            ].copy()

            if untagged_ebs.empty:
                self.logger.info("No untagged EBS storage to attribute")
                return pd.DataFrame()

            self.logger.info(f"Found {len(untagged_ebs)} untagged EBS storage records")

            # Set namespace to "Storage unattributed"
            untagged_ebs["namespace"] = "Storage unattributed"

            # Extract usage_start
            if "lineitem_usagestartdate" in untagged_ebs.columns:
                untagged_ebs["usage_start"] = pd.to_datetime(
                    untagged_ebs["lineitem_usagestartdate"]
                ).dt.tz_localize(None)

            # Aggregate by date
            agg_cols = ["namespace"]
            if "usage_start" in untagged_ebs.columns:
                agg_cols.append("usage_start")

            agg_dict = {
                "lineitem_unblendedcost": "sum",
                "lineitem_blendedcost": "sum",
            }

            if "savingsplan_savingsplaneffectivecost" in untagged_ebs.columns:
                agg_dict["savingsplan_savingsplaneffectivecost"] = "sum"

            attributed = untagged_ebs.groupby(agg_cols, as_index=False).agg(agg_dict)

            # Rename cost columns
            attributed.rename(
                columns={
                    "lineitem_unblendedcost": "unblended_cost",
                    "lineitem_blendedcost": "blended_cost",
                },
                inplace=True,
            )

            if "savingsplan_savingsplaneffectivecost" in attributed.columns:
                attributed.rename(
                    columns={
                        "savingsplan_savingsplaneffectivecost": "savingsplan_effective_cost"
                    },
                    inplace=True,
                )
            else:
                attributed["savingsplan_effective_cost"] = 0.0

            attributed["calculated_amortized_cost"] = attributed["unblended_cost"]

            # Apply markup
            markup = self.DEFAULT_MARKUP
            attributed["markup_cost"] = attributed["unblended_cost"] * markup
            attributed["markup_cost_blended"] = attributed["blended_cost"] * markup
            attributed["markup_cost_savingsplan"] = (
                attributed["savingsplan_effective_cost"] * markup
            )
            attributed["markup_cost_amortized"] = (
                attributed["calculated_amortized_cost"] * markup
            )

            attributed["data_source"] = "Storage"

            self.logger.info(
                "✓ Untagged storage attribution complete",
                total_cost=f"${attributed['unblended_cost'].sum():,.2f}",
            )

            return attributed

    def attribute_network_costs(self, matched_aws_df: pd.DataFrame) -> pd.DataFrame:
        """
        Attribute network/data transfer costs to 'Network unattributed' namespace.

        Trino reference: 2_summarize_data_by_cluster.sql Lines 668-803

        Network costs are NOT attributed to pods. Instead, they go to a special
        'Network unattributed' namespace for tracking purposes.

        Args:
            matched_aws_df: Matched AWS DataFrame (including network line items)

        Returns:
            DataFrame with network costs attributed to 'Network unattributed' namespace
        """
        with PerformanceTimer("Attribute network costs", self.logger):
            # Filter to network costs only
            if "data_transfer_direction" not in matched_aws_df.columns:
                self.logger.info(
                    "No data_transfer_direction column, no network costs to attribute"
                )
                return pd.DataFrame()

            network_df = matched_aws_df[
                matched_aws_df["data_transfer_direction"].notna()
            ].copy()

            if network_df.empty:
                self.logger.info("No network costs to attribute")
                return pd.DataFrame()

            self.logger.info(f"Found {len(network_df)} network cost records")

            # Prepare network DataFrame for output
            network_df["namespace"] = "Network unattributed"

            # Extract usage_start
            if "lineitem_usagestartdate" in network_df.columns:
                network_df["usage_start"] = pd.to_datetime(
                    network_df["lineitem_usagestartdate"]
                ).dt.tz_localize(None)
            elif "usage_start" not in network_df.columns:
                self.logger.error("Cannot find usage_start column in network data")
                return pd.DataFrame()

            # Map cost columns
            network_attributed = network_df[
                [
                    "usage_start",
                    "namespace",
                    "lineitem_unblendedcost",
                    "lineitem_blendedcost",
                ]
            ].copy()

            # Add savingsplan and calculated_amortized_cost if available
            if "savingsplan_savingsplaneffectivecost" in network_df.columns:
                network_attributed["savingsplan_effective_cost"] = network_df[
                    "savingsplan_savingsplaneffectivecost"
                ]
            else:
                network_attributed["savingsplan_effective_cost"] = 0.0

            if "lineitem_calculated_amortizedcost" in network_df.columns:
                network_attributed["calculated_amortized_cost"] = network_df[
                    "lineitem_calculated_amortizedcost"
                ]
            else:
                network_attributed["calculated_amortized_cost"] = network_df[
                    "lineitem_unblendedcost"
                ]

            # Rename cost columns
            network_attributed.rename(
                columns={
                    "lineitem_unblendedcost": "unblended_cost",
                    "lineitem_blendedcost": "blended_cost",
                },
                inplace=True,
            )

            # Apply markup
            markup = self.DEFAULT_MARKUP
            network_attributed["markup_cost"] = (
                network_attributed["unblended_cost"] * markup
            )
            network_attributed["markup_cost_blended"] = (
                network_attributed["blended_cost"] * markup
            )
            network_attributed["markup_cost_savingsplan"] = (
                network_attributed["savingsplan_effective_cost"] * markup
            )
            network_attributed["markup_cost_amortized"] = (
                network_attributed["calculated_amortized_cost"] * markup
            )

            self.logger.info(
                "✓ Network cost attribution complete",
                records=len(network_attributed),
                total_network_cost=f"${network_attributed['unblended_cost'].sum():,.2f}",
            )

            return network_attributed

    def get_cost_summary(self, attributed_df: pd.DataFrame) -> Dict:
        """
        Get a summary of attributed costs.

        Args:
            attributed_df: DataFrame with attributed costs

        Returns:
            Dictionary with cost summary statistics
        """
        if attributed_df.empty:
            return {"status": "empty"}

        summary = {
            "total_rows": len(attributed_df),
            "unique_pods": attributed_df["pod"].nunique()
            if "pod" in attributed_df.columns
            else 0,
            "unique_namespaces": attributed_df["namespace"].nunique()
            if "namespace" in attributed_df.columns
            else 0,
            "costs": {},
        }

        # Cost summaries
        cost_columns = [
            "unblended_cost",
            "markup_cost",
            "blended_cost",
            "markup_cost_blended",
            "savingsplan_effective_cost",
            "markup_cost_savingsplan",
            "calculated_amortized_cost",
            "markup_cost_amortized",
        ]

        for col in cost_columns:
            if col in attributed_df.columns:
                summary["costs"][col] = float(attributed_df[col].sum())

        # Attribution ratio statistics
        if "attribution_ratio" in attributed_df.columns:
            summary["attribution_ratio"] = {
                "mean": float(attributed_df["attribution_ratio"].mean()),
                "median": float(attributed_df["attribution_ratio"].median()),
                "min": float(attributed_df["attribution_ratio"].min()),
                "max": float(attributed_df["attribution_ratio"].max()),
            }

        self.logger.info("Cost summary", **summary)
        return summary
