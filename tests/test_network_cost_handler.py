"""
Unit tests for Network Cost Handler

Tests the NetworkCostHandler class for handling network/data transfer costs.
"""

import numpy as np
import pandas as pd
import pytest

from src.network_cost_handler import NetworkCostHandler


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {"aws": {"markup": 10.0}}  # 10% markup


@pytest.fixture
def sample_aws_with_network():
    """Sample AWS data with network costs."""
    return pd.DataFrame(
        {
            "lineitem_resourceid": [
                "i-node1-suffix",  # Network cost (IN)
                "i-node2-suffix",  # Network cost (OUT)
                "i-node1-suffix",  # Regular compute cost
                "vol-12345",  # Storage cost (no network)
            ],
            "lineitem_productcode": [
                "AmazonEC2",
                "AmazonEC2",
                "AmazonEC2",
                "AmazonEBS",
            ],
            "product_productfamily": [
                "Data Transfer",
                "Data Transfer",
                "Compute Instance",
                "Storage",
            ],
            "data_transfer_direction": ["IN", "OUT", None, None],
            "lineitem_unblendedcost": [10.0, 20.0, 50.0, 15.0],
            "lineitem_blendedcost": [9.5, 19.0, 48.0, 14.5],
            "lineitem_usageamount": [100.0, 200.0, 24.0, 50.0],
            "savingsplan_savingsplaneffectivecost": [9.0, 18.0, 45.0, 14.0],
            "calculated_amortized_cost": [9.2, 18.5, 46.0, 14.2],
            "resource_id_matched": [True, True, True, False],
        }
    )


@pytest.fixture
def sample_ocp_pod_usage():
    """Sample OCP pod usage data."""
    return pd.DataFrame(
        {
            "namespace": ["backend", "frontend", "backend"],
            "pod": ["api-1", "web-1", "api-2"],
            "node": ["node1", "node2", "node1"],
            "resource_id": ["node1-suffix", "node2-suffix", "node1-suffix"],
            "pod_usage_cpu_core_hours": [10.0, 20.0, 15.0],
            "node_capacity_cpu_core_hours": [24.0, 24.0, 24.0],
        }
    )


class TestNetworkCostHandler:
    """Test suite for NetworkCostHandler."""

    def test_initialization(self, mock_config):
        """Test network cost handler initialization."""
        handler = NetworkCostHandler(mock_config)
        assert handler.config == mock_config
        assert handler.logger is not None
        assert handler.markup_percent == 10.0
        assert handler.NETWORK_NAMESPACE == "Network unattributed"

    def test_initialization_default_markup(self):
        """Test initialization with default markup."""
        config = {}
        handler = NetworkCostHandler(config)
        assert handler.markup_percent == 0.0

    def test_filter_network_costs_basic(self, mock_config, sample_aws_with_network):
        """Test basic filtering of network costs."""
        handler = NetworkCostHandler(mock_config)

        non_network, network = handler.filter_network_costs(sample_aws_with_network)

        # Verify separation
        assert len(network) == 2  # 2 network records (IN + OUT)
        assert len(non_network) == 2  # 2 non-network records

        # Verify network records have direction
        assert all(network["data_transfer_direction"].notna())
        assert "IN" in network["data_transfer_direction"].values
        assert "OUT" in network["data_transfer_direction"].values

        # Verify non-network records have no direction
        assert all(non_network["data_transfer_direction"].isna())

    def test_filter_network_costs_empty_dataframe(self, mock_config):
        """Test filtering with empty DataFrame."""
        handler = NetworkCostHandler(mock_config)

        empty_df = pd.DataFrame()
        non_network, network = handler.filter_network_costs(empty_df)

        assert len(non_network) == 0
        assert len(network) == 0

    def test_filter_network_costs_missing_column(self, mock_config):
        """Test filtering when data_transfer_direction column is missing."""
        handler = NetworkCostHandler(mock_config)

        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "i-456"],
                "lineitem_unblendedcost": [10.0, 20.0],
            }
        )

        non_network, network = handler.filter_network_costs(aws_data)

        # Should treat all as non-network
        assert len(non_network) == 2
        assert len(network) == 0

    def test_filter_network_costs_all_network(self, mock_config):
        """Test filtering when all costs are network."""
        handler = NetworkCostHandler(mock_config)

        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "i-456"],
                "data_transfer_direction": ["IN", "OUT"],
                "lineitem_unblendedcost": [10.0, 20.0],
            }
        )

        non_network, network = handler.filter_network_costs(aws_data)

        assert len(non_network) == 0
        assert len(network) == 2

    def test_filter_network_costs_no_network(self, mock_config):
        """Test filtering when no costs are network."""
        handler = NetworkCostHandler(mock_config)

        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-123", "i-456"],
                "data_transfer_direction": [None, None],
                "lineitem_unblendedcost": [10.0, 20.0],
            }
        )

        non_network, network = handler.filter_network_costs(aws_data)

        assert len(non_network) == 2
        assert len(network) == 0

    def test_attribute_network_costs_basic(
        self, mock_config, sample_aws_with_network, sample_ocp_pod_usage
    ):
        """Test basic network cost attribution."""
        handler = NetworkCostHandler(mock_config)

        # Filter to get network costs
        _, network_df = handler.filter_network_costs(sample_aws_with_network)

        # Attribute to nodes
        result = handler.attribute_network_costs(network_df, sample_ocp_pod_usage)

        # Verify namespace assignment
        assert all(result["namespace"] == handler.NETWORK_NAMESPACE)

        # Verify node assignment
        assert "node1" in result["node"].values
        assert "node2" in result["node"].values

        # Verify direction is preserved
        assert "IN" in result["data_transfer_direction"].values
        assert "OUT" in result["data_transfer_direction"].values

        # Verify costs are aggregated (output uses clean column names)
        assert "unblended_cost" in result.columns
        assert result["unblended_cost"].sum() == 30.0  # 10 + 20

    def test_attribute_network_costs_empty_network(
        self, mock_config, sample_ocp_pod_usage
    ):
        """Test attribution with no network costs."""
        handler = NetworkCostHandler(mock_config)

        empty_network = pd.DataFrame()
        result = handler.attribute_network_costs(empty_network, sample_ocp_pod_usage)

        assert len(result) == 0

    def test_attribute_network_costs_no_matching_nodes(self, mock_config):
        """Test attribution when network costs don't match any OCP nodes."""
        handler = NetworkCostHandler(mock_config)

        network_df = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-unmatched-resource"],
                "data_transfer_direction": ["IN"],
                "lineitem_unblendedcost": [10.0],
                "lineitem_blendedcost": [9.5],
                "lineitem_usageamount": [100.0],
            }
        )

        ocp_data = pd.DataFrame(
            {"node": ["node1"], "resource_id": ["different-suffix"]}
        )

        result = handler.attribute_network_costs(network_df, ocp_data)

        # Should return empty DataFrame when no matches
        assert len(result) == 0

    def test_attribute_network_costs_missing_aws_columns(
        self, mock_config, sample_ocp_pod_usage
    ):
        """Test attribution with missing required AWS columns."""
        handler = NetworkCostHandler(mock_config)

        incomplete_network = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-node1-suffix"],
                "data_transfer_direction": ["IN"]
                # Missing cost columns
            }
        )

        with pytest.raises(ValueError, match="missing required columns"):
            handler.attribute_network_costs(incomplete_network, sample_ocp_pod_usage)

    def test_attribute_network_costs_missing_ocp_columns(self, mock_config):
        """Test attribution with missing required OCP columns."""
        handler = NetworkCostHandler(mock_config)

        network_df = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-node1-suffix"],
                "data_transfer_direction": ["IN"],
                "lineitem_unblendedcost": [10.0],
                "lineitem_blendedcost": [9.5],
                "lineitem_usageamount": [100.0],
            }
        )

        incomplete_ocp = pd.DataFrame(
            {
                "node": ["node1"]
                # Missing resource_id column
            }
        )

        with pytest.raises(ValueError, match="missing required columns"):
            handler.attribute_network_costs(network_df, incomplete_ocp)

    def test_attribute_network_costs_markup_calculation(
        self, mock_config, sample_ocp_pod_usage
    ):
        """Test that markup is correctly calculated for network costs."""
        handler = NetworkCostHandler(mock_config)

        network_df = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-node1-suffix"],
                "data_transfer_direction": ["IN"],
                "lineitem_unblendedcost": [100.0],
                "lineitem_blendedcost": [95.0],
                "lineitem_usageamount": [1000.0],
                "savingsplan_savingsplaneffectivecost": [90.0],
                "calculated_amortized_cost": [92.0],
            }
        )

        result = handler.attribute_network_costs(network_df, sample_ocp_pod_usage)

        # Verify markup calculations (10% markup)
        assert result["markup_cost"].iloc[0] == pytest.approx(10.0)  # 10% of 100
        assert result["markup_cost_blended"].iloc[0] == pytest.approx(9.5)  # 10% of 95
        assert result["markup_cost_savingsplan"].iloc[0] == pytest.approx(
            9.0
        )  # 10% of 90
        assert result["markup_cost_amortized"].iloc[0] == pytest.approx(
            9.2
        )  # 10% of 92

    def test_attribute_network_costs_grouping_by_node_and_direction(self, mock_config):
        """Test that network costs are grouped by node and direction."""
        handler = NetworkCostHandler(mock_config)

        # Multiple records for same node and direction (should aggregate)
        network_df = pd.DataFrame(
            {
                "lineitem_resourceid": [
                    "i-node1-suffix",
                    "i-node1-suffix",
                    "i-node2-suffix",
                ],
                "data_transfer_direction": ["IN", "IN", "OUT"],
                "lineitem_unblendedcost": [10.0, 15.0, 20.0],
                "lineitem_blendedcost": [9.5, 14.5, 19.0],
                "lineitem_usageamount": [100.0, 150.0, 200.0],
            }
        )

        ocp_data = pd.DataFrame(
            {
                "node": ["node1", "node2"],
                "resource_id": ["node1-suffix", "node2-suffix"],
            }
        )

        result = handler.attribute_network_costs(network_df, ocp_data)

        # Should have 2 grouped records (node1+IN aggregated, node2+OUT)
        assert len(result) == 2

        # Verify node1+IN aggregation (output uses clean column names)
        node1_in = result[
            (result["node"] == "node1") & (result["data_transfer_direction"] == "IN")
        ]
        assert len(node1_in) == 1
        assert node1_in["unblended_cost"].iloc[0] == 25.0  # 10 + 15
        assert node1_in["usage_amount"].iloc[0] == 250.0  # 100 + 150

        # Verify node2+OUT
        node2_out = result[
            (result["node"] == "node2") & (result["data_transfer_direction"] == "OUT")
        ]
        assert len(node2_out) == 1
        assert node2_out["unblended_cost"].iloc[0] == 20.0

    def test_get_network_summary_basic(self, mock_config):
        """Test basic network summary generation."""
        handler = NetworkCostHandler(mock_config)

        # Use output column names (unblended_cost, usage_amount)
        network_df = pd.DataFrame(
            {
                "node": ["node1", "node2", "node1"],
                "namespace": [handler.NETWORK_NAMESPACE] * 3,
                "data_transfer_direction": ["IN", "OUT", "IN"],
                "unblended_cost": [10.0, 20.0, 15.0],
                "usage_amount": [100.0, 200.0, 150.0],
            }
        )

        summary = handler.get_network_summary(network_df)

        assert summary["total_records"] == 3
        assert summary["unique_nodes"] == 2
        assert summary["direction_breakdown"] == {"IN": 2, "OUT": 1}
        assert summary["total_cost_unblended"] == 45.0
        assert summary["total_usage_amount"] == 450.0

    def test_get_network_summary_empty(self, mock_config):
        """Test summary with empty DataFrame."""
        handler = NetworkCostHandler(mock_config)

        empty_df = pd.DataFrame()
        summary = handler.get_network_summary(empty_df)

        assert summary["status"] == "no_network_costs"

    def test_get_network_summary_missing_columns(self, mock_config):
        """Test summary with missing columns."""
        handler = NetworkCostHandler(mock_config)

        incomplete_df = pd.DataFrame(
            {
                "node": ["node1"]
                # Missing other columns
            }
        )

        summary = handler.get_network_summary(incomplete_df)

        # Should handle gracefully
        assert "total_records" in summary
        assert summary["unique_nodes"] == 1
        assert summary["direction_breakdown"] == {}

    def test_suffix_matching_logic(self, mock_config):
        """Test that suffix matching works correctly for resource IDs."""
        handler = NetworkCostHandler(mock_config)

        network_df = pd.DataFrame(
            {
                "lineitem_resourceid": [
                    "arn:aws:ec2:us-east-1:123456789012:instance/i-node1-suffix",  # Full ARN
                    "i-node2-suffix",  # Short form
                ],
                "data_transfer_direction": ["IN", "OUT"],
                "lineitem_unblendedcost": [10.0, 20.0],
                "lineitem_blendedcost": [9.5, 19.0],
                "lineitem_usageamount": [100.0, 200.0],
            }
        )

        ocp_data = pd.DataFrame(
            {
                "node": ["node1", "node2"],
                "resource_id": ["node1-suffix", "node2-suffix"],
            }
        )

        result = handler.attribute_network_costs(network_df, ocp_data)

        # Both should match (suffix matching)
        assert len(result) == 2
        assert "node1" in result["node"].values
        assert "node2" in result["node"].values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
