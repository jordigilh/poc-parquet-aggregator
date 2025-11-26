"""
Unit tests for Cost Attributor

Tests the CostAttributor class for attributing AWS costs to OCP pods.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, date
from src.cost_attributor import CostAttributor


@pytest.fixture
def mock_config():
    """Mock configuration for testing with default weighted distribution."""
    return {
        'cost': {
            'markup': 0.10,  # 10% markup
            'distribution': {
                'method': 'weighted',
                'weights': {
                    'aws': {'cpu_weight': 0.73, 'memory_weight': 0.27},
                    'default': {'cpu_weight': 0.73, 'memory_weight': 0.27}
                }
            }
        }
    }


@pytest.fixture
def mock_config_cpu_only():
    """Mock configuration for CPU-only distribution."""
    return {
        'cost': {
            'markup': 0.10,
            'distribution': {
                'method': 'cpu',
                'weights': {
                    'default': {'cpu_weight': 0.73, 'memory_weight': 0.27}
                }
            }
        }
    }


@pytest.fixture
def mock_config_memory_only():
    """Mock configuration for memory-only distribution."""
    return {
        'cost': {
            'markup': 0.10,
            'distribution': {
                'method': 'memory',
                'weights': {
                    'default': {'cpu_weight': 0.73, 'memory_weight': 0.27}
                }
            }
        }
    }


@pytest.fixture
def sample_ocp_pod_usage():
    """Sample OCP pod usage data."""
    return pd.DataFrame({
        'namespace': ['backend', 'frontend', 'backend'],
        'pod': ['api-1', 'web-1', 'api-2'],
        'node': ['ip-10-0-1-100.ec2.internal', 'ip-10-0-1-101.ec2.internal', 'ip-10-0-1-100.ec2.internal'],
        'resource_id': ['i-0123456789abcdef0', 'i-0123456789abcdef1', 'i-0123456789abcdef0'],
        'interval_start': pd.to_datetime(['2025-10-01 00:00:00', '2025-10-01 00:00:00', '2025-10-01 00:00:00']),
        'pod_usage_cpu_core_hours': [1.5, 2.0, 1.0],
        'pod_usage_memory_gigabyte_hours': [4.0, 8.0, 2.0],
        'node_capacity_cpu_core_hours': [4.0, 8.0, 4.0],
        'node_capacity_memory_gigabyte_hours': [16.0, 32.0, 16.0]
    })


@pytest.fixture
def sample_aws_matched():
    """Sample AWS matched resources."""
    return pd.DataFrame({
        'lineitem_resourceid': ['i-0123456789abcdef0', 'i-0123456789abcdef1'],
        'lineitem_productcode': ['AmazonEC2', 'AmazonEC2'],
        'lineitem_usagestartdate': pd.to_datetime(['2025-10-01', '2025-10-01']),
        'lineitem_unblendedcost': [10.0, 20.0],
        'lineitem_blendedcost': [9.5, 19.0],
        'savingsplan_savingsplaneffectivecost': [9.0, 18.0],
        'pricing_publicondemandcost': [12.0, 24.0],
        'resource_id_matched': [True, True],
        'matched_resource_id': ['i-0123456789abcdef0', 'i-0123456789abcdef1'],
        'tag_matched': [False, False]
    })


@pytest.fixture
def sample_merged_data():
    """Sample merged OCP + AWS data."""
    return pd.DataFrame({
        'namespace': ['backend', 'frontend'],
        'pod': ['api-1', 'web-1'],
        'node': ['ip-10-0-1-100.ec2.internal', 'ip-10-0-1-101.ec2.internal'],
        'resource_id': ['i-0123456789abcdef0', 'i-0123456789abcdef1'],
        'usage_date': [date(2025, 10, 1), date(2025, 10, 1)],
        'pod_usage_cpu_core_hours': [1.5, 2.0],
        'pod_usage_memory_gigabyte_hours': [4.0, 8.0],
        'node_capacity_cpu_core_hours': [4.0, 8.0],
        'node_capacity_memory_gigabyte_hours': [16.0, 32.0],
        'lineitem_resourceid': ['i-0123456789abcdef0', 'i-0123456789abcdef1'],
        'lineitem_unblendedcost': [10.0, 20.0],
        'lineitem_blendedcost': [9.5, 19.0],
        'savingsplan_savingsplaneffectivecost': [9.0, 18.0],
        'pricing_publicondemandcost': [12.0, 24.0]
    })


class TestCostAttributor:
    """Test suite for CostAttributor."""

    def test_initialization(self, mock_config):
        """Test cost attributor initialization."""
        attributor = CostAttributor(mock_config)
        assert attributor.config == mock_config
        assert attributor.logger is not None
        assert attributor.markup == 0.10
        assert attributor.distribution_method == 'weighted'
        assert attributor.cpu_weight == 0.73
        assert attributor.memory_weight == 0.27

    def test_initialization_default_markup(self):
        """Test initialization with default markup."""
        attributor = CostAttributor({})
        assert attributor.markup == 0.10  # Default 10%
        assert attributor.distribution_method == 'cpu'  # Default: Trino-compatible
        assert attributor.cpu_weight == 0.73  # Default weight
        assert attributor.memory_weight == 0.27  # Default weight

    def test_initialization_per_provider_weights(self):
        """Test that per-provider weights are loaded correctly."""
        config = {
            'cost': {
                'distribution': {
                    'method': 'weighted',
                    'weights': {
                        'aws': {'cpu_weight': 0.73, 'memory_weight': 0.27},
                        'gcp': {'cpu_weight': 0.72, 'memory_weight': 0.28},
                        'azure': {'cpu_weight': 0.73, 'memory_weight': 0.27},
                        'default': {'cpu_weight': 0.70, 'memory_weight': 0.30}
                    }
                }
            }
        }

        # Test AWS provider
        aws_attributor = CostAttributor(config, provider='aws')
        assert aws_attributor.cpu_weight == 0.73
        assert aws_attributor.memory_weight == 0.27

        # Test GCP provider
        gcp_attributor = CostAttributor(config, provider='gcp')
        assert gcp_attributor.cpu_weight == 0.72
        assert gcp_attributor.memory_weight == 0.28

        # Test unknown provider (should use default)
        unknown_attributor = CostAttributor(config, provider='unknown')
        assert unknown_attributor.cpu_weight == 0.70
        assert unknown_attributor.memory_weight == 0.30

    def test_join_ocp_with_aws_by_resource_id(
        self, mock_config, sample_ocp_pod_usage, sample_aws_matched
    ):
        """Test joining OCP with AWS by resource ID."""
        attributor = CostAttributor(mock_config)

        result = attributor.join_ocp_with_aws(
            sample_ocp_pod_usage,
            sample_aws_matched
        )

        # Should have successful joins
        assert not result.empty

        # Check that expected columns are present
        assert 'namespace' in result.columns
        assert 'pod' in result.columns
        assert 'lineitem_resourceid' in result.columns
        assert 'lineitem_unblendedcost' in result.columns

        # Check join worked correctly
        assert len(result) > 0

    def test_join_ocp_with_aws_empty_ocp(self, mock_config, sample_aws_matched):
        """Test joining with empty OCP DataFrame."""
        attributor = CostAttributor(mock_config)

        result = attributor.join_ocp_with_aws(
            pd.DataFrame(),
            sample_aws_matched
        )

        assert result.empty

    def test_join_ocp_with_aws_empty_aws(self, mock_config, sample_ocp_pod_usage):
        """Test joining with empty AWS DataFrame."""
        attributor = CostAttributor(mock_config)

        result = attributor.join_ocp_with_aws(
            sample_ocp_pod_usage,
            pd.DataFrame()
        )

        assert result.empty

    def test_calculate_attribution_ratio_cpu_dominant(self, mock_config):
        """Test attribution ratio calculation when CPU ratio is higher (weighted method)."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [3.0],  # 75% of capacity
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [4.0],  # 25% of capacity
            'node_capacity_memory_gigabyte_hours': [16.0]
        })

        result = attributor.calculate_attribution_ratio(df)

        assert 'attribution_ratio' in result.columns
        assert 'cpu_ratio' in result.columns
        assert 'memory_ratio' in result.columns

        assert result['cpu_ratio'].iloc[0] == pytest.approx(0.75)
        assert result['memory_ratio'].iloc[0] == pytest.approx(0.25)
        # Weighted: 0.75 * 0.73 + 0.25 * 0.27 = 0.5475 + 0.0675 = 0.615
        assert result['attribution_ratio'].iloc[0] == pytest.approx(0.615)

    def test_calculate_attribution_ratio_memory_dominant(self, mock_config):
        """Test attribution ratio calculation when memory ratio is higher (weighted method)."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [1.0],  # 25% of capacity
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [12.0],  # 75% of capacity
            'node_capacity_memory_gigabyte_hours': [16.0]
        })

        result = attributor.calculate_attribution_ratio(df)

        assert result['memory_ratio'].iloc[0] == pytest.approx(0.75)
        assert result['cpu_ratio'].iloc[0] == pytest.approx(0.25)
        # Weighted: 0.25 * 0.73 + 0.75 * 0.27 = 0.1825 + 0.2025 = 0.385
        assert result['attribution_ratio'].iloc[0] == pytest.approx(0.385)

    def test_calculate_attribution_ratio_capped_at_100(self, mock_config):
        """Test that individual ratios are capped at 100% before weighting."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [5.0],  # 125% (over capacity) -> capped to 100%
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [8.0],  # 50%
            'node_capacity_memory_gigabyte_hours': [16.0]
        })

        result = attributor.calculate_attribution_ratio(df)

        # CPU capped at 1.0, memory at 0.5
        # Weighted: 1.0 * 0.73 + 0.5 * 0.27 = 0.73 + 0.135 = 0.865
        assert result['cpu_ratio'].iloc[0] == pytest.approx(1.0)
        assert result['memory_ratio'].iloc[0] == pytest.approx(0.5)
        assert result['attribution_ratio'].iloc[0] == pytest.approx(0.865)

    def test_calculate_attribution_ratio_zero_capacity(self, mock_config):
        """Test attribution ratio with zero capacity (should handle gracefully)."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [1.0],
            'node_capacity_cpu_core_hours': [0.0],  # Zero capacity
            'pod_usage_memory_gigabyte_hours': [4.0],
            'node_capacity_memory_gigabyte_hours': [0.0]  # Zero capacity
        })

        result = attributor.calculate_attribution_ratio(df)

        # Should handle division by zero gracefully
        assert 'attribution_ratio' in result.columns
        assert result['attribution_ratio'].iloc[0] == 0.0  # Filled with 0

    def test_attribute_costs_unblended(self, mock_config, sample_merged_data):
        """Test unblended cost attribution with weighted method."""
        attributor = CostAttributor(mock_config)

        result = attributor.attribute_costs(sample_merged_data)

        assert 'unblended_cost' in result.columns
        assert 'markup_cost' in result.columns

        # First row: cpu_ratio = 1.5/4.0 = 0.375, memory_ratio = 4.0/16.0 = 0.25
        # Weighted: 0.375 * 0.73 + 0.25 * 0.27 = 0.27375 + 0.0675 = 0.34125
        # Cost = 10.0 * 0.34125 = 3.4125
        # Markup = 3.4125 * 0.10 = 0.34125
        expected_ratio = 0.375 * 0.73 + 0.25 * 0.27
        expected_cost = 10.0 * expected_ratio
        expected_markup = expected_cost * 0.10

        assert result['unblended_cost'].iloc[0] == pytest.approx(expected_cost, rel=0.01)
        assert result['markup_cost'].iloc[0] == pytest.approx(expected_markup, rel=0.01)

    def test_attribute_costs_all_types(self, mock_config, sample_merged_data):
        """Test that all 4 cost types are attributed."""
        attributor = CostAttributor(mock_config)

        result = attributor.attribute_costs(sample_merged_data)

        # Check all cost columns exist
        assert 'unblended_cost' in result.columns
        assert 'blended_cost' in result.columns
        assert 'savingsplan_effective_cost' in result.columns
        assert 'calculated_amortized_cost' in result.columns

        # Check all markup columns exist
        assert 'markup_cost' in result.columns
        assert 'markup_cost_blended' in result.columns
        assert 'markup_cost_savingsplan' in result.columns
        assert 'markup_cost_amortized' in result.columns

        # Verify they have non-zero values
        assert result['unblended_cost'].sum() > 0
        assert result['blended_cost'].sum() > 0
        assert result['savingsplan_effective_cost'].sum() > 0
        assert result['calculated_amortized_cost'].sum() > 0

    def test_attribute_costs_markup_calculation(self, mock_config):
        """Test that markup is calculated correctly."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [2.0],
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [8.0],
            'node_capacity_memory_gigabyte_hours': [16.0],
            'lineitem_unblendedcost': [100.0],
            'lineitem_blendedcost': [0.0],
            'savingsplan_savingsplaneffectivecost': [0.0],
            'pricing_publicondemandcost': [0.0]
        })

        result = attributor.attribute_costs(df)

        # Attribution ratio = max(2/4, 8/16) = max(0.5, 0.5) = 0.5
        # Cost = 100.0 * 0.5 = 50.0
        # Markup = 50.0 * 0.10 = 5.0
        assert result['unblended_cost'].iloc[0] == pytest.approx(50.0)
        assert result['markup_cost'].iloc[0] == pytest.approx(5.0)

    def test_attribute_compute_costs_complete(
        self, mock_config, sample_ocp_pod_usage, sample_aws_matched
    ):
        """Test complete compute cost attribution workflow."""
        attributor = CostAttributor(mock_config)

        result = attributor.attribute_compute_costs(
            sample_ocp_pod_usage,
            sample_aws_matched
        )

        # Should have attributed costs
        if not result.empty:
            assert 'unblended_cost' in result.columns
            assert 'attribution_ratio' in result.columns
            assert 'namespace' in result.columns
            assert 'pod' in result.columns

    def test_attribute_compute_costs_empty_inputs(self, mock_config):
        """Test complete workflow with empty inputs."""
        attributor = CostAttributor(mock_config)

        result = attributor.attribute_compute_costs(
            pd.DataFrame(),
            pd.DataFrame()
        )

        assert result.empty

    def test_get_cost_summary(self, mock_config, sample_merged_data):
        """Test cost summary generation."""
        attributor = CostAttributor(mock_config)

        attributed = attributor.attribute_costs(sample_merged_data)
        summary = attributor.get_cost_summary(attributed)

        assert 'total_rows' in summary
        assert 'unique_pods' in summary
        assert 'unique_namespaces' in summary
        assert 'costs' in summary

        # Check cost totals
        assert 'unblended_cost' in summary['costs']
        assert summary['costs']['unblended_cost'] > 0

    def test_get_cost_summary_empty(self, mock_config):
        """Test cost summary with empty DataFrame."""
        attributor = CostAttributor(mock_config)

        summary = attributor.get_cost_summary(pd.DataFrame())

        assert summary['status'] == 'empty'

    def test_weighted_attribution(self, mock_config):
        """Test weighted attribution method (industry standard)."""
        attributor = CostAttributor(mock_config)

        # Scenario: High CPU, low memory
        df_cpu_high = pd.DataFrame({
            'pod_usage_cpu_core_hours': [3.5],  # 87.5% CPU
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [2.0],  # 12.5% memory
            'node_capacity_memory_gigabyte_hours': [16.0],
            'lineitem_unblendedcost': [100.0],
            'lineitem_blendedcost': [0.0],
            'savingsplan_savingsplaneffectivecost': [0.0],
            'pricing_publicondemandcost': [0.0]
        })

        result = attributor.attribute_costs(df_cpu_high)

        # Weighted: 0.875 * 0.73 + 0.125 * 0.27 = 0.63875 + 0.03375 = 0.6725
        expected_ratio = 0.875 * 0.73 + 0.125 * 0.27
        expected_cost = 100.0 * expected_ratio
        assert result['unblended_cost'].iloc[0] == pytest.approx(expected_cost, rel=0.01)

    def test_cpu_only_attribution(self, mock_config_cpu_only):
        """Test CPU-only attribution method (Trino-compatible)."""
        attributor = CostAttributor(mock_config_cpu_only)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [3.5],  # 87.5% CPU
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [2.0],  # 12.5% memory
            'node_capacity_memory_gigabyte_hours': [16.0],
            'lineitem_unblendedcost': [100.0],
            'lineitem_blendedcost': [0.0],
            'savingsplan_savingsplaneffectivecost': [0.0],
            'pricing_publicondemandcost': [0.0]
        })

        result = attributor.attribute_costs(df)

        # CPU-only: uses only CPU ratio (87.5%)
        expected_cost = 100.0 * 0.875
        assert result['unblended_cost'].iloc[0] == pytest.approx(expected_cost, rel=0.01)

    def test_memory_only_attribution(self, mock_config_memory_only):
        """Test memory-only attribution method."""
        attributor = CostAttributor(mock_config_memory_only)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [3.5],  # 87.5% CPU
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [2.0],  # 12.5% memory
            'node_capacity_memory_gigabyte_hours': [16.0],
            'lineitem_unblendedcost': [100.0],
            'lineitem_blendedcost': [0.0],
            'savingsplan_savingsplaneffectivecost': [0.0],
            'pricing_publicondemandcost': [0.0]
        })

        result = attributor.attribute_costs(df)

        # Memory-only: uses only memory ratio (12.5%)
        expected_cost = 100.0 * 0.125
        assert result['unblended_cost'].iloc[0] == pytest.approx(expected_cost, rel=0.01)

    def test_multiple_pods_same_node(self, mock_config):
        """Test attribution for multiple pods on the same node."""
        attributor = CostAttributor(mock_config)

        # 3 pods on same node, each using 25% of capacity
        df = pd.DataFrame({
            'pod': ['pod-1', 'pod-2', 'pod-3'],
            'namespace': ['ns-1', 'ns-1', 'ns-2'],
            'pod_usage_cpu_core_hours': [1.0, 1.0, 1.0],  # Each 25%
            'node_capacity_cpu_core_hours': [4.0, 4.0, 4.0],
            'pod_usage_memory_gigabyte_hours': [4.0, 4.0, 4.0],  # Each 25%
            'node_capacity_memory_gigabyte_hours': [16.0, 16.0, 16.0],
            'lineitem_unblendedcost': [100.0, 100.0, 100.0],  # Same node cost
            'lineitem_blendedcost': [0.0, 0.0, 0.0],
            'savingsplan_savingsplaneffectivecost': [0.0, 0.0, 0.0],
            'pricing_publicondemandcost': [0.0, 0.0, 0.0]
        })

        result = attributor.attribute_costs(df)

        # Each pod should get 25% of the cost
        expected_cost_per_pod = 100.0 * 0.25
        for cost in result['unblended_cost']:
            assert cost == pytest.approx(expected_cost_per_pod, rel=0.01)

    def test_zero_cost_handling(self, mock_config):
        """Test handling of zero costs."""
        attributor = CostAttributor(mock_config)

        df = pd.DataFrame({
            'pod_usage_cpu_core_hours': [2.0],
            'node_capacity_cpu_core_hours': [4.0],
            'pod_usage_memory_gigabyte_hours': [8.0],
            'node_capacity_memory_gigabyte_hours': [16.0],
            'lineitem_unblendedcost': [0.0],  # Zero cost
            'lineitem_blendedcost': [0.0],
            'savingsplan_savingsplaneffectivecost': [0.0],
            'pricing_publicondemandcost': [0.0]
        })

        result = attributor.attribute_costs(df)

        # All costs should be zero
        assert result['unblended_cost'].iloc[0] == 0.0
        assert result['markup_cost'].iloc[0] == 0.0


class TestStorageCostAttribution:
    """Tests for storage cost attribution (Scenario 18, 19, 22 fixes)."""

    def test_storage_suffix_matching(self, mock_config):
        """
        TDD TEST: Storage cost attribution should use SUFFIX matching, not exact matching.

        SCENARIO 18 FIX: OCP has csi_volume_handle='shared-disk-001'
        AWS has resource_id='vol-shared-disk-001' (with vol- prefix added by nise)

        Trino SQL: substr(resource_id, -length(csi_volume_handle)) = csi_volume_handle
        """
        attributor = CostAttributor(mock_config)

        # OCP storage data: csi_volume_handle='shared-disk-001'
        ocp_storage_df = pd.DataFrame({
            'interval_start': ['2025-10-01 00:00:00'] * 2,
            'namespace': ['project-alpha', 'project-bravo'],
            'persistentvolume': ['pv-alpha', 'pv-bravo'],
            'persistentvolumeclaim': ['pvc-alpha', 'pvc-bravo'],
            'csi_volume_handle': ['shared-disk-001', 'shared-disk-001'],  # Same CSI handle
            'persistentvolumeclaim_capacity_byte_seconds': [
                40 * 1024**3 * 3600,  # 40 GB for alpha
                30 * 1024**3 * 3600   # 30 GB for bravo
            ],
            'cluster_id': ['cluster-alpha', 'cluster-bravo']
        })

        # AWS EBS data: resource_id='vol-shared-disk-001' (with vol- prefix!)
        matched_aws_df = pd.DataFrame({
            'lineitem_resourceid': ['vol-shared-disk-001'] * 24,  # 24 hours
            'lineitem_productcode': ['AmazonEC2'] * 24,
            'lineitem_usagetype': ['EBS:VolumeUsage.gp3'] * 24,
            'lineitem_usagestartdate': pd.date_range('2025-10-01', periods=24, freq='h'),
            'lineitem_unblendedcost': [1.277 / 24] * 24,  # ~$0.0532/hr
            'lineitem_blendedcost': [1.277 / 24] * 24,
            'lineitem_unblendedrate': [0.08 / 744] * 24,  # Rate per GB-hr
            'savingsplan_savingsplaneffectivecost': [0.0] * 24,
            'lineitem_normalizedusageamount': [100.0] * 24,
            'lineitem_usageamount': [100.0] * 24
        })

        # Disk capacities (calculated by DiskCapacityCalculator)
        disk_capacities = pd.DataFrame({
            'resource_id': ['vol-shared-disk-001'],  # AWS resource ID (with prefix)
            'capacity': [100],  # 100 GB disk
            'usage_start': [date(2025, 10, 1)]
        })

        result = attributor.attribute_storage_costs(ocp_storage_df, matched_aws_df, disk_capacities)

        # Should NOT be empty - suffix matching should work
        assert not result.empty, "Storage attribution failed - suffix matching not working"

        # Should have 4 rows: 2 regular namespaces + 2 "Storage unattributed" (one per cluster)
        # This is correct behavior: 100 GB disk with 70 GB claimed = 30 GB unattributed
        assert len(result) == 4, f"Expected 4 rows (2 regular + 2 unattributed), got {len(result)}"

        # Regular namespace cost should be proportional to PVC size
        # Alpha: (40/100) * $1.277 = $0.5108
        # Bravo: (30/100) * $1.277 = $0.3831
        regular_namespaces = result[result['namespace'] != 'Storage unattributed']
        regular_cost = regular_namespaces['unblended_cost'].sum()
        expected_regular = (40/100 + 30/100) * 1.277  # $0.8939
        assert regular_cost == pytest.approx(expected_regular, rel=0.1), \
            f"Expected regular cost ~${expected_regular:.2f}, got ${regular_cost:.2f}"

        # Total cost should equal full disk cost (including unattributed)
        total_cost = result['unblended_cost'].sum()
        expected_total = 1.277  # Full disk cost
        assert total_cost == pytest.approx(expected_total, rel=0.1), \
            f"Expected total cost ~${expected_total:.2f}, got ${total_cost:.2f}"

    def test_non_csi_tag_based_storage_attribution(self, mock_config):
        """
        TDD TEST: Non-CSI storage (EBS tagged with openshift_project) should be attributed.

        SCENARIO 19 FIX: When there's NO OCP storage data (no CSI handles), but EBS volumes
        are tagged with openshift_project, the POC should attribute those costs to the
        tagged namespace.

        Trino SQL: json_query(aws.tags, '$.openshift_project') = ocp.namespace
        """
        attributor = CostAttributor(mock_config)

        # NO OCP storage data - simulating non-CSI environment
        ocp_storage_df = pd.DataFrame()  # Empty - no CSI handles

        # AWS EBS data: tagged with openshift_project but NO CSI handle match
        # These are "tag-matched" storage volumes
        matched_aws_df = pd.DataFrame({
            'lineitem_resourceid': ['vol-legacy-001'] * 24,
            'lineitem_productcode': ['AmazonEC2'] * 24,
            'lineitem_usagetype': ['EBS:VolumeUsage.gp3'] * 24,
            'lineitem_usagestartdate': pd.date_range('2025-10-01', periods=24, freq='h'),
            'lineitem_unblendedcost': [0.6383 / 24] * 24,  # ~$0.0266/hr for 50GB
            'lineitem_blendedcost': [0.6383 / 24] * 24,
            'lineitem_unblendedrate': [0.08 / 744] * 24,
            'savingsplan_savingsplaneffectivecost': [0.0] * 24,
            'lineitem_normalizedusageamount': [50.0] * 24,
            'lineitem_usageamount': [50.0] * 24,
            # KEY: Tagged with openshift_project for tag-based attribution
            'resourcetags': ['{"openshift_cluster": "my-cluster", "openshift_project": "legacy-app"}'] * 24,
            'tag_matched': [True] * 24,  # Tag matcher found this
            'matched_ocp_namespace': ['legacy-app'] * 24,  # The namespace from openshift_project tag
        })

        # No disk capacities (not needed for tag-based attribution)
        disk_capacities = pd.DataFrame()

        # Call attribute_tag_matched_storage - NEW METHOD for tag-based attribution
        result = attributor.attribute_tag_matched_storage(matched_aws_df)

        # EXPECTED BEHAVIOR:
        # - Result should NOT be empty
        # - Result should have costs attributed to 'legacy-app' namespace
        # - Total cost should be ~$0.6383

        assert not result.empty, "Tag-matched storage attribution should return results"

        assert 'legacy-app' in result['namespace'].values, \
            "Tag-matched storage should be attributed to 'legacy-app' namespace"

        total_cost = result['unblended_cost'].sum()
        assert total_cost == pytest.approx(0.6383, rel=0.1), \
            f"Expected ~$0.64, got ${total_cost:.2f}"

    def test_storage_unattributed_multi_cluster_shared_disk(self, mock_config):
        """
        TDD TEST: Shared disk with unused capacity should create 'Storage unattributed' records.

        SCENARIO 18 FIX: When a 100 GB disk is shared across clusters but only 70 GB
        is claimed by PVCs (40 GB + 30 GB), the remaining 30 GB cost should go to
        'Storage unattributed' namespace.

        Trino SQL: Remaining capacity cost is attributed to 'Storage unattributed'

        Expected:
        - Total disk cost: $1.277/day (100 GB at $0.383/GB/month)
        - Alpha PVC (40 GB): (40/100) * $1.277 = $0.5108
        - Bravo PVC (30 GB): (30/100) * $1.277 = $0.3831
        - Unattributed (30 GB): (30/100) * $1.277 = $0.3831
        """
        attributor = CostAttributor(mock_config)

        # OCP storage data: Two clusters sharing ONE disk via same CSI handle
        # Use persistentvolumeclaim_capacity_gigabyte as the capacity column
        ocp_storage_df = pd.DataFrame({
            'cluster_id': ['cluster-alpha', 'cluster-bravo'],
            'namespace': ['project-alpha', 'project-bravo'],
            'persistentvolume': ['shared-storage-alpha', 'shared-storage-bravo'],
            'csi_volume_handle': ['shared-disk-001', 'shared-disk-001'],  # SAME handle
            'persistentvolumeclaim': ['pvc-alpha', 'pvc-bravo'],
            'persistentvolumeclaim_capacity_gigabyte': [40, 30],  # 40 + 30 = 70 GB claimed of 100 GB disk
            'interval_start': pd.to_datetime(['2025-10-01', '2025-10-01']),
        })

        # AWS EBS: Single 100 GB disk with $1.277/day cost
        matched_aws_df = pd.DataFrame({
            'lineitem_resourceid': ['vol-shared-disk-001'] * 24,
            'lineitem_productcode': ['AmazonEC2'] * 24,
            'lineitem_usagetype': ['EBS:VolumeUsage.gp3'] * 24,
            'lineitem_usagestartdate': pd.date_range('2025-10-01', periods=24, freq='h'),
            'lineitem_unblendedcost': [1.277 / 24] * 24,  # $1.277/day split across 24 hours
            'lineitem_blendedcost': [1.277 / 24] * 24,
            'lineitem_unblendedrate': [0.08 / 744] * 24,
            'savingsplan_savingsplaneffectivecost': [0.0] * 24,
            'lineitem_normalizedusageamount': [100.0] * 24,  # 100 GB disk
            'lineitem_usageamount': [100.0] * 24,
            'resource_id_matched': [True] * 24,
            'matched_resource_id': ['shared-disk-001'] * 24,
        })

        # Disk capacities from calculator - resource_id must match AFTER EBS aggregation
        # (the code renames lineitem_resourceid to resource_id, so use the full AWS resource ID)
        disk_capacities = pd.DataFrame({
            'resource_id': ['vol-shared-disk-001'],  # Must match AWS resource_id (with vol- prefix)
            'capacity': [100],  # 100 GB disk
            'usage_date': [date(2025, 10, 1)]  # Must be date object
        })

        result = attributor.attribute_storage_costs(ocp_storage_df, matched_aws_df, disk_capacities)

        # EXPECTED: Should have attributed costs PLUS "Storage unattributed" records
        assert not result.empty, "Storage attribution should return results"

        # Check that we have both regular namespaces AND 'Storage unattributed'
        namespaces = result['namespace'].unique().tolist()

        # Regular namespaces should have their proportional costs
        regular_cost = result[result['namespace'] != 'Storage unattributed']['unblended_cost'].sum()
        expected_regular = (40/100 + 30/100) * 1.277  # 70% of disk = $0.8939
        assert regular_cost == pytest.approx(expected_regular, rel=0.1), \
            f"Regular namespace cost should be ~${expected_regular:.2f}, got ${regular_cost:.2f}"

        # Storage unattributed should have the remaining 30% cost
        assert 'Storage unattributed' in namespaces, \
            "Should have 'Storage unattributed' namespace for unused disk capacity"

        unattributed_cost = result[result['namespace'] == 'Storage unattributed']['unblended_cost'].sum()
        expected_unattributed = (30/100) * 1.277  # 30% of disk = $0.3831
        assert unattributed_cost == pytest.approx(expected_unattributed, rel=0.1), \
            f"Unattributed storage cost should be ~${expected_unattributed:.2f}, got ${unattributed_cost:.2f}"

        # Total should equal full disk cost
        total_cost = result['unblended_cost'].sum()
        assert total_cost == pytest.approx(1.277, rel=0.1), \
            f"Total storage cost should be ~$1.28, got ${total_cost:.2f}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

