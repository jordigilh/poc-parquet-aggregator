"""OCP Pod usage aggregation logic (replicates Trino SQL)."""

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from .utils import (
    get_logger,
    parse_json_labels,
    filter_labels_by_enabled_keys,
    merge_label_dicts,
    labels_to_json_string,
    convert_seconds_to_hours,
    convert_bytes_to_gigabytes,
    safe_greatest,
    coalesce,
    PerformanceTimer,
)


class PodAggregator:
    """Aggregate OCP pod usage data (replicates Trino SQL lines 260-316)."""

    def __init__(self, config: Dict, enabled_tag_keys: List[str]):
        """Initialize pod aggregator.

        Args:
            config: Configuration dictionary
            enabled_tag_keys: List of enabled tag keys from PostgreSQL
        """
        self.config = config
        self.enabled_tag_keys = enabled_tag_keys
        self.logger = get_logger("aggregator_pod")

        # OCP configuration
        self.ocp_config = config['ocp']
        self.report_period_id = self.ocp_config['report_period_id']
        self.cluster_id = self.ocp_config['cluster_id']
        self.cluster_alias = self.ocp_config['cluster_alias']
        self.provider_uuid = self.ocp_config['provider_uuid']

        self.logger.info(
            "Initialized pod aggregator",
            cluster_id=self.cluster_id,
            enabled_tags_count=len(enabled_tag_keys)
        )

    def aggregate(
        self,
        pod_usage_df: pd.DataFrame,
        node_capacity_df: pd.DataFrame,
        node_labels_df: Optional[pd.DataFrame] = None,
        namespace_labels_df: Optional[pd.DataFrame] = None,
        cost_category_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Aggregate pod usage data by day + namespace + node.

        This replicates the main SELECT in Trino SQL (lines 260-316).

        Args:
            pod_usage_df: openshift_pod_usage_line_items_daily
            node_capacity_df: Pre-calculated node capacity by day
            node_labels_df: openshift_node_labels_line_items_daily (optional)
            namespace_labels_df: openshift_namespace_labels_line_items_daily (optional)
            cost_category_df: reporting_ocp_cost_category_namespace (optional)

        Returns:
            Aggregated DataFrame ready for PostgreSQL insert
        """
        with PerformanceTimer("Pod usage aggregation", self.logger):
            # Step 1: Pre-process labels
            pod_usage_df = self._prepare_pod_usage_data(pod_usage_df)

            # Step 2: Join with node labels
            if node_labels_df is not None and not node_labels_df.empty:
                pod_usage_df = self._join_node_labels(pod_usage_df, node_labels_df)
            else:
                pod_usage_df['node_labels'] = None

            # Step 3: Join with namespace labels
            if namespace_labels_df is not None and not namespace_labels_df.empty:
                pod_usage_df = self._join_namespace_labels(pod_usage_df, namespace_labels_df)
            else:
                pod_usage_df['namespace_labels'] = None

            # Step 4: Parse label strings into dictionaries
            from .utils import parse_json_labels
            pod_usage_df['node_labels_dict'] = pod_usage_df['node_labels'].apply(
                lambda x: parse_json_labels(x) if x is not None else {}
            )
            pod_usage_df['namespace_labels_dict'] = pod_usage_df['namespace_labels'].apply(
                lambda x: parse_json_labels(x) if x is not None else {}
            )
            pod_usage_df['pod_labels_dict'] = pod_usage_df['pod_labels'].apply(
                lambda x: parse_json_labels(x) if x is not None else {}
            )

            # Step 5: Merge pod/node/namespace labels
            pod_usage_df['merged_labels_dict'] = pod_usage_df.apply(
                lambda row: self._merge_all_labels(
                    row.get('node_labels_dict'),
                    row.get('namespace_labels_dict'),
                    row.get('pod_labels_dict')
                ),
                axis=1
            )

            # Step 6: Convert merged labels to JSON strings for grouping
            from .utils import labels_to_json_string
            pod_usage_df['merged_labels'] = pod_usage_df['merged_labels_dict'].apply(labels_to_json_string)

            # Step 7: Group and aggregate
            aggregated_df = self._group_and_aggregate(pod_usage_df)

            # Step 6: Join with node capacity
            aggregated_df = self._join_node_capacity(aggregated_df, node_capacity_df)

            # Step 7: Join with cost category (if available)
            if cost_category_df is not None and not cost_category_df.empty:
                aggregated_df = self._join_cost_category(aggregated_df, cost_category_df)
            else:
                aggregated_df['cost_category_id'] = None

            # Step 8: Format final output
            result_df = self._format_output(aggregated_df)

            self.logger.info(
                "Pod aggregation complete",
                input_rows=len(pod_usage_df),
                output_rows=len(result_df)
            )

            return result_df

    def _prepare_pod_usage_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare pod usage data (parse dates, parse labels).

        Args:
            df: Raw pod usage DataFrame

        Returns:
            Prepared DataFrame
        """
        df = df.copy()

        # Critical Filter: Exclude empty nodes (Trino SQL line 309: AND li.node != '')
        initial_count = len(df)
        df = df[df['node'].notna() & (df['node'] != '')]
        filtered_count = len(df)

        if initial_count > filtered_count:
            self.logger.warning(
                f"Filtered out {initial_count - filtered_count} rows with empty/null nodes",
                initial_rows=initial_count,
                filtered_rows=filtered_count
            )

        # Parse interval_start as date
        # Handle nise date format: "2025-11-01 00:00:00 +0000 UTC"
        df['interval_start_clean'] = df['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
        df['usage_start'] = pd.to_datetime(df['interval_start_clean']).dt.date
        df.drop('interval_start_clean', axis=1, inplace=True)

        # Parse pod_labels JSON
        df['pod_labels_dict'] = df['pod_labels'].apply(parse_json_labels)

        # Filter pod labels by enabled keys
        df['pod_labels_filtered'] = df['pod_labels_dict'].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        return df

    def _join_node_labels(
        self,
        pod_df: pd.DataFrame,
        node_labels_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Join with node labels.

        Args:
            pod_df: Pod usage DataFrame
            node_labels_df: Node labels DataFrame

        Returns:
            Joined DataFrame
        """
        # Parse node labels
        node_labels_df = node_labels_df.copy()
        node_labels_df['interval_start_clean'] = node_labels_df['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
        node_labels_df['usage_start'] = pd.to_datetime(node_labels_df['interval_start_clean']).dt.date
        node_labels_df.drop('interval_start_clean', axis=1, inplace=True)
        node_labels_df['node_labels_dict'] = node_labels_df['node_labels'].apply(parse_json_labels)

        # Filter by enabled keys
        node_labels_df['node_labels_filtered'] = node_labels_df['node_labels_dict'].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        # Select columns for join
        node_labels_join = node_labels_df[['usage_start', 'node', 'node_labels_filtered']].rename(
            columns={'node_labels_filtered': 'node_labels'}
        )

        # Left join
        return pod_df.merge(
            node_labels_join,
            on=['usage_start', 'node'],
            how='left'
        )

    def _join_namespace_labels(
        self,
        pod_df: pd.DataFrame,
        namespace_labels_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Join with namespace labels.

        Args:
            pod_df: Pod usage DataFrame
            namespace_labels_df: Namespace labels DataFrame

        Returns:
            Joined DataFrame
        """
        # Parse namespace labels
        namespace_labels_df = namespace_labels_df.copy()
        namespace_labels_df['interval_start_clean'] = namespace_labels_df['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
        namespace_labels_df['usage_start'] = pd.to_datetime(namespace_labels_df['interval_start_clean']).dt.date
        namespace_labels_df.drop('interval_start_clean', axis=1, inplace=True)
        namespace_labels_df['namespace_labels_dict'] = namespace_labels_df['namespace_labels'].apply(parse_json_labels)

        # Filter by enabled keys
        namespace_labels_df['namespace_labels_filtered'] = namespace_labels_df['namespace_labels_dict'].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        # Select columns for join
        namespace_labels_join = namespace_labels_df[['usage_start', 'namespace', 'namespace_labels_filtered']].rename(
            columns={'namespace_labels_filtered': 'namespace_labels'}
        )

        # Left join
        return pod_df.merge(
            namespace_labels_join,
            on=['usage_start', 'namespace'],
            how='left'
        )

    def _merge_all_labels(
        self,
        node_labels: Optional[Dict],
        namespace_labels: Optional[Dict],
        pod_labels: Optional[Dict]
    ) -> Dict[str, str]:
        """Merge node + namespace + pod labels (replicates Trino map_concat).

        Trino SQL logic (lines 266-273):
        - COALESCE NULL labels to empty map: map(array[], array[])
        - Merge order: node → namespace → pod (later overrides earlier)

        Args:
            node_labels: Node label dictionary (None → {})
            namespace_labels: Namespace label dictionary (None → {})
            pod_labels: Pod label dictionary (None → {})

        Returns:
            Merged label dictionary
        """
        # COALESCE NULL to empty dict (Trino: cast(map(array[], array[]) as json))
        node_labels = node_labels if node_labels is not None else {}
        namespace_labels = namespace_labels if namespace_labels is not None else {}
        pod_labels = pod_labels if pod_labels is not None else {}

        return merge_label_dicts(node_labels, namespace_labels, pod_labels)

    def _group_and_aggregate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group by (usage_start, namespace, node) and aggregate metrics.

        This replicates the GROUP BY and SUM/MAX logic in Trino SQL.

        Args:
            df: Prepared DataFrame

        Returns:
            Aggregated DataFrame
        """
        # Group by keys
        group_keys = ['usage_start', 'namespace', 'node', 'source', 'merged_labels']

        # Aggregation functions
        agg_funcs = {
            'resource_id': lambda x: x.iloc[0] if len(x) > 0 else None,  # Take first value (safer than max for mixed types)
            # CPU metrics (convert seconds to hours)
            'pod_usage_cpu_core_seconds': lambda x: convert_seconds_to_hours(x.sum()),
            'pod_request_cpu_core_seconds': lambda x: convert_seconds_to_hours(x.sum()),
            'pod_limit_cpu_core_seconds': lambda x: convert_seconds_to_hours(x.sum()),
            # Memory metrics (convert byte-seconds to GB-hours)
            'pod_usage_memory_byte_seconds': lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            'pod_request_memory_byte_seconds': lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            'pod_limit_memory_byte_seconds': lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            # Capacity metrics (max)
            'node_capacity_cpu_cores': 'max',
            'node_capacity_memory_bytes': lambda x: convert_bytes_to_gigabytes(x.max())
        }

        # Calculate effective usage before grouping
        # Trino SQL line 277: coalesce(li.pod_effective_usage_cpu_core_seconds,
        #                             greatest(li.pod_usage_cpu_core_seconds, li.pod_request_cpu_core_seconds))
        df['pod_effective_usage_cpu_core_seconds'] = df.apply(
                lambda row: coalesce(
                    row.get('pod_effective_usage_cpu_core_seconds'),
                    safe_greatest(
                        row.get('pod_usage_cpu_core_seconds'),
                        row.get('pod_request_cpu_core_seconds')
                    )
                ),
                axis=1
            )

            # Same logic for memory (Trino SQL line 281)
        df['pod_effective_usage_memory_byte_seconds'] = df.apply(
            lambda row: coalesce(
                row.get('pod_effective_usage_memory_byte_seconds'),
                safe_greatest(
                    row.get('pod_usage_memory_byte_seconds'),
                    row.get('pod_request_memory_byte_seconds')
                )
            ),
            axis=1
        )

        # Add effective usage to aggregation
        agg_funcs['pod_effective_usage_cpu_core_seconds'] = lambda x: convert_seconds_to_hours(x.sum())
        agg_funcs['pod_effective_usage_memory_byte_seconds'] = lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum()))

        # Group and aggregate
        aggregated = df.groupby(group_keys, dropna=False).agg(agg_funcs).reset_index()

        # Rename columns to match output schema
        aggregated = aggregated.rename(columns={
            'source': 'source_uuid',
            'pod_usage_cpu_core_seconds': 'pod_usage_cpu_core_hours',
            'pod_request_cpu_core_seconds': 'pod_request_cpu_core_hours',
            'pod_effective_usage_cpu_core_seconds': 'pod_effective_usage_cpu_core_hours',
            'pod_limit_cpu_core_seconds': 'pod_limit_cpu_core_hours',
            'pod_usage_memory_byte_seconds': 'pod_usage_memory_gigabyte_hours',
            'pod_request_memory_byte_seconds': 'pod_request_memory_gigabyte_hours',
            'pod_effective_usage_memory_byte_seconds': 'pod_effective_usage_memory_gigabyte_hours',
            'pod_limit_memory_byte_seconds': 'pod_limit_memory_gigabyte_hours',
            'node_capacity_memory_bytes': 'node_capacity_memory_gigabytes'
        })

        return aggregated

    def _join_node_capacity(
        self,
        aggregated_df: pd.DataFrame,
        node_capacity_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Join with pre-calculated node capacity.

        Args:
            aggregated_df: Aggregated pod usage
            node_capacity_df: Node capacity by day

        Returns:
            Joined DataFrame
        """
        if node_capacity_df.empty:
            aggregated_df['node_capacity_cpu_core_hours'] = None
            aggregated_df['node_capacity_memory_gigabyte_hours'] = None
            aggregated_df['cluster_capacity_cpu_core_hours'] = None
            aggregated_df['cluster_capacity_memory_gigabyte_hours'] = None
            return aggregated_df

        # Join with node capacity
        return aggregated_df.merge(
            node_capacity_df,
            on=['usage_start', 'node'],
            how='left'
        )

    def _join_cost_category(
        self,
        aggregated_df: pd.DataFrame,
        cost_category_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Join with cost category namespace (LIKE matching).

        Args:
            aggregated_df: Aggregated DataFrame
            cost_category_df: Cost category DataFrame

        Returns:
            Joined DataFrame
        """
        # Implement LIKE matching with MAX aggregation (Trino SQL line 264)
        # If multiple patterns match, take MAX(cost_category_id) like Trino does

        def match_cost_category(namespace):
            matching_ids = []
            for _, row in cost_category_df.iterrows():
                pattern = row['namespace']
                # Simple pattern match (% wildcard)
                if pattern.endswith('%'):
                    if namespace.startswith(pattern[:-1]):
                        matching_ids.append(row['cost_category_id'])
                elif namespace == pattern:
                    matching_ids.append(row['cost_category_id'])

            # Return MAX of matching IDs (or None if no matches)
            # This matches Trino SQL line 264: max(cat_ns.cost_category_id)
            return max(matching_ids) if matching_ids else None

        aggregated_df['cost_category_id'] = aggregated_df['namespace'].apply(match_cost_category)

        return aggregated_df

    def _format_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format final output to match PostgreSQL schema.

        Args:
            df: Aggregated DataFrame

        Returns:
            Formatted DataFrame
        """
        # Convert merged_labels dict to JSON string
        df['pod_labels'] = df['merged_labels'].apply(labels_to_json_string)

        # Add fixed columns
        df['uuid'] = None  # PostgreSQL will generate
        df['report_period_id'] = self.report_period_id
        df['cluster_id'] = self.cluster_id
        df['cluster_alias'] = self.cluster_alias
        df['data_source'] = 'Pod'
        df['usage_end'] = df['usage_start']  # Same as usage_start for daily

        # Storage columns (NULL for pod data)
        df['persistentvolumeclaim'] = None
        df['persistentvolume'] = None
        df['storageclass'] = None
        df['volume_labels'] = None
        df['persistentvolumeclaim_capacity_gigabyte'] = None
        df['persistentvolumeclaim_capacity_gigabyte_months'] = None
        df['volume_request_storage_gigabyte_months'] = None
        df['persistentvolumeclaim_usage_gigabyte_months'] = None
        df['csi_volume_handle'] = None

        # Infrastructure cost (default JSON)
        df['infrastructure_usage_cost'] = '{"cpu": 0.000000000, "memory": 0.000000000, "storage": 0.000000000}'

        # Partition columns
        # Note: Trino SQL line 665 uses lpad(month, 2, '0') for zero-padding
        df['source'] = self.provider_uuid
        df['year'] = df['usage_start'].apply(lambda d: str(d.year))
        df['month'] = df['usage_start'].apply(lambda d: str(d.month).zfill(2))  # Zero-pad: '1' → '01'
        df['day'] = df['usage_start'].apply(lambda d: str(d.day))

        # Select columns in correct order
        output_columns = [
            'uuid', 'report_period_id', 'cluster_id', 'cluster_alias', 'data_source',
            'usage_start', 'usage_end', 'namespace', 'node', 'resource_id',
            'pod_labels',
            'pod_usage_cpu_core_hours', 'pod_request_cpu_core_hours',
            'pod_effective_usage_cpu_core_hours', 'pod_limit_cpu_core_hours',
            'pod_usage_memory_gigabyte_hours', 'pod_request_memory_gigabyte_hours',
            'pod_effective_usage_memory_gigabyte_hours', 'pod_limit_memory_gigabyte_hours',
            'node_capacity_cpu_cores', 'node_capacity_cpu_core_hours',
            'node_capacity_memory_gigabytes', 'node_capacity_memory_gigabyte_hours',
            'cluster_capacity_cpu_core_hours', 'cluster_capacity_memory_gigabyte_hours',
            'persistentvolumeclaim', 'persistentvolume', 'storageclass', 'volume_labels',
            'persistentvolumeclaim_capacity_gigabyte', 'persistentvolumeclaim_capacity_gigabyte_months',
            'volume_request_storage_gigabyte_months', 'persistentvolumeclaim_usage_gigabyte_months',
            'source_uuid', 'infrastructure_usage_cost', 'csi_volume_handle', 'cost_category_id',
            'source', 'year', 'month', 'day'
        ]

        return df[output_columns]


def calculate_node_capacity(pod_usage_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate node and cluster capacity (replicates CTEs in Trino SQL).

    Trino SQL Logic (lines 143-171):
    1. Inner query: MAX capacity per interval + node
    2. Outer query: SUM of max capacities per day + node
    3. Cluster capacity: SUM across all nodes per day

    IMPORTANT: This requires hourly interval data (openshift_pod_usage_line_items),
    NOT daily aggregated data (openshift_pod_usage_line_items_daily).

    The POC currently uses daily data, which is a simplification.
    For production, this should read from the hourly Parquet files.

    Args:
        pod_usage_df: Pod usage line items (ideally hourly)

    Returns:
        Tuple of (node_capacity_df, cluster_capacity_df)
    """
    logger = get_logger("capacity_calculator")

    with PerformanceTimer("Calculate node/cluster capacity", logger):
        # Parse usage_start
        df = pod_usage_df.copy()
        # Handle nise date format: "2025-11-01 00:00:00 +0000 UTC"
        df['interval_start_clean'] = df['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
        df['usage_start'] = pd.to_datetime(df['interval_start_clean']).dt.date
        df.drop('interval_start_clean', axis=1, inplace=True)

        # Step 1: Get max capacity per interval + node (Trino lines 149-160)
        # NOTE: If input is already daily aggregated, this step is a no-op
        interval_capacity = df.groupby(['interval_start', 'node']).agg({
            'node_capacity_cpu_core_seconds': 'max',
            'node_capacity_memory_byte_seconds': 'max'
        }).reset_index()

        # Step 2: Sum across intervals for each day + node (Trino lines 143-164)
        # Handle nise date format
        interval_capacity['interval_start_clean'] = interval_capacity['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
        interval_capacity['usage_start'] = pd.to_datetime(interval_capacity['interval_start_clean']).dt.date
        interval_capacity.drop('interval_start_clean', axis=1, inplace=True)
        node_capacity = interval_capacity.groupby(['usage_start', 'node']).agg({
            'node_capacity_cpu_core_seconds': 'sum',
            'node_capacity_memory_byte_seconds': 'sum'
        }).reset_index()

        logger.debug(
            "Node capacity calculation",
            intervals=len(interval_capacity),
            node_days=len(node_capacity)
        )

        # Convert to hours and GB
        node_capacity['node_capacity_cpu_core_hours'] = node_capacity['node_capacity_cpu_core_seconds'] / 3600.0
        node_capacity['node_capacity_memory_gigabyte_hours'] = (
            node_capacity['node_capacity_memory_byte_seconds'] / 3600.0 * pow(2, -30)
        )

        # Step 3: Calculate cluster capacity (Trino lines 165-171)
        # Sum across all nodes per day
        cluster_capacity = node_capacity.groupby('usage_start').agg({
            'node_capacity_cpu_core_seconds': 'sum',
            'node_capacity_memory_byte_seconds': 'sum'
        }).reset_index()

        cluster_capacity['cluster_capacity_cpu_core_hours'] = cluster_capacity['node_capacity_cpu_core_seconds'] / 3600.0
        cluster_capacity['cluster_capacity_memory_gigabyte_hours'] = (
            cluster_capacity['node_capacity_memory_byte_seconds'] / 3600.0 * pow(2, -30)
        )

        # Verify cluster capacity is > 0
        if (cluster_capacity['cluster_capacity_cpu_core_hours'] <= 0).any():
            logger.warning("Found days with zero or negative cluster CPU capacity")
        if (cluster_capacity['cluster_capacity_memory_gigabyte_hours'] <= 0).any():
            logger.warning("Found days with zero or negative cluster memory capacity")

        logger.debug(
            "Cluster capacity summary",
            days=len(cluster_capacity),
            total_cpu_hours=cluster_capacity['cluster_capacity_cpu_core_hours'].sum(),
            total_memory_gb_hours=cluster_capacity['cluster_capacity_memory_gigabyte_hours'].sum()
        )

        # Join cluster capacity back to node capacity (each node gets the same cluster total)
        node_capacity = node_capacity.merge(
            cluster_capacity[['usage_start', 'cluster_capacity_cpu_core_hours', 'cluster_capacity_memory_gigabyte_hours']],
            on='usage_start',
            how='left'
        )

        # Verify join was successful
        if node_capacity['cluster_capacity_cpu_core_hours'].isna().any():
            logger.error("Cluster capacity join failed - found NULL values")
        else:
            logger.debug("✓ Cluster capacity successfully joined to all nodes")

        logger.info(
            "Capacity calculation complete",
            node_capacity_rows=len(node_capacity),
            cluster_capacity_days=len(cluster_capacity)
        )

        return node_capacity, cluster_capacity

