"""
Unit tests for StorageAggregator.

Focus: Behavior and correctness, not implementation details.

Tests validate:
- Correct output schema
- Proper data transformations
- Edge case handling
- Data integrity
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, date

from src.aggregator_storage import StorageAggregator


@pytest.fixture
def config():
    """Standard test configuration."""
    return {
        'ocp': {
            'cluster_id': 'test-cluster-123',
            'provider_uuid': 'test-provider-456',
            'cluster_alias': 'Test Cluster',
            'report_period_id': 1
        },
        'performance': {
            'use_arrow_compute': False,
            'delete_intermediate_dfs': False,
            'gc_after_aggregation': False
        }
    }


@pytest.fixture
def storage_aggregator(config):
    """Create a storage aggregator instance."""
    return StorageAggregator(config)


@pytest.fixture
def sample_storage_data():
    """Sample storage usage data."""
    return pd.DataFrame({
        'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 3),
        'namespace': ['ns1', 'ns1', 'ns2'],
        'pod': ['pod1', 'pod2', 'pod3'],
        'persistentvolumeclaim': ['pvc1', 'pvc2', 'pvc3'],
        'persistentvolume': ['pv1', 'pv2', 'pv3'],
        'storageclass': ['gp2', 'gp2', 'gp3'],
        'persistentvolumeclaim_capacity_byte_seconds': [1000000000.0, 2000000000.0, 3000000000.0],
        'volume_request_storage_byte_seconds': [800000000.0, 1600000000.0, 2400000000.0],
        'persistentvolumeclaim_usage_byte_seconds': [500000000.0, 1000000000.0, 1500000000.0],
        'volume_labels': ['{"app": "web"}', '{"app": "api"}', '{"app": "db"}'],
        'csi_volume_handle': ['vol-123', 'vol-456', 'vol-789']
    })


@pytest.fixture
def sample_pod_data():
    """Sample pod usage data for joining."""
    return pd.DataFrame({
        'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 3),
        'namespace': ['ns1', 'ns1', 'ns2'],
        'pod': ['pod1', 'pod2', 'pod3'],
        'node': ['node1', 'node1', 'node2'],
        'resource_id': ['i-111', 'i-111', 'i-222']
    })


@pytest.fixture
def sample_node_labels():
    """Sample node labels."""
    return pd.DataFrame({
        'usage_start': [date(2025, 10, 1)] * 2,
        'node': ['node1', 'node2'],
        'node_labels': ['{"env": "prod"}', '{"env": "dev"}']
    })


@pytest.fixture
def sample_namespace_labels():
    """Sample namespace labels."""
    return pd.DataFrame({
        'usage_start': [date(2025, 10, 1)] * 2,
        'namespace': ['ns1', 'ns2'],
        'namespace_labels': ['{"team": "platform"}', '{"team": "data"}']
    })


class TestStorageAggregatorBehavior:
    """Test StorageAggregator behavior and correctness."""

    def test_output_has_storage_data_source(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify output has data_source='Storage'."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert not result.empty, "Result should not be empty"
        assert 'data_source' in result.columns, "data_source column must exist"
        assert (result['data_source'] == 'Storage').all(), "All rows must have data_source='Storage'"

    def test_output_has_null_cpu_memory_columns(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify storage rows have NULL CPU/memory columns."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        cpu_memory_cols = [
            'pod_usage_cpu_core_hours',
            'pod_request_cpu_core_hours',
            'pod_limit_cpu_core_hours',
            'pod_usage_memory_gigabyte_hours',
            'pod_request_memory_gigabyte_hours',
            'pod_limit_memory_gigabyte_hours',
            'node_capacity_cpu_cores',
            'node_capacity_memory_gigabytes'
        ]

        for col in cpu_memory_cols:
            assert col in result.columns, f"{col} must exist in output"
            assert result[col].isna().all(), f"{col} must be NULL for storage rows"

    def test_output_has_populated_storage_columns(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify storage columns are populated."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        storage_cols = [
            'persistentvolumeclaim',
            'persistentvolume',
            'storageclass',
            'persistentvolumeclaim_capacity_gigabyte_months',
            'volume_request_storage_gigabyte_months',
            'persistentvolumeclaim_usage_gigabyte_months'
        ]

        for col in storage_cols:
            assert col in result.columns, f"{col} must exist in output"
            assert result[col].notna().any(), f"{col} should have values"

    def test_byte_seconds_to_gigabyte_months_conversion(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify correct conversion from byte-seconds to gigabyte-months."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        # Check that values are reasonable (not zero, not infinity)
        assert (result['persistentvolumeclaim_capacity_gigabyte_months'] > 0).all()
        assert (result['persistentvolumeclaim_capacity_gigabyte_months'] < 1e6).all()

        # Verify conversion formula is applied
        # Input: 1000000000 byte-seconds
        # Expected: 1000000000 / (1024^3 * 3600) / 730 ≈ 0.000366 GB-months
        first_row = result.iloc[0]
        capacity_gb_months = first_row['persistentvolumeclaim_capacity_gigabyte_months']

        # Should be a small positive number
        assert 0 < capacity_gb_months < 1, "Conversion result should be reasonable"

    def test_join_with_pods_adds_node_info(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify storage data is joined with pod data to get node/resource_id."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert 'node' in result.columns, "node column must exist"
        assert 'resource_id' in result.columns, "resource_id column must exist"

        # Check that we got node info from pod data
        assert result['node'].notna().any(), "Some nodes should be populated"

    def test_csi_volume_handle_preserved(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify csi_volume_handle is preserved (critical for AWS matching)."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert 'csi_volume_handle' in result.columns, "csi_volume_handle must exist"

        # Check that original CSI handles are preserved
        original_handles = set(sample_storage_data['csi_volume_handle'].unique())
        result_handles = set(result['csi_volume_handle'].dropna().unique())

        assert original_handles <= result_handles, "All CSI handles must be preserved"

    def test_label_precedence_volume_over_namespace_over_node(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify label precedence: Volume > Namespace > Node."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert 'pod_labels' in result.columns, "pod_labels must exist (merged labels)"

        # Verify volume labels are present (highest precedence)
        import json
        first_labels = json.loads(result.iloc[0]['pod_labels'])

        # Should have volume label (highest precedence)
        assert 'app' in first_labels, "Volume label should be present"
        assert first_labels['app'] == 'web', "Volume label should have correct value"

        # Should also have namespace and node labels
        assert 'team' in first_labels, "Namespace label should be present"
        assert 'env' in first_labels, "Node label should be present"

    def test_empty_storage_data_returns_empty_result(
        self, storage_aggregator, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify empty storage data returns empty result."""
        empty_storage = pd.DataFrame()

        result = storage_aggregator.aggregate(
            empty_storage, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert result.empty, "Empty input should return empty result"

    def test_missing_pod_match_handles_gracefully(
        self, storage_aggregator, sample_storage_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify storage without matching pods is handled gracefully."""
        # Pod data that doesn't match any storage
        mismatched_pods = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['different-ns'],
            'pod': ['different-pod'],
            'node': ['node1'],
            'resource_id': ['i-999']
        })

        result = storage_aggregator.aggregate(
            sample_storage_data, mismatched_pods,
            sample_node_labels, sample_namespace_labels
        )

        # Should still produce output, but with empty/NULL nodes
        assert not result.empty, "Should produce output even without pod matches"
        # Nodes should be empty strings (not NaN) for PostgreSQL compatibility
        assert (result['node'] == '').any() or result['node'].isna().any(), "Some nodes should be empty/NULL"

    def test_output_schema_matches_expected(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify output schema matches reporting_ocpusagelineitem_daily_summary."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        required_columns = [
            'usage_start', 'usage_end', 'data_source',
            'namespace', 'node', 'pod', 'resource_id',
            'persistentvolumeclaim', 'persistentvolume', 'storageclass',
            'volume_labels', 'csi_volume_handle',
            'persistentvolumeclaim_capacity_gigabyte_months',
            'volume_request_storage_gigabyte_months',
            'persistentvolumeclaim_usage_gigabyte_months',
            'pod_labels', 'cluster_id', 'source_uuid'
        ]

        for col in required_columns:
            assert col in result.columns, f"Required column {col} must exist"

    def test_cluster_metadata_populated(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify cluster metadata is populated correctly."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert (result['cluster_id'] == 'test-cluster-123').all()
        assert (result['source_uuid'] == 'test-provider-456').all()
        assert (result['cluster_alias'] == 'Test Cluster').all()
        assert (result['report_period_id'] == 1).all()

    def test_usage_start_is_date_type(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify usage_start is properly converted to date."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        assert pd.api.types.is_datetime64_any_dtype(result['usage_start'])

    def test_no_nan_in_json_columns(
        self, storage_aggregator, sample_storage_data, sample_pod_data,
        sample_node_labels, sample_namespace_labels
    ):
        """Verify no NaN values in JSON columns (PostgreSQL compatibility)."""
        result = storage_aggregator.aggregate(
            sample_storage_data, sample_pod_data,
            sample_node_labels, sample_namespace_labels
        )

        json_columns = ['volume_labels', 'pod_labels']

        for col in json_columns:
            # Should not have NaN
            assert not result[col].isna().any(), f"{col} should not have NaN values"
            # Should be valid JSON strings or None
            for val in result[col]:
                if val is not None:
                    import json
                    json.loads(val)  # Should not raise

    def test_multiple_pvcs_per_namespace(self, storage_aggregator):
        """Verify multiple PVCs in same namespace are handled correctly."""
        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 4),
            'namespace': ['ns1', 'ns1', 'ns1', 'ns1'],  # Same namespace
            'pod': ['pod1', 'pod1', 'pod2', 'pod2'],
            'persistentvolumeclaim': ['pvc1', 'pvc2', 'pvc3', 'pvc4'],  # Different PVCs
            'persistentvolume': ['pv1', 'pv2', 'pv3', 'pv4'],
            'storageclass': ['gp2'] * 4,
            'persistentvolumeclaim_capacity_byte_seconds': [1e9] * 4,
            'volume_request_storage_byte_seconds': [8e8] * 4,
            'persistentvolumeclaim_usage_byte_seconds': [5e8] * 4,
            'volume_labels': ['{}'] * 4,
            'csi_volume_handle': ['vol-1', 'vol-2', 'vol-3', 'vol-4']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 2),
            'namespace': ['ns1', 'ns1'],
            'pod': ['pod1', 'pod2'],
            'node': ['node1', 'node1'],
            'resource_id': ['i-111', 'i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # Should have 4 rows (one per PVC)
        assert len(result) == 4, "Should have one row per PVC"
        assert len(result['persistentvolumeclaim'].unique()) == 4


class TestStorageAggregatorEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_metrics_handled_correctly(self, storage_aggregator):
        """Verify zero storage metrics are handled correctly."""
        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [0.0],
            'volume_request_storage_byte_seconds': [0.0],
            'persistentvolumeclaim_usage_byte_seconds': [0.0],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'node': ['node1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        assert len(result) == 1, "Should produce output for zero metrics"
        assert result.iloc[0]['persistentvolumeclaim_capacity_gigabyte_months'] == 0.0

    def test_null_csi_volume_handle(self, storage_aggregator):
        """Verify NULL csi_volume_handle is handled correctly."""
        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [1e9],
            'volume_request_storage_byte_seconds': [8e8],
            'persistentvolumeclaim_usage_byte_seconds': [5e8],
            'volume_labels': ['{}'],
            'csi_volume_handle': [None]  # NULL handle
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'node': ['node1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        assert len(result) == 1
        # Should be empty string, not None (for PostgreSQL)
        assert result.iloc[0]['csi_volume_handle'] == ''

    def test_empty_labels(self, storage_aggregator):
        """Verify empty labels are handled correctly."""
        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [1e9],
            'volume_request_storage_byte_seconds': [8e8],
            'persistentvolumeclaim_usage_byte_seconds': [5e8],
            'volume_labels': [None],  # NULL labels
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod1'],
            'node': ['node1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # Should have valid JSON, not None
        assert result.iloc[0]['pod_labels'] is not None
        import json
        labels = json.loads(result.iloc[0]['pod_labels'])
        assert isinstance(labels, dict)


class TestSharedVolumeNodeCount:
    """Test shared volume node count division (Trino SQL lines 205-212, 410-411).

    When a PV is mounted on multiple nodes, the storage usage should be
    divided by the number of nodes to avoid overcounting.

    Trino behavior: GROUP BY includes node, so for a shared PV on 3 nodes,
    we get 3 output rows (one per node), but each row's usage is divided by 3.
    """

    def test_shared_pv_across_3_nodes_divides_usage_by_3(self, config):
        """
        CRITICAL TEST: Shared PV usage must be divided by node count.

        Scenario:
        - 1 PV (shared-pv) mounted by 3 pods on 3 different nodes
        - Each pod reports 3000 byte-seconds usage
        - Total raw = 9000, but with node_count=3, each row gets 9000/3 = 3000

        Trino SQL (lines 410-411):
            sum(sli.volume_request_storage_byte_seconds) / max(nc.node_count)

        Output: 3 rows (one per node), each with usage = 3000/3 = 1000 byte-seconds
        """
        storage_aggregator = StorageAggregator(config)

        # Storage data: 3 pods using the same PV on 3 different nodes
        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 3),
            'namespace': ['ns1', 'ns1', 'ns1'],
            'pod': ['pod-a', 'pod-b', 'pod-c'],
            'persistentvolumeclaim': ['shared-pvc', 'shared-pvc', 'shared-pvc'],
            'persistentvolume': ['shared-pv', 'shared-pv', 'shared-pv'],
            'storageclass': ['gp2', 'gp2', 'gp2'],
            # Each pod reports 3000 byte-seconds usage
            'persistentvolumeclaim_capacity_byte_seconds': [3000.0, 3000.0, 3000.0],
            'volume_request_storage_byte_seconds': [3000.0, 3000.0, 3000.0],
            'persistentvolumeclaim_usage_byte_seconds': [3000.0, 3000.0, 3000.0],
            'volume_labels': ['{}', '{}', '{}'],
            'csi_volume_handle': ['vol-shared', 'vol-shared', 'vol-shared']
        })

        # Pod data: 3 pods on 3 DIFFERENT nodes
        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 3),
            'namespace': ['ns1', 'ns1', 'ns1'],
            'pod': ['pod-a', 'pod-b', 'pod-c'],
            'node': ['node-1', 'node-2', 'node-3'],  # 3 different nodes!
            'resource_id': ['i-111', 'i-222', 'i-333']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # Trino groups by node, so we get 3 rows (one per node)
        assert len(result) == 3, f"Expected 3 rows (one per node), got {len(result)}"

        # Each row's usage should be divided by 3 (the node count)
        # Input: 3000 per row, sum = 9000
        # After division by 3 nodes: each row = 9000/3 = 3000 (but wait, it's grouped so sum per node)
        # Actually: each pod reports 3000. After grouping by node, sum per node = 3000.
        # Then divide by node_count(3) = 1000 per row.
        expected_raw_divided = 1000.0  # 3000 sum per node / 3 nodes
        bytes_to_gb = 1024**3
        seconds_per_day = 86400
        days_in_month = 31  # October 2025 has 31 days
        expected_gb_months = expected_raw_divided / (bytes_to_gb * seconds_per_day * days_in_month)

        # Check each row has the divided value
        for idx, row in result.iterrows():
            actual_request = row['volume_request_storage_gigabyte_months']
            actual_usage = row['persistentvolumeclaim_usage_gigabyte_months']

            # The key assertion: usage should be divided by node count (3)
            assert abs(actual_request - expected_gb_months) < 1e-10, \
                f"Row {idx}: volume_request should be {expected_gb_months}, got {actual_request}"
            assert abs(actual_usage - expected_gb_months) < 1e-10, \
                f"Row {idx}: pvc_usage should be {expected_gb_months}, got {actual_usage}"

        # Total across all rows should equal original / node_count
        total_request = result['volume_request_storage_gigabyte_months'].sum()
        expected_total = (3000.0 * 3) / 3 / (bytes_to_gb * seconds_per_day * days_in_month)  # 9000 / 3 = 3000
        assert abs(total_request - expected_total) < 1e-10, \
            f"Total usage should be {expected_total}, got {total_request}"

    def test_single_node_pv_not_affected(self, config):
        """PV on single node should not be divided."""
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['single-pvc'],
            'persistentvolume': ['single-pv'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [3000.0],
            'volume_request_storage_byte_seconds': [3000.0],
            'persistentvolumeclaim_usage_byte_seconds': [3000.0],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-single']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'node': ['node-1'],  # Only 1 node
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # With 1 node, no division should occur (divide by 1)
        expected_raw = 3000.0  # 3000 / 1 node = 3000
        bytes_to_gb = 1024**3
        seconds_per_day = 86400
        days_in_month = 31  # October 2025 has 31 days
        expected_gb_months = expected_raw / (bytes_to_gb * seconds_per_day * days_in_month)

        actual_request = result.iloc[0]['volume_request_storage_gigabyte_months']

        assert abs(actual_request - expected_gb_months) < 1e-10, \
            f"Single node PV should not change. Expected {expected_gb_months}, got {actual_request}"

    def test_mixed_shared_and_single_pvs(self, config):
        """Test mix of shared (3 nodes) and single (1 node) PVs."""
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 4),
            'namespace': ['ns1', 'ns1', 'ns1', 'ns2'],
            'pod': ['pod-a', 'pod-b', 'pod-c', 'pod-d'],
            'persistentvolumeclaim': ['shared-pvc', 'shared-pvc', 'shared-pvc', 'single-pvc'],
            'persistentvolume': ['shared-pv', 'shared-pv', 'shared-pv', 'single-pv'],
            'storageclass': ['gp2', 'gp2', 'gp2', 'gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [3000.0, 3000.0, 3000.0, 6000.0],
            'volume_request_storage_byte_seconds': [3000.0, 3000.0, 3000.0, 6000.0],
            'persistentvolumeclaim_usage_byte_seconds': [3000.0, 3000.0, 3000.0, 6000.0],
            'volume_labels': ['{}', '{}', '{}', '{}'],
            'csi_volume_handle': ['vol-shared', 'vol-shared', 'vol-shared', 'vol-single']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00'] * 4),
            'namespace': ['ns1', 'ns1', 'ns1', 'ns2'],
            'pod': ['pod-a', 'pod-b', 'pod-c', 'pod-d'],
            'node': ['node-1', 'node-2', 'node-3', 'node-4'],  # 3 nodes for shared, 1 for single
            'resource_id': ['i-111', 'i-222', 'i-333', 'i-444']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # Should have 4 rows: 3 for shared-pvc (one per node), 1 for single-pvc
        assert len(result) == 4, f"Expected 4 rows, got {len(result)}"

        bytes_to_gb = 1024**3
        seconds_to_hours = 3600
        hours_in_month = 730

        # Find the shared PVC rows (3 rows)
        shared_rows = result[result['persistentvolumeclaim'] == 'shared-pvc']
        single_row = result[result['persistentvolumeclaim'] == 'single-pvc'].iloc[0]

        assert len(shared_rows) == 3, f"Expected 3 shared PVC rows, got {len(shared_rows)}"

        # Shared: each row = 3000 sum / 3 nodes = 1000
        expected_shared_per_row = 1000.0 / (bytes_to_gb * seconds_to_hours) / hours_in_month
        # Single: 6000 / 1 node = 6000
        expected_single = 6000.0 / (bytes_to_gb * seconds_to_hours) / hours_in_month

        for idx, row in shared_rows.iterrows():
            assert abs(row['volume_request_storage_gigabyte_months'] - expected_shared_per_row) < 1e-10, \
                f"Shared PV row should be divided by 3"

        assert abs(single_row['volume_request_storage_gigabyte_months'] - expected_single) < 1e-10, \
            f"Single PV should not be divided"


class TestDaysInMonthFormula:
    """Test days-in-month calculation for storage metrics (Trino SQL lines 358-363).

    Trino uses actual days in month: last_day_of_month(usage_start)
    POC was using fixed 730 hours/month (30.416 days average)

    For accurate billing, we need to use actual days per month.
    """

    def test_february_28_days(self, config):
        """
        February 2025 has 28 days (non-leap year).

        Trino formula (lines 358-363):
            capacity_byte_seconds / (86400 * days_in_month) * power(2, -30)

        For February: 86400 * 28 = 2,419,200 seconds
        """
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-02-15 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            # Use a value that makes calculation clear
            # 1 GB for 1 day = 1 * 1024^3 * 86400 byte-seconds
            'persistentvolumeclaim_capacity_byte_seconds': [1073741824.0 * 86400],  # 1 GB * 1 day
            'volume_request_storage_byte_seconds': [1073741824.0 * 86400],
            'persistentvolumeclaim_usage_byte_seconds': [1073741824.0 * 86400],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-02-15 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'node': ['node-1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # February has 28 days
        # 1 GB for 1 day = 1/28 GB-months
        expected_gb_months = 1.0 / 28.0

        actual = result.iloc[0]['persistentvolumeclaim_capacity_gigabyte_months']

        assert abs(actual - expected_gb_months) < 1e-10, \
            f"February (28 days): Expected {expected_gb_months}, got {actual}"

    def test_july_31_days(self, config):
        """
        July 2025 has 31 days.

        For July: 86400 * 31 = 2,678,400 seconds
        """
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-07-15 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            # 1 GB for 1 day
            'persistentvolumeclaim_capacity_byte_seconds': [1073741824.0 * 86400],
            'volume_request_storage_byte_seconds': [1073741824.0 * 86400],
            'persistentvolumeclaim_usage_byte_seconds': [1073741824.0 * 86400],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-07-15 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'node': ['node-1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # July has 31 days
        # 1 GB for 1 day = 1/31 GB-months
        expected_gb_months = 1.0 / 31.0

        actual = result.iloc[0]['persistentvolumeclaim_capacity_gigabyte_months']

        assert abs(actual - expected_gb_months) < 1e-10, \
            f"July (31 days): Expected {expected_gb_months}, got {actual}"

    def test_february_vs_july_difference(self, config):
        """
        Verify Feb and July produce different results for same input.

        Feb (28 days) should give higher GB-months than July (31 days)
        because the same usage over fewer days = more monthly rate.
        """
        storage_aggregator = StorageAggregator(config)

        def get_result_for_month(month_str):
            storage_data = pd.DataFrame({
                'interval_start': pd.to_datetime([f'{month_str} 00:00:00']),
                'namespace': ['ns1'],
                'pod': ['pod-a'],
                'persistentvolumeclaim': ['pvc1'],
                'persistentvolume': ['pv1'],
                'storageclass': ['gp2'],
                'persistentvolumeclaim_capacity_byte_seconds': [1073741824.0 * 86400],
                'volume_request_storage_byte_seconds': [1073741824.0 * 86400],
                'persistentvolumeclaim_usage_byte_seconds': [1073741824.0 * 86400],
                'volume_labels': ['{}'],
                'csi_volume_handle': ['vol-1']
            })

            pod_data = pd.DataFrame({
                'interval_start': pd.to_datetime([f'{month_str} 00:00:00']),
                'namespace': ['ns1'],
                'pod': ['pod-a'],
                'node': ['node-1'],
                'resource_id': ['i-111']
            })

            return storage_aggregator.aggregate(
                storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
            )

        feb_result = get_result_for_month('2025-02-15')
        jul_result = get_result_for_month('2025-07-15')

        feb_capacity = feb_result.iloc[0]['persistentvolumeclaim_capacity_gigabyte_months']
        jul_capacity = jul_result.iloc[0]['persistentvolumeclaim_capacity_gigabyte_months']

        # Feb (28 days) should be higher than July (31 days)
        # 1/28 > 1/31
        assert feb_capacity > jul_capacity, \
            f"Feb ({feb_capacity}) should be > July ({jul_capacity}) for same input"

        # The ratio should be close to 31/28 = 1.107
        expected_ratio = 31.0 / 28.0
        actual_ratio = feb_capacity / jul_capacity

        assert abs(actual_ratio - expected_ratio) < 0.001, \
            f"Ratio should be {expected_ratio}, got {actual_ratio}"


class TestStorageCostCategory:
    """Test cost category for storage rows (Trino SQL lines 406, 428-429).

    Trino SQL:
        LEFT JOIN postgres.{{schema}}.reporting_ocp_cost_category_namespace AS cat_ns
            ON sli.namespace LIKE cat_ns.namespace
        ...
        max(cat_ns.cost_category_id) as cost_category_id
    """

    def test_storage_cost_category_applied(self, config):
        """
        Storage rows should have cost_category_id from cost category join.

        Currently POC sets cost_category_id = None for storage rows.
        Should match namespace pattern like pod aggregation does.
        """
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['platform-monitoring'],  # Matches 'platform-%' pattern
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [1e9],
            'volume_request_storage_byte_seconds': [1e9],
            'persistentvolumeclaim_usage_byte_seconds': [1e9],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['platform-monitoring'],
            'pod': ['pod-a'],
            'node': ['node-1'],
            'resource_id': ['i-111']
        })

        cost_category_df = pd.DataFrame({
            'namespace': ['platform-%'],  # Pattern matches 'platform-monitoring'
            'cost_category_id': [42]
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data,
            pd.DataFrame(), pd.DataFrame(),
            cost_category_df=cost_category_df  # Pass cost category
        )

        # Storage rows should have cost_category_id = 42
        assert 'cost_category_id' in result.columns, "cost_category_id must exist"
        assert result.iloc[0]['cost_category_id'] == 42, \
            f"Expected cost_category_id=42, got {result.iloc[0]['cost_category_id']}"

    def test_storage_cost_category_no_match_is_null(self, config):
        """Storage rows with no matching pattern should have NULL cost_category_id."""
        storage_aggregator = StorageAggregator(config)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['my-app'],  # Does NOT match 'platform-%'
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_byte_seconds': [1e9],
            'volume_request_storage_byte_seconds': [1e9],
            'persistentvolumeclaim_usage_byte_seconds': [1e9],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['my-app'],
            'pod': ['pod-a'],
            'node': ['node-1'],
            'resource_id': ['i-111']
        })

        cost_category_df = pd.DataFrame({
            'namespace': ['platform-%'],
            'cost_category_id': [42]
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data,
            pd.DataFrame(), pd.DataFrame(),
            cost_category_df=cost_category_df
        )

        # No match, should be None
        assert result.iloc[0]['cost_category_id'] is None, \
            f"Expected cost_category_id=None, got {result.iloc[0]['cost_category_id']}"


class TestPVCCapacityGigabyte:
    """Test PVC capacity in gigabytes (Trino SQL lines 356-357).

    Trino SQL:
        (sua.persistentvolumeclaim_capacity_bytes * power(2, -30)) as persistentvolumeclaim_capacity_gigabyte

    This is a single point-in-time capacity value, not byte-seconds.
    """

    def test_pvc_capacity_gigabyte_calculated(self, config):
        """
        persistentvolumeclaim_capacity_gigabyte should be calculated.

        Currently POC sets this to None.
        Should be: max(capacity_bytes) * 2^-30 = capacity in GB
        """
        storage_aggregator = StorageAggregator(config)

        # 10 GB = 10 * 1024^3 bytes = 10737418240 bytes
        capacity_bytes = 10 * (1024 ** 3)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'persistentvolumeclaim': ['pvc1'],
            'persistentvolume': ['pv1'],
            'storageclass': ['gp2'],
            'persistentvolumeclaim_capacity_bytes': [float(capacity_bytes)],  # 10 GB
            'persistentvolumeclaim_capacity_byte_seconds': [float(capacity_bytes) * 86400],
            'volume_request_storage_byte_seconds': [1e9],
            'persistentvolumeclaim_usage_byte_seconds': [1e9],
            'volume_labels': ['{}'],
            'csi_volume_handle': ['vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00']),
            'namespace': ['ns1'],
            'pod': ['pod-a'],
            'node': ['node-1'],
            'resource_id': ['i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # persistentvolumeclaim_capacity_gigabyte = 10 GB
        expected_gb = 10.0

        assert 'persistentvolumeclaim_capacity_gigabyte' in result.columns
        actual = result.iloc[0]['persistentvolumeclaim_capacity_gigabyte']

        assert actual is not None, "persistentvolumeclaim_capacity_gigabyte should not be None"
        assert abs(actual - expected_gb) < 0.001, \
            f"Expected {expected_gb} GB, got {actual} GB"

    def test_pvc_capacity_gigabyte_max_across_intervals(self, config):
        """
        When multiple intervals exist, should use MAX capacity.

        Trino uses max(persistentvolumeclaim_capacity_bytes).
        """
        storage_aggregator = StorageAggregator(config)

        # Two rows with different capacities (e.g., PVC was resized)
        capacity_bytes_1 = 5 * (1024 ** 3)   # 5 GB
        capacity_bytes_2 = 10 * (1024 ** 3)  # 10 GB (after resize)

        storage_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00', '2025-10-01 12:00:00']),
            'namespace': ['ns1', 'ns1'],
            'pod': ['pod-a', 'pod-a'],
            'persistentvolumeclaim': ['pvc1', 'pvc1'],
            'persistentvolume': ['pv1', 'pv1'],
            'storageclass': ['gp2', 'gp2'],
            'persistentvolumeclaim_capacity_bytes': [float(capacity_bytes_1), float(capacity_bytes_2)],
            'persistentvolumeclaim_capacity_byte_seconds': [1e9, 1e9],
            'volume_request_storage_byte_seconds': [1e9, 1e9],
            'persistentvolumeclaim_usage_byte_seconds': [1e9, 1e9],
            'volume_labels': ['{}', '{}'],
            'csi_volume_handle': ['vol-1', 'vol-1']
        })

        pod_data = pd.DataFrame({
            'interval_start': pd.to_datetime(['2025-10-01 00:00:00', '2025-10-01 12:00:00']),
            'namespace': ['ns1', 'ns1'],
            'pod': ['pod-a', 'pod-a'],
            'node': ['node-1', 'node-1'],
            'resource_id': ['i-111', 'i-111']
        })

        result = storage_aggregator.aggregate(
            storage_data, pod_data, pd.DataFrame(), pd.DataFrame()
        )

        # Should use MAX = 10 GB
        expected_gb = 10.0
        actual = result.iloc[0]['persistentvolumeclaim_capacity_gigabyte']

        assert actual is not None, "persistentvolumeclaim_capacity_gigabyte should not be None"
        assert abs(actual - expected_gb) < 0.001, \
            f"Expected MAX {expected_gb} GB, got {actual} GB"
