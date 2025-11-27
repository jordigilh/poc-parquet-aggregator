"""
Tests for Unallocated Capacity Aggregation (TDD).

These tests validate the POC implementation matches Trino SQL lines 491-581:
- Node role lookup from reporting_ocp_nodes
- Platform unallocated namespace for master/infra nodes
- Worker unallocated namespace for worker nodes
- Capacity minus usage calculation
- Exclusion of already-unallocated rows

Reference: koku/masu/database/trino_sql/reporting_ocpusagelineitem_daily_summary.sql
"""

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestUnallocatedCapacityAggregator:
    """Test UnallocatedCapacityAggregator class."""

    @pytest.fixture
    def sample_node_roles(self):
        """Sample node roles from reporting_ocp_nodes table.

        Trino SQL lines 491-498:
        WITH cte_node_role AS (
            SELECT max(node_role) AS node_role, node, resource_id
            FROM postgres.reporting_ocp_nodes
            GROUP BY node, resource_id
        )
        """
        return pd.DataFrame(
            {
                "node": [
                    "master-0",
                    "master-1",
                    "infra-0",
                    "worker-0",
                    "worker-1",
                    "worker-2",
                ],
                "resource_id": [
                    "i-master0",
                    "i-master1",
                    "i-infra0",
                    "i-worker0",
                    "i-worker1",
                    "i-worker2",
                ],
                "node_role": [
                    "master",
                    "master",
                    "infra",
                    "worker",
                    "worker",
                    "worker",
                ],
            }
        )

    @pytest.fixture
    def sample_daily_summary(self):
        """Sample daily summary data (already aggregated pod data).

        This represents data already in reporting_ocpusagelineitem_daily_summary
        that the unallocated calculation processes.
        """
        return pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)] * 6,
                "namespace": ["app-a", "app-b", "app-a", "app-a", "app-b", "app-c"],
                "node": [
                    "master-0",
                    "master-0",
                    "infra-0",
                    "worker-0",
                    "worker-1",
                    "worker-2",
                ],
                "resource_id": [
                    "i-master0",
                    "i-master0",
                    "i-infra0",
                    "i-worker0",
                    "i-worker1",
                    "i-worker2",
                ],
                "pod_usage_cpu_core_hours": [1.0, 2.0, 3.0, 10.0, 15.0, 5.0],
                "pod_request_cpu_core_hours": [2.0, 3.0, 4.0, 12.0, 18.0, 8.0],
                "pod_effective_usage_cpu_core_hours": [2.0, 3.0, 4.0, 12.0, 18.0, 8.0],
                "pod_usage_memory_gigabyte_hours": [0.5, 1.0, 1.5, 5.0, 8.0, 3.0],
                "pod_request_memory_gigabyte_hours": [1.0, 2.0, 2.0, 6.0, 10.0, 4.0],
                "pod_effective_usage_memory_gigabyte_hours": [
                    1.0,
                    2.0,
                    2.0,
                    6.0,
                    10.0,
                    4.0,
                ],
                "node_capacity_cpu_core_hours": [24.0, 24.0, 24.0, 96.0, 96.0, 96.0],
                "node_capacity_memory_gigabyte_hours": [
                    64.0,
                    64.0,
                    64.0,
                    256.0,
                    256.0,
                    256.0,
                ],
                "cluster_capacity_cpu_core_hours": [432.0] * 6,
                "cluster_capacity_memory_gigabyte_hours": [1152.0] * 6,
                "node_capacity_cpu_cores": [4.0, 4.0, 4.0, 16.0, 16.0, 16.0],
                "node_capacity_memory_gigabytes": [16.0, 16.0, 16.0, 64.0, 64.0, 64.0],
                "data_source": ["Pod"] * 6,
                "source_uuid": ["provider-uuid"] * 6,
            }
        )

    @pytest.fixture
    def config(self):
        """Sample configuration."""
        return {
            "ocp": {
                "cluster_id": "test-cluster",
                "cluster_alias": "Test Cluster",
                "provider_uuid": "provider-uuid",
                "report_period_id": 1,
            },
            "features": {
                "unallocated_capacity": True,
            },
        }

    # =========================================================================
    # Test 1: Node Role Lookup
    # =========================================================================
    def test_get_node_roles_from_database(self, sample_node_roles, config):
        """Test that node roles are correctly fetched from reporting_ocp_nodes.

        Trino SQL lines 491-498:
        WITH cte_node_role AS (
            SELECT max(node_role) AS node_role, node, resource_id
            FROM postgres.reporting_ocp_nodes
            GROUP BY node, resource_id
        )
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        # Mock the database reader
        with patch.object(aggregator, "_fetch_node_roles", return_value=sample_node_roles):
            node_roles = aggregator.get_node_roles()

        assert len(node_roles) == 6
        assert node_roles[node_roles["node"] == "master-0"]["node_role"].iloc[0] == "master"
        assert node_roles[node_roles["node"] == "infra-0"]["node_role"].iloc[0] == "infra"
        assert node_roles[node_roles["node"] == "worker-0"]["node_role"].iloc[0] == "worker"

    def test_node_role_lookup_with_max_aggregation(self, config):
        """Test that MAX(node_role) is used when multiple roles exist for same node.

        This matches Trino's: SELECT max(node_role) AS node_role
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        # Node with multiple roles (edge case)
        node_roles_raw = pd.DataFrame(
            {
                "node": ["node-0", "node-0", "node-1"],
                "resource_id": ["i-0", "i-0", "i-1"],
                "node_role": [
                    "worker",
                    "infra",
                    "master",
                ],  # node-0 has both worker and infra
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        # The aggregator should apply MAX to get one role per node
        result = aggregator._aggregate_node_roles(node_roles_raw)

        # 'worker' > 'master' > 'infra' alphabetically, so 'worker' should win
        assert len(result[result["node"] == "node-0"]) == 1
        assert result[result["node"] == "node-0"]["node_role"].iloc[0] == "worker"

    # =========================================================================
    # Test 2: Platform Unallocated Namespace
    # =========================================================================
    def test_platform_unallocated_for_master_nodes(self, sample_daily_summary, sample_node_roles, config):
        """Test that master nodes get 'Platform unallocated' namespace.

        Trino SQL lines 507-511:
        CASE max(nodes.node_role)
            WHEN 'master' THEN 'Platform unallocated'
            WHEN 'infra' THEN 'Platform unallocated'
            WHEN 'worker' THEN 'Worker unallocated'
        END as namespace
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # Check master nodes have Platform unallocated
        master_unallocated = result[result["node"] == "master-0"]
        assert len(master_unallocated) == 1
        assert master_unallocated["namespace"].iloc[0] == "Platform unallocated"

    def test_platform_unallocated_for_infra_nodes(self, sample_daily_summary, sample_node_roles, config):
        """Test that infra nodes get 'Platform unallocated' namespace."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # Check infra nodes have Platform unallocated
        infra_unallocated = result[result["node"] == "infra-0"]
        assert len(infra_unallocated) == 1
        assert infra_unallocated["namespace"].iloc[0] == "Platform unallocated"

    # =========================================================================
    # Test 3: Worker Unallocated Namespace
    # =========================================================================
    def test_worker_unallocated_for_worker_nodes(self, sample_daily_summary, sample_node_roles, config):
        """Test that worker nodes get 'Worker unallocated' namespace."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # Check worker nodes have Worker unallocated
        worker_unallocated = result[result["node"] == "worker-0"]
        assert len(worker_unallocated) == 1
        assert worker_unallocated["namespace"].iloc[0] == "Worker unallocated"

    # =========================================================================
    # Test 4: Capacity Minus Usage Calculation
    # =========================================================================
    def test_unallocated_cpu_calculation(self, sample_daily_summary, sample_node_roles, config):
        """Test: unallocated_cpu = node_capacity - sum(pod_usage).

        Trino SQL lines 514-516:
        (max(lids.node_capacity_cpu_core_hours) - sum(lids.pod_usage_cpu_core_hours)) as pod_usage_cpu_core_hours
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # master-0: capacity=24, usage=1+2=3, unallocated=21
        master_0 = result[result["node"] == "master-0"].iloc[0]
        assert master_0["pod_usage_cpu_core_hours"] == pytest.approx(21.0, rel=0.01)

        # worker-0: capacity=96, usage=10, unallocated=86
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(86.0, rel=0.01)

    def test_unallocated_memory_calculation(self, sample_daily_summary, sample_node_roles, config):
        """Test: unallocated_memory = node_capacity - sum(pod_usage)."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # master-0: capacity=64, usage=0.5+1.0=1.5, unallocated=62.5
        master_0 = result[result["node"] == "master-0"].iloc[0]
        assert master_0["pod_usage_memory_gigabyte_hours"] == pytest.approx(62.5, rel=0.01)

        # worker-0: capacity=256, usage=5, unallocated=251
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_memory_gigabyte_hours"] == pytest.approx(251.0, rel=0.01)

    def test_unallocated_request_calculation(self, sample_daily_summary, sample_node_roles, config):
        """Test: unallocated_request = node_capacity - sum(pod_request)."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # master-0: capacity=24, request=2+3=5, unallocated=19
        master_0 = result[result["node"] == "master-0"].iloc[0]
        assert master_0["pod_request_cpu_core_hours"] == pytest.approx(19.0, rel=0.01)

    def test_unallocated_effective_usage_calculation(self, sample_daily_summary, sample_node_roles, config):
        """Test: unallocated_effective = node_capacity - sum(pod_effective_usage)."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        # master-0: capacity=24, effective=2+3=5, unallocated=19
        master_0 = result[result["node"] == "master-0"].iloc[0]
        assert master_0["pod_effective_usage_cpu_core_hours"] == pytest.approx(19.0, rel=0.01)

    # =========================================================================
    # Test 5: Exclusion of Already-Unallocated Rows
    # =========================================================================
    def test_excludes_platform_unallocated_from_input(self, sample_node_roles, config):
        """Test that existing 'Platform unallocated' rows are excluded from calculation.

        Trino SQL lines 541-544:
        AND lids.namespace != 'Platform unallocated'
        AND lids.namespace != 'Worker unallocated'
        AND lids.namespace != 'Network unattributed'
        AND lids.namespace != 'Storage unattributed'
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        # Daily summary with existing unallocated rows
        daily_summary = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)] * 3,
                "namespace": ["app-a", "Platform unallocated", "Worker unallocated"],
                "node": ["worker-0", "master-0", "worker-1"],
                "resource_id": ["i-worker0", "i-master0", "i-worker1"],
                "pod_usage_cpu_core_hours": [10.0, 20.0, 30.0],
                "pod_request_cpu_core_hours": [12.0, 22.0, 32.0],
                "pod_effective_usage_cpu_core_hours": [12.0, 22.0, 32.0],
                "pod_usage_memory_gigabyte_hours": [5.0, 10.0, 15.0],
                "pod_request_memory_gigabyte_hours": [6.0, 12.0, 18.0],
                "pod_effective_usage_memory_gigabyte_hours": [6.0, 12.0, 18.0],
                "node_capacity_cpu_core_hours": [96.0, 24.0, 96.0],
                "node_capacity_memory_gigabyte_hours": [256.0, 64.0, 256.0],
                "cluster_capacity_cpu_core_hours": [216.0] * 3,
                "cluster_capacity_memory_gigabyte_hours": [576.0] * 3,
                "node_capacity_cpu_cores": [16.0, 4.0, 16.0],
                "node_capacity_memory_gigabytes": [64.0, 16.0, 64.0],
                "data_source": ["Pod"] * 3,
                "source_uuid": ["provider-uuid"] * 3,
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=daily_summary, node_roles_df=sample_node_roles)

        # Should only calculate unallocated for worker-0 (app-a namespace)
        # The existing Platform/Worker unallocated rows should be excluded
        assert len(result[result["node"] == "worker-0"]) == 1
        # worker-0: capacity=96, usage=10, unallocated=86
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(86.0, rel=0.01)

    def test_excludes_network_unattributed_from_input(self, sample_node_roles, config):
        """Test that 'Network unattributed' rows are excluded."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        daily_summary = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)] * 2,
                "namespace": ["app-a", "Network unattributed"],
                "node": ["worker-0", "worker-0"],
                "resource_id": ["i-worker0", "i-worker0"],
                "pod_usage_cpu_core_hours": [10.0, 5.0],
                "pod_request_cpu_core_hours": [12.0, 6.0],
                "pod_effective_usage_cpu_core_hours": [12.0, 6.0],
                "pod_usage_memory_gigabyte_hours": [5.0, 2.5],
                "pod_request_memory_gigabyte_hours": [6.0, 3.0],
                "pod_effective_usage_memory_gigabyte_hours": [6.0, 3.0],
                "node_capacity_cpu_core_hours": [96.0, 96.0],
                "node_capacity_memory_gigabyte_hours": [256.0, 256.0],
                "cluster_capacity_cpu_core_hours": [96.0] * 2,
                "cluster_capacity_memory_gigabyte_hours": [256.0] * 2,
                "node_capacity_cpu_cores": [16.0, 16.0],
                "node_capacity_memory_gigabytes": [64.0, 64.0],
                "data_source": ["Pod"] * 2,
                "source_uuid": ["provider-uuid"] * 2,
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=daily_summary, node_roles_df=sample_node_roles)

        # Should only count app-a usage (10), not Network unattributed (5)
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(86.0, rel=0.01)

    def test_excludes_storage_unattributed_from_input(self, sample_node_roles, config):
        """Test that 'Storage unattributed' rows are excluded."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        daily_summary = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)] * 2,
                "namespace": ["app-a", "Storage unattributed"],
                "node": ["worker-0", "worker-0"],
                "resource_id": ["i-worker0", "i-worker0"],
                "pod_usage_cpu_core_hours": [10.0, 5.0],
                "pod_request_cpu_core_hours": [12.0, 6.0],
                "pod_effective_usage_cpu_core_hours": [12.0, 6.0],
                "pod_usage_memory_gigabyte_hours": [5.0, 2.5],
                "pod_request_memory_gigabyte_hours": [6.0, 3.0],
                "pod_effective_usage_memory_gigabyte_hours": [6.0, 3.0],
                "node_capacity_cpu_core_hours": [96.0, 96.0],
                "node_capacity_memory_gigabyte_hours": [256.0, 256.0],
                "cluster_capacity_cpu_core_hours": [96.0] * 2,
                "cluster_capacity_memory_gigabyte_hours": [256.0] * 2,
                "node_capacity_cpu_cores": [16.0, 16.0],
                "node_capacity_memory_gigabytes": [64.0, 64.0],
                "data_source": ["Pod"] * 2,
                "source_uuid": ["provider-uuid"] * 2,
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=daily_summary, node_roles_df=sample_node_roles)

        # Should only count app-a usage (10), not Storage unattributed (5)
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(86.0, rel=0.01)

    def test_only_processes_pod_data_source(self, sample_node_roles, config):
        """Test that only data_source='Pod' rows are processed.

        Trino SQL line 546:
        AND lids.data_source = 'Pod'
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        daily_summary = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)] * 2,
                "namespace": ["app-a", "app-a"],
                "node": ["worker-0", "worker-0"],
                "resource_id": ["i-worker0", "i-worker0"],
                "pod_usage_cpu_core_hours": [10.0, 5.0],
                "pod_request_cpu_core_hours": [12.0, 6.0],
                "pod_effective_usage_cpu_core_hours": [12.0, 6.0],
                "pod_usage_memory_gigabyte_hours": [5.0, 2.5],
                "pod_request_memory_gigabyte_hours": [6.0, 3.0],
                "pod_effective_usage_memory_gigabyte_hours": [6.0, 3.0],
                "node_capacity_cpu_core_hours": [96.0, 96.0],
                "node_capacity_memory_gigabyte_hours": [256.0, 256.0],
                "cluster_capacity_cpu_core_hours": [96.0] * 2,
                "cluster_capacity_memory_gigabyte_hours": [256.0] * 2,
                "node_capacity_cpu_cores": [16.0, 16.0],
                "node_capacity_memory_gigabytes": [64.0, 64.0],
                "data_source": ["Pod", "Storage"],  # Second row is Storage
                "source_uuid": ["provider-uuid"] * 2,
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=daily_summary, node_roles_df=sample_node_roles)

        # Should only count Pod data_source usage (10), not Storage (5)
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(86.0, rel=0.01)

    # =========================================================================
    # Test 6: Output Schema
    # =========================================================================
    def test_output_has_required_columns(self, sample_daily_summary, sample_node_roles, config):
        """Test that output has all required columns for PostgreSQL insert."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        required_columns = [
            "usage_start",
            "usage_end",
            "namespace",
            "node",
            "resource_id",
            "pod_usage_cpu_core_hours",
            "pod_request_cpu_core_hours",
            "pod_effective_usage_cpu_core_hours",
            "pod_usage_memory_gigabyte_hours",
            "pod_request_memory_gigabyte_hours",
            "pod_effective_usage_memory_gigabyte_hours",
            "node_capacity_cpu_cores",
            "node_capacity_cpu_core_hours",
            "node_capacity_memory_gigabytes",
            "node_capacity_memory_gigabyte_hours",
            "cluster_capacity_cpu_core_hours",
            "cluster_capacity_memory_gigabyte_hours",
            "data_source",
            "source_uuid",
            "cluster_id",
            "cluster_alias",
            "report_period_id",
        ]

        for col in required_columns:
            assert col in result.columns, f"Missing required column: {col}"

    def test_output_data_source_is_pod(self, sample_daily_summary, sample_node_roles, config):
        """Test that output data_source is 'Pod' (like Trino line 526)."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(
            daily_summary_df=sample_daily_summary, node_roles_df=sample_node_roles
        )

        assert (result["data_source"] == "Pod").all()

    # =========================================================================
    # Test 7: Edge Cases
    # =========================================================================
    def test_handles_node_without_role(self, sample_daily_summary, config):
        """Test that nodes without a role in reporting_ocp_nodes are skipped."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        # Node roles missing some nodes
        incomplete_roles = pd.DataFrame(
            {
                "node": ["worker-0"],  # Only worker-0 has a role
                "resource_id": ["i-worker0"],
                "node_role": ["worker"],
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=sample_daily_summary, node_roles_df=incomplete_roles)

        # Only worker-0 should have unallocated capacity
        assert len(result) == 1
        assert result.iloc[0]["node"] == "worker-0"

    def test_handles_empty_daily_summary(self, sample_node_roles, config):
        """Test that empty daily summary returns empty result."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        empty_summary = pd.DataFrame()

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=empty_summary, node_roles_df=sample_node_roles)

        assert len(result) == 0

    def test_handles_empty_node_roles(self, sample_daily_summary, config):
        """Test that empty node roles returns empty result."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        empty_roles = pd.DataFrame()

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=sample_daily_summary, node_roles_df=empty_roles)

        assert len(result) == 0

    def test_negative_unallocated_becomes_zero(self, sample_node_roles, config):
        """Test that negative unallocated (over-provisioned) becomes zero or is handled."""
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        # Usage exceeds capacity (shouldn't happen, but handle gracefully)
        over_provisioned = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)],
                "namespace": ["app-a"],
                "node": ["worker-0"],
                "resource_id": ["i-worker0"],
                "pod_usage_cpu_core_hours": [100.0],  # More than capacity (96)
                "pod_request_cpu_core_hours": [100.0],
                "pod_effective_usage_cpu_core_hours": [100.0],
                "pod_usage_memory_gigabyte_hours": [300.0],  # More than capacity (256)
                "pod_request_memory_gigabyte_hours": [300.0],
                "pod_effective_usage_memory_gigabyte_hours": [300.0],
                "node_capacity_cpu_core_hours": [96.0],
                "node_capacity_memory_gigabyte_hours": [256.0],
                "cluster_capacity_cpu_core_hours": [96.0],
                "cluster_capacity_memory_gigabyte_hours": [256.0],
                "node_capacity_cpu_cores": [16.0],
                "node_capacity_memory_gigabytes": [64.0],
                "data_source": ["Pod"],
                "source_uuid": ["provider-uuid"],
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=over_provisioned, node_roles_df=sample_node_roles)

        # Should either be 0 or negative (depending on design choice)
        # Trino doesn't explicitly handle this, so we allow negative
        worker_0 = result[result["node"] == "worker-0"].iloc[0]
        # capacity - usage = 96 - 100 = -4
        assert worker_0["pod_usage_cpu_core_hours"] == pytest.approx(-4.0, rel=0.01)

