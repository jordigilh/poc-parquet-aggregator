"""
Unit tests for OCP-AWS Aggregator

Tests the OCPAWSAggregator class for orchestrating the complete
OCP-on-AWS cost attribution pipeline.
"""

from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from src.aggregator_ocp_aws import OCPAWSAggregator


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {
        "ocp": {
            "cluster_id": "test-cluster",
            "cluster_alias": "Test Cluster",
            "provider_uuid": "ocp-provider-uuid",
            "report_period_id": 1,
        },
        "aws": {
            "provider_uuid": "aws-provider-uuid",
            "markup_percent": 10.0,
            "cost_entry_bill_id": 1,
        },
        "performance": {"use_streaming": False, "chunk_size": 100000},
        "s3": {
            "endpoint": "http://localhost:9000",
            "bucket": "test-bucket",
            "access_key": "minioadmin",
            "secret_key": "minioadmin",
        },
    }


@pytest.fixture
def enabled_tag_keys():
    """Mock enabled tag keys."""
    return ["openshift_cluster", "openshift_node", "openshift_project", "env", "app"]


class TestOCPAWSAggregator:
    """Test suite for OCPAWSAggregator."""

    def test_initialization(self, mock_config, enabled_tag_keys):
        """Test aggregator initialization."""
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)

        assert aggregator.cluster_id == "test-cluster"
        assert aggregator.cluster_alias == "Test Cluster"
        assert aggregator.provider_uuid == "ocp-provider-uuid"
        assert aggregator.aws_provider_uuid == "aws-provider-uuid"
        assert aggregator.markup_percent == 10.0
        assert len(aggregator.enabled_tag_keys) == 5

        # Verify components are initialized
        assert aggregator.parquet_reader is not None
        assert aggregator.aws_loader is not None
        assert aggregator.resource_matcher is not None
        assert aggregator.tag_matcher is not None
        assert aggregator.disk_calculator is not None
        assert aggregator.cost_attributor is not None

    def test_get_pipeline_summary(self, mock_config, enabled_tag_keys):
        """Test pipeline summary generation."""
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        summary = aggregator.get_pipeline_summary()

        assert summary["cluster_id"] == "test-cluster"
        assert summary["cluster_alias"] == "Test Cluster"
        assert summary["ocp_provider_uuid"] == "ocp-provider-uuid"
        assert summary["aws_provider_uuid"] == "aws-provider-uuid"
        assert summary["markup_percent"] == 10.0
        assert summary["enabled_tag_keys_count"] == 5
        assert summary["streaming_enabled"] is False

    @patch("src.aggregator_ocp_aws.ParquetReader")
    def test_load_ocp_data(self, mock_reader_class, mock_config, enabled_tag_keys):
        """Test OCP data loading."""
        # Setup mock
        mock_reader = Mock()
        mock_reader_class.return_value = mock_reader

        mock_reader.read_pod_usage_line_items.return_value = pd.DataFrame(
            {"namespace": ["default"], "pod": ["test-pod"], "node": ["node-1"]}
        )
        mock_reader.read_storage_usage_line_items.return_value = pd.DataFrame(
            {"namespace": ["default"], "persistentvolumeclaim": ["pvc-1"]}
        )
        mock_reader.read_node_labels_line_items.return_value = pd.DataFrame({"node": ["node-1"], "labels": ["{}"]})
        mock_reader.read_namespace_labels_line_items.return_value = pd.DataFrame(
            {"namespace": ["default"], "labels": ["{}"]}
        )

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.parquet_reader = mock_reader

        # Load data
        result = aggregator._load_ocp_data("2024", "10", "test-cluster")

        # Verify
        assert "pod_usage" in result
        assert "storage_usage" in result
        assert "node_labels" in result
        assert "namespace_labels" in result
        assert len(result["pod_usage"]) == 1
        assert len(result["storage_usage"]) == 1

    @patch("src.aggregator_ocp_aws.AWSDataLoader")
    def test_load_aws_data(self, mock_loader_class, mock_config, enabled_tag_keys):
        """Test AWS data loading."""
        # Setup mock
        mock_loader = Mock()
        mock_loader_class.return_value = mock_loader

        mock_loader.read_aws_line_items_for_matching.return_value = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "vol-456"],
                "lineitem_productcode": ["AmazonEC2", "AmazonEBS"],
                "lineitem_unblendedcost": [10.0, 5.0],
            }
        )

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.aws_loader = mock_loader

        # Load data
        result = aggregator._load_aws_data("2024", "10", "aws-provider-uuid")

        # Verify
        assert len(result) == 2
        assert "lineitem_resourceid" in result.columns
        mock_loader.read_aws_line_items_for_matching.assert_called_once()

    @patch("src.aggregator_ocp_aws.ResourceMatcher")
    def test_match_resources(self, mock_matcher_class, mock_config, enabled_tag_keys):
        """Test resource ID matching."""
        # Setup mock
        mock_matcher = Mock()
        mock_matcher_class.return_value = mock_matcher

        mock_matcher.extract_ocp_resource_ids.return_value = {
            "node_resource_ids": {"i-123"},
            "pv_names": set(),
            "csi_volume_handles": set(),
        }

        aws_df = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "i-456"],
                "lineitem_productcode": ["AmazonEC2", "AmazonEC2"],
            }
        )

        matched_df = aws_df.copy()
        matched_df["resource_id_matched"] = [True, False]
        mock_matcher.match_by_resource_id.return_value = matched_df

        mock_matcher.get_matched_resources_summary.return_value = {
            "total_aws": 2,
            "matched": 1,
            "match_rate": 50.0,
        }

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.resource_matcher = mock_matcher

        ocp_data = {
            "pod_usage": pd.DataFrame({"node": ["node-1"], "resource_id": ["i-123"]}),
            "storage_usage": pd.DataFrame(),
        }

        # Match
        result = aggregator._match_resources(aws_df, ocp_data)

        # Verify
        assert "resource_id_matched" in result.columns
        assert result["resource_id_matched"].sum() == 1
        mock_matcher.extract_ocp_resource_ids.assert_called_once()
        mock_matcher.match_by_resource_id.assert_called_once()

    @patch("src.aggregator_ocp_aws.TagMatcher")
    def test_match_tags(self, mock_matcher_class, mock_config, enabled_tag_keys):
        """Test tag matching."""
        # Setup mock
        mock_matcher = Mock()
        mock_matcher_class.return_value = mock_matcher

        mock_matcher.extract_ocp_tag_values.return_value = {
            "cluster_ids": {"test-cluster"},
            "node_names": {"node-1"},
            "namespaces": {"default"},
        }

        aws_df = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "rds-456"],
                "resourcetags": ['{"openshift_cluster": "test-cluster"}', "{}"],
                "resource_id_matched": [False, False],
            }
        )

        tagged_df = aws_df.copy()
        tagged_df["tag_matched"] = [True, False]
        tagged_df["matched_tag"] = ["openshift_cluster=test-cluster", ""]
        mock_matcher.match_by_tags.return_value = tagged_df

        mock_matcher.get_tag_matching_summary.return_value = {
            "total_aws": 2,
            "tag_matched": 1,
            "by_cluster": 1,
            "by_node": 0,
            "by_namespace": 0,
        }

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.tag_matcher = mock_matcher

        ocp_data = {"pod_usage": pd.DataFrame({"namespace": ["default"], "node": ["node-1"]})}

        # Match
        result = aggregator._match_tags(aws_df, ocp_data, "test-cluster")

        # Verify
        assert "tag_matched" in result.columns
        assert result["tag_matched"].sum() == 1
        mock_matcher.extract_ocp_tag_values.assert_called_once()
        mock_matcher.match_by_tags.assert_called_once()

    @patch("src.aggregator_ocp_aws.DiskCapacityCalculator")
    def test_calculate_disk_capacities_with_volumes(self, mock_calculator_class, mock_config, enabled_tag_keys):
        """Test disk capacity calculation when volumes are present."""
        # Setup mocks
        mock_calculator = Mock()
        mock_calculator_class.return_value = mock_calculator

        matched_aws = pd.DataFrame(
            {
                "lineitem_resourceid": ["vol-123"],
                "lineitem_productcode": ["AmazonEBS"],
                "lineitem_usagetype": ["EBS:VolumeUsage.gp2"],
                "resource_id_matched": [True],
            }
        )

        ocp_storage = pd.DataFrame({"csi_volume_handle": ["vol-123"], "namespace": ["default"]})

        mock_calculator.extract_matched_volumes.return_value = {"vol-123"}

        capacities_df = pd.DataFrame(
            {
                "resource_id": ["vol-123"],
                "capacity": [100],
                "usage_start": ["2024-10-01"],
            }
        )
        mock_calculator.calculate_disk_capacities.return_value = capacities_df

        mock_calculator.get_capacity_summary.return_value = {
            "total_volumes": 1,
            "avg_capacity": 100.0,
        }

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.disk_calculator = mock_calculator

        # Calculate
        result = aggregator._calculate_disk_capacities(matched_aws, ocp_storage, "2024", "10", "aws-provider-uuid")

        # Verify
        assert len(result) == 1
        assert result["capacity"].iloc[0] == 100
        mock_calculator.extract_matched_volumes.assert_called_once()
        mock_calculator.calculate_disk_capacities.assert_called_once()

    @patch("src.aggregator_ocp_aws.DiskCapacityCalculator")
    def test_calculate_disk_capacities_no_volumes(self, mock_calculator_class, mock_config, enabled_tag_keys):
        """Test disk capacity calculation when no volumes are matched."""
        # Setup mock
        mock_calculator = Mock()
        mock_calculator_class.return_value = mock_calculator

        matched_aws = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123"],
                "lineitem_productcode": ["AmazonEC2"],
                "resource_id_matched": [True],
            }
        )

        ocp_storage = pd.DataFrame()

        mock_calculator.extract_matched_volumes.return_value = set()

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.disk_calculator = mock_calculator

        # Calculate
        result = aggregator._calculate_disk_capacities(matched_aws, ocp_storage, "2024", "10", "aws-provider-uuid")

        # Verify
        assert result.empty
        mock_calculator.extract_matched_volumes.assert_called_once()

    @patch("src.aggregator_ocp_aws.CostAttributor")
    def test_attribute_costs(self, mock_attributor_class, mock_config, enabled_tag_keys):
        """Test cost attribution."""
        # Setup mock
        mock_attributor = Mock()
        mock_attributor_class.return_value = mock_attributor

        attributed_df = pd.DataFrame(
            {
                "namespace": ["default"],
                "node": ["node-1"],
                "unblended_cost": [10.0],
                "markup_cost": [1.0],
                "blended_cost": [10.0],
                "markup_cost_blended": [1.0],
            }
        )
        mock_attributor.attribute_compute_costs.return_value = attributed_df

        mock_attributor.get_cost_summary.return_value = {
            "total_unblended_cost": 10.0,
            "total_markup": 1.0,
        }

        # Create aggregator
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)
        aggregator.cost_attributor = mock_attributor

        ocp_data = {
            "pod_usage": pd.DataFrame({"namespace": ["default"], "node": ["node-1"]}),
            "storage_usage": pd.DataFrame(),
        }

        matched_aws = pd.DataFrame({"lineitem_resourceid": ["i-123"], "lineitem_unblendedcost": [10.0]})

        disk_capacities = pd.DataFrame()

        # Attribute
        result = aggregator._attribute_costs(ocp_data, matched_aws, disk_capacities)

        # Verify
        assert len(result) == 1
        assert result["unblended_cost"].iloc[0] == 10.0
        mock_attributor.attribute_compute_costs.assert_called_once()

    def test_format_output(self, mock_config, enabled_tag_keys):
        """Test output formatting."""
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)

        attributed_df = pd.DataFrame(
            {
                "namespace": ["default"],
                "node": ["node-1"],
                "resource_id": ["i-123"],
                "usage_start": ["2024-10-01"],
                "usage_end": ["2024-10-01"],
                "unblended_cost": [10.0],
                "markup_cost": [1.0],
                "blended_cost": [10.0],
                "markup_cost_blended": [1.0],
                "savingsplan_effective_cost": [9.0],
                "markup_cost_savingsplan": [0.9],
                "calculated_amortized_cost": [9.5],
                "markup_cost_amortized": [0.95],
            }
        )

        result = aggregator._format_output(attributed_df, "test-cluster", "Test Cluster", "ocp-provider-uuid")

        # Verify required columns exist
        required_columns = [
            "uuid",
            "report_period_id",
            "cluster_id",
            "cluster_alias",
            "data_source",
            "namespace",
            "node",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "resource_id",
            "usage_start",
            "usage_end",
            "product_code",
            "product_family",
            "instance_type",
            "cost_entry_bill_id",
            "usage_account_id",
            "account_alias_id",
            "availability_zone",
            "region",
            "unit",
            "usage_amount",
            "data_transfer_direction",
            "currency_code",
            "unblended_cost",
            "markup_cost",
            "blended_cost",
            "markup_cost_blended",
            "savingsplan_effective_cost",
            "markup_cost_savingsplan",
            "calculated_amortized_cost",
            "markup_cost_amortized",
            "pod_labels",
            "tags",
            "aws_cost_category",
            "source_uuid",
        ]

        for col in required_columns:
            assert col in result.columns, f"Missing column: {col}"

        # Verify metadata
        assert result["cluster_id"].iloc[0] == "test-cluster"
        assert result["cluster_alias"].iloc[0] == "Test Cluster"
        assert result["source_uuid"].iloc[0] == "ocp-provider-uuid"

        # Verify UUID is generated
        assert result["uuid"].notna().all()
        assert len(result["uuid"].iloc[0]) == 36  # UUID format

        # Verify costs
        assert result["unblended_cost"].iloc[0] == 10.0
        assert result["markup_cost"].iloc[0] == 1.0

    def test_format_output_handles_nan(self, mock_config, enabled_tag_keys):
        """Test output formatting handles NaN values correctly."""
        aggregator = OCPAWSAggregator(mock_config, enabled_tag_keys)

        import numpy as np

        attributed_df = pd.DataFrame(
            {
                "namespace": ["default"],
                "node": [np.nan],  # NaN value
                "resource_id": ["i-123"],
                "usage_start": ["2024-10-01"],
                "usage_end": ["2024-10-01"],
                "unblended_cost": [10.0],
            }
        )

        result = aggregator._format_output(attributed_df, "test-cluster", "Test Cluster", "ocp-provider-uuid")

        # Verify NaN is replaced with empty string
        assert result["node"].iloc[0] == ""

        # Verify default values for missing columns
        assert result["pod_labels"].iloc[0] == "{}"
        assert result["tags"].iloc[0] == "{}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
