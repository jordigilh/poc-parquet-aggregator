"""
Unallocated Capacity Aggregator.

Implements Trino SQL lines 491-581 from reporting_ocpusagelineitem_daily_summary.sql:
- Calculates unused node capacity (capacity - pod usage)
- Creates "Platform unallocated" namespace for master/infra nodes
- Creates "Worker unallocated" namespace for worker nodes
"""

import uuid as uuid_lib
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .utils import get_logger

# Namespaces to exclude from unallocated calculation (Trino SQL lines 541-544)
EXCLUDED_NAMESPACES = [
    "Platform unallocated",
    "Worker unallocated",
    "Network unattributed",
    "Storage unattributed",
]


class UnallocatedCapacityAggregator:
    """Calculate unallocated node capacity.

    Implements Trino SQL lines 491-581:
    - Joins with reporting_ocp_nodes to get node roles
    - Calculates: node_capacity - sum(pod_usage)
    - Creates Platform/Worker unallocated namespaces
    """

    def __init__(self, config: Dict, logger=None):
        """Initialize the aggregator.

        Args:
            config: Configuration dictionary
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or get_logger("aggregator_unallocated")

        # OCP configuration
        ocp_config = config.get("ocp", {})
        self.cluster_id = ocp_config.get("cluster_id", "")
        self.cluster_alias = ocp_config.get("cluster_alias", "")
        self.report_period_id = ocp_config.get("report_period_id", 0)
        self.provider_uuid = ocp_config.get("provider_uuid", "")

        self.logger.info("Initialized UnallocatedCapacityAggregator", cluster_id=self.cluster_id)

    def get_node_roles(self) -> pd.DataFrame:
        """Fetch node roles from reporting_ocp_nodes table.

        Returns:
            DataFrame with columns: node, resource_id, node_role
        """
        raw_roles = self._fetch_node_roles()
        return self._aggregate_node_roles(raw_roles)

    def _fetch_node_roles(self) -> pd.DataFrame:
        """Internal method to fetch node roles from database.

        This is typically mocked in tests. In production, it queries:
        SELECT node, resource_id, node_role FROM reporting_ocp_nodes
        """
        # This should be overridden or injected in production
        raise NotImplementedError("_fetch_node_roles must be provided via mock or database connection")

    def _aggregate_node_roles(self, node_roles_df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate node roles using MAX (Trino SQL lines 491-498).

        When a node has multiple roles, MAX is used to select one.
        Alphabetically: 'worker' > 'master' > 'infra'

        Args:
            node_roles_df: Raw node roles with potential duplicates

        Returns:
            DataFrame with one role per node (MAX aggregation)
        """
        if node_roles_df.empty:
            return pd.DataFrame(columns=["node", "resource_id", "node_role"])

        # Bug #12 fix: Convert node_role from Categorical to string before max()
        # Pandas cannot perform max() on non-ordered Categorical columns
        df = node_roles_df.copy()
        if df["node_role"].dtype.name == "category":
            df["node_role"] = df["node_role"].astype(str)

        # Group by node + resource_id and take MAX of node_role
        # This matches Trino: SELECT max(node_role) AS node_role
        aggregated = df.groupby(["node", "resource_id"], as_index=False).agg({"node_role": "max"})

        return aggregated

    def calculate_unallocated(self, daily_summary_df: pd.DataFrame, node_roles_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate unallocated capacity per node.

        Implements Trino SQL lines 499-581:
        - Filters out existing unallocated/unattributed rows
        - Groups by node and sums usage
        - Subtracts from capacity to get unallocated
        - Assigns Platform/Worker unallocated namespace based on node role

        Args:
            daily_summary_df: Already-aggregated pod data
            node_roles_df: Node roles from reporting_ocp_nodes

        Returns:
            DataFrame with unallocated capacity rows
        """
        # Handle empty inputs
        if daily_summary_df.empty:
            self.logger.info("Empty daily summary, returning empty result")
            return pd.DataFrame()

        if node_roles_df.empty:
            self.logger.info("Empty node roles, returning empty result")
            return pd.DataFrame()

        # Step 1: Filter input data (Trino SQL lines 541-546)
        filtered_df = self._filter_input_data(daily_summary_df)

        if filtered_df.empty:
            self.logger.info("No data after filtering, returning empty result")
            return pd.DataFrame()

        # Step 2: Group by node and calculate totals
        node_totals = self._calculate_node_totals(filtered_df)

        # Step 3: Join with node roles
        node_totals_with_roles = self._join_node_roles(node_totals, node_roles_df)

        if node_totals_with_roles.empty:
            self.logger.info("No nodes matched with roles, returning empty result")
            return pd.DataFrame()

        # Step 4: Calculate unallocated = capacity - usage
        unallocated = self._calculate_unallocated_values(node_totals_with_roles)

        # Step 5: Assign namespace based on role
        unallocated = self._assign_namespace(unallocated)

        # Step 6: Format output
        result = self._format_output(unallocated)

        self.logger.info(
            "Unallocated capacity calculated",
            nodes_processed=len(result),
            platform_unallocated=len(result[result["namespace"] == "Platform unallocated"]),
            worker_unallocated=len(result[result["namespace"] == "Worker unallocated"]),
        )

        return result

    def _filter_input_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter input to exclude already-unallocated rows and non-Pod data.

        Trino SQL lines 541-546:
        - Excludes Platform unallocated, Worker unallocated
        - Excludes Network unattributed, Storage unattributed
        - Only includes data_source = 'Pod'
        - Excludes rows with NULL node
        """
        filtered = df.copy()

        # Exclude special namespaces
        filtered = filtered[~filtered["namespace"].isin(EXCLUDED_NAMESPACES)]

        # Only Pod data source
        if "data_source" in filtered.columns:
            filtered = filtered[filtered["data_source"] == "Pod"]

        # Exclude NULL nodes
        filtered = filtered[filtered["node"].notna() & (filtered["node"] != "")]

        return filtered

    def _calculate_node_totals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group by node/usage_start and aggregate usage + capacity.

        Trino SQL lines 513-526:
        - MAX for capacity values
        - SUM for usage values
        """
        # Group by node, usage_start, source_uuid (Trino line 547)
        groupby_cols = ["node", "usage_start", "source_uuid"]

        # Aggregations matching Trino SQL
        agg_dict = {
            # Usage: SUM
            "pod_usage_cpu_core_hours": "sum",
            "pod_request_cpu_core_hours": "sum",
            "pod_effective_usage_cpu_core_hours": "sum",
            "pod_usage_memory_gigabyte_hours": "sum",
            "pod_request_memory_gigabyte_hours": "sum",
            "pod_effective_usage_memory_gigabyte_hours": "sum",
            # Capacity: MAX
            "node_capacity_cpu_cores": "max",
            "node_capacity_cpu_core_hours": "max",
            "node_capacity_memory_gigabytes": "max",
            "node_capacity_memory_gigabyte_hours": "max",
            "cluster_capacity_cpu_core_hours": "max",
            "cluster_capacity_memory_gigabyte_hours": "max",
            # Resource ID: MAX (for joining with roles)
            "resource_id": "max",
        }

        # Only include columns that exist
        agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}

        totals = df.groupby(groupby_cols, as_index=False).agg(agg_dict)

        return totals

    def _join_node_roles(self, node_totals: pd.DataFrame, node_roles_df: pd.DataFrame) -> pd.DataFrame:
        """Join node totals with node roles.

        Trino SQL lines 533-535:
        LEFT JOIN cte_node_role AS nodes
            ON lids.node = nodes.node
            AND lids.resource_id = nodes.resource_id
        """
        if node_roles_df.empty:
            return pd.DataFrame()

        # Aggregate node roles first (handles duplicates)
        roles = self._aggregate_node_roles(node_roles_df)

        # Join on node + resource_id
        merged = pd.merge(
            node_totals,
            roles,
            on=["node", "resource_id"],
            how="inner",  # Only nodes with known roles
        )

        return merged

    def _calculate_unallocated_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate unallocated = capacity - usage.

        Trino SQL lines 514-519:
        (max(node_capacity_cpu_core_hours) - sum(pod_usage_cpu_core_hours))
        """
        result = df.copy()

        # CPU calculations
        result["unallocated_pod_usage_cpu_core_hours"] = (
            result["node_capacity_cpu_core_hours"] - result["pod_usage_cpu_core_hours"]
        )
        result["unallocated_pod_request_cpu_core_hours"] = (
            result["node_capacity_cpu_core_hours"] - result["pod_request_cpu_core_hours"]
        )
        result["unallocated_pod_effective_usage_cpu_core_hours"] = (
            result["node_capacity_cpu_core_hours"] - result["pod_effective_usage_cpu_core_hours"]
        )

        # Memory calculations
        result["unallocated_pod_usage_memory_gigabyte_hours"] = (
            result["node_capacity_memory_gigabyte_hours"] - result["pod_usage_memory_gigabyte_hours"]
        )
        result["unallocated_pod_request_memory_gigabyte_hours"] = (
            result["node_capacity_memory_gigabyte_hours"] - result["pod_request_memory_gigabyte_hours"]
        )
        result["unallocated_pod_effective_usage_memory_gigabyte_hours"] = (
            result["node_capacity_memory_gigabyte_hours"] - result["pod_effective_usage_memory_gigabyte_hours"]
        )

        return result

    def _assign_namespace(self, df: pd.DataFrame) -> pd.DataFrame:
        """Assign namespace based on node role.

        Trino SQL lines 507-511:
        CASE max(nodes.node_role)
            WHEN 'master' THEN 'Platform unallocated'
            WHEN 'infra' THEN 'Platform unallocated'
            WHEN 'worker' THEN 'Worker unallocated'
        END as namespace
        """
        result = df.copy()

        def get_namespace(role):
            if role in ["master", "infra"]:
                return "Platform unallocated"
            elif role == "worker":
                return "Worker unallocated"
            else:
                # Unknown roles default to Worker unallocated
                return "Worker unallocated"

        result["namespace"] = result["node_role"].apply(get_namespace)

        return result

    def _format_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format output to match PostgreSQL schema.

        Returns DataFrame ready for INSERT into reporting_ocpusagelineitem_daily_summary.
        """
        result = pd.DataFrame(index=df.index)

        # Metadata columns
        result["report_period_id"] = self.report_period_id
        result["cluster_id"] = self.cluster_id
        result["cluster_alias"] = self.cluster_alias
        result["data_source"] = "Pod"  # Trino SQL line 526
        result["source_uuid"] = df["source_uuid"].values

        # Time columns
        result["usage_start"] = df["usage_start"]
        result["usage_end"] = df["usage_start"]  # Same as usage_start

        # Identity columns
        result["namespace"] = df["namespace"]
        result["node"] = df["node"]
        result["resource_id"] = df["resource_id"]

        # Unallocated values (renamed from "unallocated_*" to standard column names)
        result["pod_usage_cpu_core_hours"] = df["unallocated_pod_usage_cpu_core_hours"]
        result["pod_request_cpu_core_hours"] = df["unallocated_pod_request_cpu_core_hours"]
        result["pod_effective_usage_cpu_core_hours"] = df["unallocated_pod_effective_usage_cpu_core_hours"]
        result["pod_usage_memory_gigabyte_hours"] = df["unallocated_pod_usage_memory_gigabyte_hours"]
        result["pod_request_memory_gigabyte_hours"] = df["unallocated_pod_request_memory_gigabyte_hours"]
        result["pod_effective_usage_memory_gigabyte_hours"] = df[
            "unallocated_pod_effective_usage_memory_gigabyte_hours"
        ]

        # Capacity columns (unchanged)
        result["node_capacity_cpu_cores"] = df["node_capacity_cpu_cores"]
        result["node_capacity_cpu_core_hours"] = df["node_capacity_cpu_core_hours"]
        result["node_capacity_memory_gigabytes"] = df["node_capacity_memory_gigabytes"]
        result["node_capacity_memory_gigabyte_hours"] = df["node_capacity_memory_gigabyte_hours"]
        result["cluster_capacity_cpu_core_hours"] = df["cluster_capacity_cpu_core_hours"]
        result["cluster_capacity_memory_gigabyte_hours"] = df["cluster_capacity_memory_gigabyte_hours"]

        # Labels (empty for unallocated capacity - no pods/volumes)
        result["pod_labels"] = "{}"
        result["volume_labels"] = None
        result["all_labels"] = "{}"  # Trino SQL lines 651-654: empty for unallocated

        # Generate UUIDs - Bug #13 fix: Koku DB requires uuid (NOT NULL, no default)
        result["uuid"] = [str(uuid_lib.uuid4()) for _ in range(len(result))]

        return result
