"""
Tests for all_labels column (TDD).

Trino SQL lines 651-654:
json_parse(json_format(cast(map_concat(
    cast(json_parse(coalesce(pod_labels, '{}')) as map(varchar, varchar)),
    cast(json_parse(coalesce(volume_labels, '{}')) as map(varchar, varchar))
)as json))) as all_labels

The all_labels column is a merge of pod_labels + volume_labels.
For Pod data: all_labels = pod_labels (volume_labels is NULL)
For Storage data: all_labels = merge(pod_labels, volume_labels)
"""

import json
from datetime import date

import pandas as pd
import pytest


class TestAllLabelsColumn:
    """Test all_labels column generation."""

    @pytest.fixture
    def sample_pod_config(self):
        """Sample configuration for pod aggregator."""
        return {
            "ocp": {
                "cluster_id": "test-cluster",
                "cluster_alias": "Test Cluster",
                "provider_uuid": "provider-uuid",
                "report_period_id": 1,
            },
            "performance": {
                "use_arrow_compute": False,
            },
        }

    @pytest.fixture
    def sample_pod_usage(self):
        """Sample pod usage data."""
        return pd.DataFrame(
            {
                "interval_start": [pd.Timestamp("2024-01-15 00:00:00")],
                "namespace": ["app-namespace"],
                "node": ["worker-0"],
                "pod": ["app-pod-1"],
                "resource_id": ["i-worker0"],
                "pod_labels": ['{"app": "myapp", "env": "prod"}'],
                "pod_usage_cpu_core_seconds": [3600.0],
                "pod_request_cpu_core_seconds": [7200.0],
                "pod_effective_usage_cpu_core_seconds": [7200.0],
                "pod_limit_cpu_core_seconds": [14400.0],
                "pod_usage_memory_byte_seconds": [1073741824.0 * 3600],  # 1GB * 3600s
                "pod_request_memory_byte_seconds": [2147483648.0 * 3600],  # 2GB * 3600s
                "pod_effective_usage_memory_byte_seconds": [2147483648.0 * 3600],
                "pod_limit_memory_byte_seconds": [4294967296.0 * 3600],  # 4GB * 3600s
                "node_capacity_cpu_cores": [16.0],
                "node_capacity_cpu_core_seconds": [16.0 * 3600],
                "node_capacity_memory_bytes": [64.0 * 1024**3],
                "node_capacity_memory_byte_seconds": [64.0 * 1024**3 * 3600],
            }
        )

    @pytest.fixture
    def sample_node_capacity(self):
        """Sample node capacity data."""
        return pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)],
                "node": ["worker-0"],
                "node_capacity_cpu_core_hours": [384.0],
                "node_capacity_memory_gigabyte_hours": [1536.0],
                "cluster_capacity_cpu_core_hours": [384.0],
                "cluster_capacity_memory_gigabyte_hours": [1536.0],
            }
        )

    # =========================================================================
    # Test 1: Pod data has all_labels = pod_labels
    # =========================================================================
    def test_pod_data_all_labels_equals_pod_labels(self, sample_pod_config, sample_pod_usage, sample_node_capacity):
        """Test that for Pod data, all_labels equals pod_labels (volume_labels is NULL).

        Trino: all_labels = map_concat(pod_labels, coalesce(volume_labels, '{}'))
        For Pod data, volume_labels is NULL, so all_labels = pod_labels
        """
        from src.aggregator_pod import PodAggregator

        enabled_keys = ["app", "env"]
        aggregator = PodAggregator(sample_pod_config, enabled_keys)

        result = aggregator.aggregate(
            pod_usage_df=sample_pod_usage,
            node_capacity_df=sample_node_capacity,
            node_labels_df=None,
            namespace_labels_df=None,
            cost_category_df=None,
        )

        # all_labels column must exist
        assert "all_labels" in result.columns, "all_labels column missing from output"

        # For Pod data, all_labels should equal pod_labels
        row = result.iloc[0]
        pod_labels = json.loads(row["pod_labels"]) if row["pod_labels"] else {}
        all_labels = json.loads(row["all_labels"]) if row["all_labels"] else {}

        assert all_labels == pod_labels, f"all_labels {all_labels} != pod_labels {pod_labels}"

    # =========================================================================
    # Test 2: Storage data has all_labels = merge(pod_labels, volume_labels)
    # =========================================================================
    def test_storage_data_all_labels_merges_pod_and_volume(self, sample_pod_config):
        """Test that for Storage data, all_labels merges pod_labels and volume_labels.

        Trino: all_labels = map_concat(pod_labels, volume_labels)
        Volume labels take precedence over pod labels.
        """
        from src.aggregator_storage import StorageAggregator

        storage_df = pd.DataFrame(
            {
                "interval_start": [pd.Timestamp("2024-01-15 00:00:00")],
                "namespace": ["app-namespace"],
                "pod": ["app-pod-1"],
                "persistentvolumeclaim": ["pvc-1"],
                "persistentvolume": ["pv-1"],
                "storageclass": ["gp2"],
                "csi_volume_handle": ["vol-123"],
                "persistentvolume_labels": ['{"storage": "fast"}'],
                "persistentvolumeclaim_labels": ['{"pvc": "mydata"}'],
                "persistentvolumeclaim_capacity_bytes": [10737418240.0],  # 10GB
                "persistentvolumeclaim_capacity_byte_seconds": [10737418240.0 * 86400],
                "volume_request_storage_byte_seconds": [5368709120.0 * 86400],  # 5GB
                "persistentvolumeclaim_usage_byte_seconds": [3221225472.0 * 86400],  # 3GB
            }
        )

        # Pod data needs interval_start for the storage aggregator join
        pod_df = pd.DataFrame(
            {
                "interval_start": [pd.Timestamp("2024-01-15 00:00:00")],
                "namespace": ["app-namespace"],
                "pod": ["app-pod-1"],
                "node": ["worker-0"],
                "resource_id": ["i-worker0"],
            }
        )

        node_labels_df = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)],
                "node": ["worker-0"],
                "node_labels": ['{"node_type": "compute"}'],
            }
        )

        namespace_labels_df = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)],
                "namespace": ["app-namespace"],
                "namespace_labels": ['{"team": "platform"}'],
            }
        )

        aggregator = StorageAggregator(sample_pod_config)

        result = aggregator.aggregate(
            storage_df=storage_df,
            pod_df=pod_df,
            node_labels_df=node_labels_df,
            namespace_labels_df=namespace_labels_df,
        )

        # all_labels column must exist
        assert "all_labels" in result.columns, "all_labels column missing from storage output"

        # For Storage data, all_labels should contain volume_labels
        row = result.iloc[0]
        all_labels_str = row["all_labels"] if row["all_labels"] else "{}"
        volume_labels_str = row["volume_labels"] if row["volume_labels"] else "{}"

        # Parse JSON strings to dicts
        all_labels = json.loads(all_labels_str) if isinstance(all_labels_str, str) else all_labels_str
        volume_labels = json.loads(volume_labels_str) if isinstance(volume_labels_str, str) else volume_labels_str

        # volume_labels should be a subset of all_labels
        for key, value in volume_labels.items():
            assert key in all_labels, f"volume_labels key '{key}' missing from all_labels"
            assert all_labels[key] == value, f"all_labels[{key}] = {all_labels[key]} != {value}"

    # =========================================================================
    # Test 3: all_labels is valid JSON
    # =========================================================================
    def test_all_labels_is_valid_json(self, sample_pod_config, sample_pod_usage, sample_node_capacity):
        """Test that all_labels is always valid JSON string."""
        from src.aggregator_pod import PodAggregator

        enabled_keys = ["app", "env"]
        aggregator = PodAggregator(sample_pod_config, enabled_keys)

        result = aggregator.aggregate(
            pod_usage_df=sample_pod_usage,
            node_capacity_df=sample_node_capacity,
            node_labels_df=None,
            namespace_labels_df=None,
            cost_category_df=None,
        )

        for idx, row in result.iterrows():
            all_labels_str = row["all_labels"]
            assert all_labels_str is not None, f"all_labels is None at row {idx}"
            assert isinstance(all_labels_str, str), f"all_labels is not a string at row {idx}"

            # Should be valid JSON that parses to a dict
            try:
                parsed = json.loads(all_labels_str)
                assert isinstance(parsed, dict), f"all_labels does not parse to dict at row {idx}: {type(parsed)}"
            except json.JSONDecodeError as e:
                pytest.fail(f"all_labels is not valid JSON at row {idx}: {e}")

    # =========================================================================
    # Test 4: Empty labels produce empty JSON object
    # =========================================================================
    def test_empty_labels_produce_empty_json(self, sample_pod_config, sample_node_capacity):
        """Test that empty/null labels produce '{}'."""
        from src.aggregator_pod import PodAggregator

        pod_usage = pd.DataFrame(
            {
                "interval_start": [pd.Timestamp("2024-01-15 00:00:00")],
                "namespace": ["app-namespace"],
                "node": ["worker-0"],
                "pod": ["app-pod-1"],
                "resource_id": ["i-worker0"],
                "pod_labels": ["{}"],  # Empty labels
                "pod_usage_cpu_core_seconds": [3600.0],
                "pod_request_cpu_core_seconds": [7200.0],
                "pod_effective_usage_cpu_core_seconds": [7200.0],
                "pod_limit_cpu_core_seconds": [14400.0],
                "pod_usage_memory_byte_seconds": [1073741824.0 * 3600],
                "pod_request_memory_byte_seconds": [2147483648.0 * 3600],
                "pod_effective_usage_memory_byte_seconds": [2147483648.0 * 3600],
                "pod_limit_memory_byte_seconds": [4294967296.0 * 3600],
                "node_capacity_cpu_cores": [16.0],
                "node_capacity_cpu_core_seconds": [16.0 * 3600],
                "node_capacity_memory_bytes": [64.0 * 1024**3],
                "node_capacity_memory_byte_seconds": [64.0 * 1024**3 * 3600],
            }
        )

        enabled_keys = []  # No enabled keys
        aggregator = PodAggregator(sample_pod_config, enabled_keys)

        result = aggregator.aggregate(
            pod_usage_df=pod_usage,
            node_capacity_df=sample_node_capacity,
            node_labels_df=None,
            namespace_labels_df=None,
            cost_category_df=None,
        )

        row = result.iloc[0]
        all_labels_str = row["all_labels"]

        # all_labels should be a JSON string '{}' or parse to empty dict
        assert all_labels_str is not None, "all_labels is None"
        parsed = json.loads(all_labels_str) if isinstance(all_labels_str, str) else all_labels_str
        assert parsed == {}, f"Expected empty dict, got {parsed}"

    # =========================================================================
    # Test 5: Unallocated capacity has all_labels = '{}'
    # =========================================================================
    def test_unallocated_capacity_all_labels_empty(self):
        """Test that unallocated capacity rows have empty all_labels.

        Unallocated capacity rows don't have pod_labels or volume_labels,
        so all_labels should be '{}'.
        """
        from src.aggregator_unallocated import UnallocatedCapacityAggregator

        config = {
            "ocp": {
                "cluster_id": "test-cluster",
                "cluster_alias": "Test Cluster",
                "provider_uuid": "provider-uuid",
                "report_period_id": 1,
            }
        }

        daily_summary = pd.DataFrame(
            {
                "usage_start": [date(2024, 1, 15)],
                "namespace": ["app-namespace"],
                "node": ["worker-0"],
                "resource_id": ["i-worker0"],
                "pod_usage_cpu_core_hours": [10.0],
                "pod_request_cpu_core_hours": [12.0],
                "pod_effective_usage_cpu_core_hours": [12.0],
                "pod_usage_memory_gigabyte_hours": [5.0],
                "pod_request_memory_gigabyte_hours": [6.0],
                "pod_effective_usage_memory_gigabyte_hours": [6.0],
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

        node_roles = pd.DataFrame(
            {
                "node": ["worker-0"],
                "resource_id": ["i-worker0"],
                "node_role": ["worker"],
            }
        )

        aggregator = UnallocatedCapacityAggregator(config)

        result = aggregator.calculate_unallocated(daily_summary_df=daily_summary, node_roles_df=node_roles)

        # all_labels column must exist
        assert "all_labels" in result.columns, "all_labels column missing from unallocated output"

        row = result.iloc[0]
        all_labels = json.loads(row["all_labels"]) if row["all_labels"] else {}

        assert all_labels == {}, f"Expected empty dict for unallocated, got {all_labels}"
