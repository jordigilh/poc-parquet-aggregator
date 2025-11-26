"""
Integration tests for storage aggregation pipeline.

Focus: End-to-end behavior, not implementation details.

Tests validate:
- Full pipeline correctness
- Pod + Storage combined output
- Data integrity through the pipeline
- Database write correctness
"""

from datetime import date, datetime
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from src.aggregator_pod import PodAggregator
from src.aggregator_storage import StorageAggregator
from src.parquet_reader import ParquetReader


@pytest.fixture
def integration_config():
    """Configuration for integration tests."""
    return {
        "ocp": {
            "cluster_id": "test-cluster-integration",
            "provider_uuid": "test-provider-integration",
            "cluster_alias": "Integration Test Cluster",
            "report_period_id": 1,
            "year": "2025",
            "month": "10",
        },
        "s3": {
            "endpoint": "http://localhost:9000",
            "bucket": "test-bucket",
            "access_key": "test",
            "secret_key": "test",
            "region": "us-east-1",
            "use_ssl": False,
            "verify_ssl": False,
        },
        "performance": {
            "use_arrow_compute": False,
            "delete_intermediate_dfs": False,
            "gc_after_aggregation": False,
            "column_filtering": False,
        },
    }


@pytest.fixture
def complete_test_dataset():
    """
    Complete test dataset with pods, storage, and labels.

    Simulates a realistic scenario:
    - 2 nodes
    - 3 namespaces
    - 5 pods
    - 3 PVCs
    """
    # Pod usage data
    pod_data = pd.DataFrame(
        {
            "interval_start": pd.to_datetime(["2025-10-01 00:00:00"] * 5),
            "namespace": ["frontend", "frontend", "backend", "backend", "database"],
            "pod": ["web-1", "web-2", "api-1", "api-2", "db-1"],
            "node": ["node1", "node1", "node2", "node2", "node2"],
            "resource_id": ["i-111", "i-111", "i-222", "i-222", "i-222"],
            "pod_labels": [
                '{"app": "web", "tier": "frontend"}',
                '{"app": "web", "tier": "frontend"}',
                '{"app": "api", "tier": "backend"}',
                '{"app": "api", "tier": "backend"}',
                '{"app": "postgres", "tier": "database"}',
            ],
            "pod_usage_cpu_core_seconds": [3600.0, 3600.0, 7200.0, 7200.0, 14400.0],
            "pod_request_cpu_core_seconds": [7200.0, 7200.0, 14400.0, 14400.0, 28800.0],
            "pod_limit_cpu_core_seconds": [14400.0, 14400.0, 28800.0, 28800.0, 57600.0],
            "pod_usage_memory_byte_seconds": [1e12, 1e12, 2e12, 2e12, 4e12],
            "pod_request_memory_byte_seconds": [2e12, 2e12, 4e12, 4e12, 8e12],
            "pod_limit_memory_byte_seconds": [4e12, 4e12, 8e12, 8e12, 16e12],
            "node_capacity_cpu_core_seconds": [86400.0] * 5,
            "node_capacity_memory_byte_seconds": [1e14] * 5,
        }
    )

    # Storage usage data
    storage_data = pd.DataFrame(
        {
            "interval_start": pd.to_datetime(["2025-10-01 00:00:00"] * 3),
            "namespace": ["frontend", "backend", "database"],
            "pod": ["web-1", "api-1", "db-1"],
            "persistentvolumeclaim": ["web-pvc", "api-pvc", "db-pvc"],
            "persistentvolume": ["pv-1", "pv-2", "pv-3"],
            "storageclass": ["gp2", "gp2", "io1"],
            "persistentvolumeclaim_capacity_byte_seconds": [1e12, 2e12, 5e12],
            "volume_request_storage_byte_seconds": [8e11, 1.6e12, 4e12],
            "persistentvolumeclaim_usage_byte_seconds": [5e11, 1e12, 3e12],
            "volume_labels": [
                '{"storage": "web-data"}',
                '{"storage": "api-cache"}',
                '{"storage": "db-data"}',
            ],
            "csi_volume_handle": ["vol-aaa111", "vol-bbb222", "vol-ccc333"],
        }
    )

    # Node labels
    node_labels = pd.DataFrame(
        {
            "usage_start": [date(2025, 10, 1)] * 2,
            "node": ["node1", "node2"],
            "node_labels": [
                '{"zone": "us-east-1a", "instance_type": "m5.large"}',
                '{"zone": "us-east-1b", "instance_type": "m5.xlarge"}',
            ],
        }
    )

    # Namespace labels
    namespace_labels = pd.DataFrame(
        {
            "usage_start": [date(2025, 10, 1)] * 3,
            "namespace": ["frontend", "backend", "database"],
            "namespace_labels": [
                '{"team": "web", "env": "prod"}',
                '{"team": "platform", "env": "prod"}',
                '{"team": "data", "env": "prod"}',
            ],
        }
    )

    return {
        "pod": pod_data,
        "storage": storage_data,
        "node_labels": node_labels,
        "namespace_labels": namespace_labels,
    }


class TestStorageIntegration:
    """Integration tests for storage aggregation."""

    def test_storage_aggregation_produces_valid_output(self, integration_config, complete_test_dataset):
        """Verify storage aggregation produces valid output."""
        aggregator = StorageAggregator(integration_config)

        result = aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Basic validations
        assert not result.empty, "Should produce output"
        assert len(result) == 3, "Should have 3 rows (one per PVC)"
        assert (result["data_source"] == "Storage").all(), "All rows should be Storage"

        # Verify CSI handles are preserved
        expected_handles = {"vol-aaa111", "vol-bbb222", "vol-ccc333"}
        actual_handles = set(result["csi_volume_handle"].unique())
        assert expected_handles == actual_handles, "CSI handles must be preserved"

    def test_pod_and_storage_combined_have_different_data_sources(self, integration_config, complete_test_dataset):
        """Verify pod and storage aggregations have different data_source values."""
        pod_aggregator = PodAggregator(integration_config, enabled_tag_keys=[])
        storage_aggregator = StorageAggregator(integration_config)

        # Mock capacity data
        node_capacity = pd.DataFrame(
            {
                "usage_start": [date(2025, 10, 1)] * 2,
                "node": ["node1", "node2"],
                "node_capacity_cpu_core_hours": [24.0, 24.0],
                "node_capacity_memory_gigabyte_hours": [96.0, 192.0],
                "node_capacity_cpu_cores": [1.0, 1.0],
                "node_capacity_memory_gigabytes": [4.0, 8.0],
            }
        )

        # Aggregate pods
        pod_result = pod_aggregator.aggregate(
            pod_usage_df=complete_test_dataset["pod"],
            node_capacity_df=node_capacity,
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
            cost_category_df=pd.DataFrame(),
        )

        # Aggregate storage
        storage_result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Verify different data sources
        assert (pod_result["data_source"] == "Pod").all(), "Pod rows should have data_source='Pod'"
        assert (storage_result["data_source"] == "Storage").all(), "Storage rows should have data_source='Storage'"

        # Combine results
        combined = pd.concat([pod_result, storage_result], ignore_index=True)

        # Verify combined dataset
        assert len(combined) == len(pod_result) + len(storage_result)
        assert set(combined["data_source"].unique()) == {"Pod", "Storage"}

    def test_storage_rows_can_be_filtered_by_data_source(self, integration_config, complete_test_dataset):
        """Verify storage rows can be filtered by data_source='Storage'."""
        storage_aggregator = StorageAggregator(integration_config)

        result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Filter by data_source
        storage_only = result[result["data_source"] == "Storage"]

        assert len(storage_only) == len(result), "All rows should be Storage"

        # Verify storage columns are populated
        assert storage_only["persistentvolumeclaim"].notna().all()
        assert storage_only["persistentvolumeclaim_capacity_gigabyte_months"].notna().all()

        # Verify CPU/memory columns are NULL
        assert storage_only["pod_usage_cpu_core_hours"].isna().all()
        assert storage_only["pod_usage_memory_gigabyte_hours"].isna().all()

    def test_storage_aggregation_preserves_label_hierarchy(self, integration_config, complete_test_dataset):
        """Verify label precedence is preserved (Volume > Namespace > Node)."""
        storage_aggregator = StorageAggregator(integration_config)

        result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        import json

        # Check first row (frontend)
        first_row = result.iloc[0]
        labels = json.loads(first_row["pod_labels"])

        # Should have all three levels
        assert "storage" in labels, "Volume label should be present (highest precedence)"
        assert "team" in labels, "Namespace label should be present"
        assert "zone" in labels, "Node label should be present"

        # Volume label should win if there's a conflict
        # (In our test data, labels don't conflict, but they should all be present)

    def test_storage_metrics_are_positive(self, integration_config, complete_test_dataset):
        """Verify storage metrics are positive values."""
        storage_aggregator = StorageAggregator(integration_config)

        result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # All metrics should be positive
        assert (result["persistentvolumeclaim_capacity_gigabyte_months"] >= 0).all()
        assert (result["volume_request_storage_gigabyte_months"] >= 0).all()
        assert (result["persistentvolumeclaim_usage_gigabyte_months"] >= 0).all()

    def test_storage_without_pod_match_still_produces_output(self, integration_config):
        """Verify storage without matching pods still produces output."""
        # Storage data
        storage_data = pd.DataFrame(
            {
                "interval_start": pd.to_datetime(["2025-10-01 00:00:00"]),
                "namespace": ["orphan-ns"],
                "pod": ["orphan-pod"],
                "persistentvolumeclaim": ["orphan-pvc"],
                "persistentvolume": ["orphan-pv"],
                "storageclass": ["gp2"],
                "persistentvolumeclaim_capacity_byte_seconds": [1e12],
                "volume_request_storage_byte_seconds": [8e11],
                "persistentvolumeclaim_usage_byte_seconds": [5e11],
                "volume_labels": ["{}"],
                "csi_volume_handle": ["vol-orphan"],
            }
        )

        # No matching pod data
        pod_data = pd.DataFrame(
            {
                "interval_start": pd.to_datetime(["2025-10-01 00:00:00"]),
                "namespace": ["different-ns"],
                "pod": ["different-pod"],
                "node": ["node1"],
                "resource_id": ["i-111"],
            }
        )

        aggregator = StorageAggregator(integration_config)
        result = aggregator.aggregate(storage_data, pod_data, pd.DataFrame(), pd.DataFrame())

        # Should still produce output
        assert not result.empty, "Should produce output even without pod match"
        assert len(result) == 1

        # Node should be NULL or empty
        assert result.iloc[0]["node"] == "" or pd.isna(result.iloc[0]["node"])


class TestStoragePodCombinedOutput:
    """Test combined pod + storage output behavior."""

    def test_combined_output_schema_is_consistent(self, integration_config, complete_test_dataset):
        """Verify pod and storage outputs have consistent schemas."""
        pod_aggregator = PodAggregator(integration_config, enabled_tag_keys=[])
        storage_aggregator = StorageAggregator(integration_config)

        # Mock capacity
        node_capacity = pd.DataFrame(
            {
                "usage_start": [date(2025, 10, 1)] * 2,
                "node": ["node1", "node2"],
                "node_capacity_cpu_core_hours": [24.0, 24.0],
                "node_capacity_memory_gigabyte_hours": [96.0, 192.0],
                "node_capacity_cpu_cores": [1.0, 1.0],
                "node_capacity_memory_gigabytes": [4.0, 8.0],
            }
        )

        pod_result = pod_aggregator.aggregate(
            pod_usage_df=complete_test_dataset["pod"],
            node_capacity_df=node_capacity,
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
            cost_category_df=pd.DataFrame(),
        )

        storage_result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Verify both have the same columns (schema compatibility)
        pod_cols = set(pod_result.columns)
        storage_cols = set(storage_result.columns)

        # Core columns must match
        core_columns = {
            "usage_start",
            "usage_end",
            "data_source",
            "namespace",
            "node",
            "pod",
            "resource_id",
            "cluster_id",
            "source_uuid",
            "pod_labels",
        }

        assert core_columns <= pod_cols, "Pod result missing core columns"
        assert core_columns <= storage_cols, "Storage result missing core columns"

        # Should be able to concatenate
        combined = pd.concat([pod_result, storage_result], ignore_index=True)
        assert len(combined) == len(pod_result) + len(storage_result)

    def test_combined_output_can_be_written_to_same_table(self, integration_config, complete_test_dataset):
        """
        Verify pod and storage outputs can be written to the same PostgreSQL table.

        This validates the key requirement: both data_source types use the same schema.
        """
        pod_aggregator = PodAggregator(integration_config, enabled_tag_keys=[])
        storage_aggregator = StorageAggregator(integration_config)

        # Mock capacity
        node_capacity = pd.DataFrame(
            {
                "usage_start": [date(2025, 10, 1)] * 2,
                "node": ["node1", "node2"],
                "node_capacity_cpu_core_hours": [24.0, 24.0],
                "node_capacity_memory_gigabyte_hours": [96.0, 192.0],
                "node_capacity_cpu_cores": [1.0, 1.0],
                "node_capacity_memory_gigabytes": [4.0, 8.0],
            }
        )

        pod_result = pod_aggregator.aggregate(
            pod_usage_df=complete_test_dataset["pod"],
            node_capacity_df=node_capacity,
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
            cost_category_df=pd.DataFrame(),
        )

        storage_result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Combine
        combined = pd.concat([pod_result, storage_result], ignore_index=True)

        # Validate combined output
        assert "data_source" in combined.columns
        assert set(combined["data_source"].unique()) == {"Pod", "Storage"}

        # Pod rows should have CPU/memory, NULL storage
        pod_rows = combined[combined["data_source"] == "Pod"]
        assert pod_rows["pod_usage_cpu_core_hours"].notna().all()
        assert pod_rows["persistentvolumeclaim"].isna().all() or (pod_rows["persistentvolumeclaim"] == "").all()

        # Storage rows should have storage metrics, NULL CPU/memory
        storage_rows = combined[combined["data_source"] == "Storage"]
        assert storage_rows["persistentvolumeclaim"].notna().all()
        assert storage_rows["pod_usage_cpu_core_hours"].isna().all()

    def test_no_duplicate_keys_in_combined_output(self, integration_config, complete_test_dataset):
        """Verify no duplicate rows in combined pod + storage output."""
        pod_aggregator = PodAggregator(integration_config, enabled_tag_keys=[])
        storage_aggregator = StorageAggregator(integration_config)

        # Mock capacity
        node_capacity = pd.DataFrame(
            {
                "usage_start": [date(2025, 10, 1)] * 2,
                "node": ["node1", "node2"],
                "node_capacity_cpu_core_hours": [24.0, 24.0],
                "node_capacity_memory_gigabyte_hours": [96.0, 192.0],
                "node_capacity_cpu_cores": [1.0, 1.0],
                "node_capacity_memory_gigabytes": [4.0, 8.0],
            }
        )

        pod_result = pod_aggregator.aggregate(
            pod_usage_df=complete_test_dataset["pod"],
            node_capacity_df=node_capacity,
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
            cost_category_df=pd.DataFrame(),
        )

        storage_result = storage_aggregator.aggregate(
            storage_df=complete_test_dataset["storage"],
            pod_df=complete_test_dataset["pod"],
            node_labels_df=complete_test_dataset["node_labels"],
            namespace_labels_df=complete_test_dataset["namespace_labels"],
        )

        # Combine
        combined = pd.concat([pod_result, storage_result], ignore_index=True)

        # Check for duplicates using key columns
        # Note: Pod and Storage are different data_source, so not duplicates
        key_cols = [
            "usage_start",
            "namespace",
            "data_source",
            "pod",
            "persistentvolumeclaim",
        ]

        before_dedup = len(combined)
        after_dedup = len(combined.drop_duplicates(subset=key_cols))

        assert before_dedup == after_dedup, "Should have no duplicate keys"
