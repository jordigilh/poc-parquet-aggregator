"""
Shared pytest fixtures for all tests.

Provides common test data and configurations.
"""

from datetime import date, datetime

import pandas as pd
import pytest


@pytest.fixture
def standard_config():
    """Standard configuration for all tests."""
    return {
        "ocp": {
            "cluster_id": "test-cluster",
            "provider_uuid": "test-provider-uuid",
            "cluster_alias": "Test Cluster",
            "report_period_id": 1,
            "year": "2025",
            "month": "10",
            "parquet_path_pod": "data/org123/OCP/source={provider_uuid}/year={year}/month={month}/*/openshift_pod_usage_line_items",
            "parquet_path_storage": "data/org123/OCP/source={provider_uuid}/year={year}/month={month}/*/openshift_storage_usage_line_items",
            "parquet_path_storage_usage_daily": "data/org123/OCP/source={provider_uuid}/year={year}/month={month}/*/openshift_storage_usage_line_items_daily",
            "parquet_path_node_labels": "data/org123/OCP/source={provider_uuid}/year={year}/month={month}/*/openshift_node_labels_line_items",
            "parquet_path_namespace_labels": "data/org123/OCP/source={provider_uuid}/year={year}/month={month}/*/openshift_namespace_labels_line_items",
        },
        "s3": {
            "endpoint": "http://localhost:9000",
            "bucket": "test-bucket",
            "access_key": "testkey",
            "secret_key": "testsecret",
            "region": "us-east-1",
            "use_ssl": False,
            "verify_ssl": False,
        },
        "performance": {
            "use_arrow_compute": False,
            "use_streaming": False,
            "chunk_size": 50000,
            "column_filtering": False,
            "delete_intermediate_dfs": False,
            "gc_after_aggregation": False,
        },
    }


@pytest.fixture
def sample_pod_usage():
    """Sample pod usage data for testing."""
    return pd.DataFrame(
        {
            "interval_start": pd.to_datetime(["2025-10-01 00:00:00"] * 3),
            "namespace": ["ns1", "ns1", "ns2"],
            "pod": ["pod1", "pod2", "pod3"],
            "node": ["node1", "node1", "node2"],
            "resource_id": ["i-111", "i-111", "i-222"],
            "pod_labels": ['{"app": "web"}', '{"app": "api"}', '{"app": "db"}'],
            "pod_usage_cpu_core_seconds": [3600.0, 7200.0, 14400.0],
            "pod_request_cpu_core_seconds": [7200.0, 14400.0, 28800.0],
            "pod_limit_cpu_core_seconds": [14400.0, 28800.0, 57600.0],
            "pod_usage_memory_byte_seconds": [1e12, 2e12, 4e12],
            "pod_request_memory_byte_seconds": [2e12, 4e12, 8e12],
            "pod_limit_memory_byte_seconds": [4e12, 8e12, 16e12],
            "node_capacity_cpu_core_seconds": [86400.0, 86400.0, 172800.0],
            "node_capacity_memory_byte_seconds": [1e14, 1e14, 2e14],
        }
    )


@pytest.fixture
def sample_storage_usage():
    """Sample storage usage data for testing."""
    return pd.DataFrame(
        {
            "interval_start": pd.to_datetime(["2025-10-01 00:00:00"] * 2),
            "namespace": ["ns1", "ns2"],
            "pod": ["pod1", "pod3"],
            "persistentvolumeclaim": ["pvc1", "pvc2"],
            "persistentvolume": ["pv1", "pv2"],
            "storageclass": ["gp2", "io1"],
            "persistentvolumeclaim_capacity_byte_seconds": [1e12, 2e12],
            "volume_request_storage_byte_seconds": [8e11, 1.6e12],
            "persistentvolumeclaim_usage_byte_seconds": [5e11, 1e12],
            "volume_labels": ['{"storage": "web"}', '{"storage": "db"}'],
            "csi_volume_handle": ["vol-111", "vol-222"],
        }
    )


@pytest.fixture
def sample_node_labels():
    """Sample node labels for testing."""
    return pd.DataFrame(
        {
            "usage_start": [date(2025, 10, 1), date(2025, 10, 1)],
            "node": ["node1", "node2"],
            "node_labels": [
                '{"zone": "us-east-1a", "instance_type": "m5.large"}',
                '{"zone": "us-east-1b", "instance_type": "m5.xlarge"}',
            ],
        }
    )


@pytest.fixture
def sample_namespace_labels():
    """Sample namespace labels for testing."""
    return pd.DataFrame(
        {
            "usage_start": [date(2025, 10, 1), date(2025, 10, 1)],
            "namespace": ["ns1", "ns2"],
            "namespace_labels": [
                '{"team": "platform", "env": "prod"}',
                '{"team": "data", "env": "prod"}',
            ],
        }
    )


@pytest.fixture
def sample_node_capacity():
    """Sample node capacity data for testing."""
    return pd.DataFrame(
        {
            "usage_start": [date(2025, 10, 1), date(2025, 10, 1)],
            "node": ["node1", "node2"],
            "node_capacity_cpu_core_hours": [24.0, 48.0],
            "node_capacity_memory_gigabyte_hours": [96.0, 192.0],
            "node_capacity_cpu_cores": [1.0, 2.0],
            "node_capacity_memory_gigabytes": [4.0, 8.0],
        }
    )
