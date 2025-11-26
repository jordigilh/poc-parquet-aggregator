"""
Unit tests for Resource Matcher

Tests the ResourceMatcher class for matching AWS resources to OCP resources.
"""

import pandas as pd
import pytest

from src.resource_matcher import ResourceMatcher


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {}


@pytest.fixture
def sample_pod_usage():
    """Sample OCP pod usage data with node resource IDs."""
    return pd.DataFrame(
        {
            "namespace": ["backend", "frontend", "backend"],
            "pod": ["api-1", "web-1", "api-2"],
            "node": [
                "ip-10-0-1-100.ec2.internal",
                "ip-10-0-1-101.ec2.internal",
                "ip-10-0-1-100.ec2.internal",
            ],
            "resource_id": [
                "i-0123456789abcdef0",
                "i-0123456789abcdef1",
                "i-0123456789abcdef0",
            ],
        }
    )


@pytest.fixture
def sample_storage_usage():
    """Sample OCP storage usage data with PV and CSI handles."""
    return pd.DataFrame(
        {
            "namespace": ["backend", "frontend"],
            "persistentvolumeclaim": ["api-pvc", "web-pvc"],
            "persistentvolume": ["pv-ebs-123", "pv-ebs-456"],
            "csi_volume_handle": ["vol-0123456789abcdef", "vol-0123456789abcdeg"],
        }
    )


@pytest.fixture
def sample_aws_data():
    """Sample AWS CUR data."""
    return pd.DataFrame(
        {
            "lineitem_resourceid": [
                "i-0123456789abcdef0",  # EC2 instance (matches node)
                "i-0123456789abcdef1",  # EC2 instance (matches node)
                "vol-0123456789abcdef",  # EBS volume (matches CSI handle)
                "vol-0123456789abcdeg",  # EBS volume (matches CSI handle)
                "i-9999999999999999",  # EC2 instance (no match)
                "vol-9999999999999999",  # EBS volume (no match)
            ],
            "lineitem_productcode": [
                "AmazonEC2",
                "AmazonEC2",
                "AmazonEBS",
                "AmazonEBS",
                "AmazonEC2",
                "AmazonEBS",
            ],
            "lineitem_unblendedcost": [1.0, 1.5, 0.5, 0.6, 2.0, 1.0],
        }
    )


class TestResourceMatcher:
    """Test suite for ResourceMatcher."""

    def test_initialization(self, mock_config):
        """Test resource matcher initialization."""
        matcher = ResourceMatcher(mock_config)
        assert matcher.config == mock_config
        assert matcher.logger is not None

    def test_extract_ocp_resource_ids_complete(
        self, mock_config, sample_pod_usage, sample_storage_usage
    ):
        """Test extraction of OCP resource IDs from complete datasets."""
        matcher = ResourceMatcher(mock_config)

        resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, sample_storage_usage
        )

        # Check node resource IDs
        assert "node_resource_ids" in resource_ids
        assert len(resource_ids["node_resource_ids"]) == 2  # 2 unique node IDs
        assert "i-0123456789abcdef0" in resource_ids["node_resource_ids"]
        assert "i-0123456789abcdef1" in resource_ids["node_resource_ids"]

        # Check PV names
        assert "pv_names" in resource_ids
        assert len(resource_ids["pv_names"]) == 2
        assert "pv-ebs-123" in resource_ids["pv_names"]
        assert "pv-ebs-456" in resource_ids["pv_names"]

        # Check CSI volume handles
        assert "csi_volume_handles" in resource_ids
        assert len(resource_ids["csi_volume_handles"]) == 2
        assert "vol-0123456789abcdef" in resource_ids["csi_volume_handles"]
        assert "vol-0123456789abcdeg" in resource_ids["csi_volume_handles"]

    def test_extract_ocp_resource_ids_empty(self, mock_config):
        """Test extraction from empty DataFrames."""
        matcher = ResourceMatcher(mock_config)

        resource_ids = matcher.extract_ocp_resource_ids(pd.DataFrame(), pd.DataFrame())

        assert len(resource_ids["node_resource_ids"]) == 0
        assert len(resource_ids["pv_names"]) == 0
        assert len(resource_ids["csi_volume_handles"]) == 0

    def test_match_by_resource_id_complete(
        self, mock_config, sample_pod_usage, sample_storage_usage, sample_aws_data
    ):
        """Test complete resource ID matching."""
        matcher = ResourceMatcher(mock_config)

        # Extract OCP resource IDs
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, sample_storage_usage
        )

        # Match AWS resources
        result = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Check that matching columns were added
        assert "resource_id_matched" in result.columns
        assert "matched_resource_id" in result.columns
        assert "match_type" in result.columns

        # Check matching results
        matched_count = result["resource_id_matched"].sum()
        assert matched_count == 4  # 2 EC2 + 2 EBS matched

        # Verify specific matches
        # EC2 instances should match nodes
        ec2_mask = result["lineitem_resourceid"] == "i-0123456789abcdef0"
        assert result.loc[ec2_mask, "resource_id_matched"].iloc[0]
        assert result.loc[ec2_mask, "match_type"].iloc[0] == "node"

        # EBS volumes should match CSI handles
        ebs_mask = result["lineitem_resourceid"] == "vol-0123456789abcdef"
        assert result.loc[ebs_mask, "resource_id_matched"].iloc[0]
        assert result.loc[ebs_mask, "match_type"].iloc[0] == "csi_handle"

        # Unmatched resources
        unmatched_mask = result["lineitem_resourceid"] == "i-9999999999999999"
        assert not result.loc[unmatched_mask, "resource_id_matched"].iloc[0]

    def test_match_by_resource_id_node_only(
        self, mock_config, sample_pod_usage, sample_aws_data
    ):
        """Test matching with only node resource IDs."""
        matcher = ResourceMatcher(mock_config)

        # Extract only node resource IDs
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, pd.DataFrame()  # No storage data
        )

        # Match AWS resources
        result = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Only EC2 instances should match
        matched_count = result["resource_id_matched"].sum()
        assert matched_count == 2  # Only 2 EC2 instances matched

        # All matches should be type 'node'
        matched_rows = result[result["resource_id_matched"]]
        assert (matched_rows["match_type"] == "node").all()

    def test_match_by_resource_id_storage_only(
        self, mock_config, sample_storage_usage, sample_aws_data
    ):
        """Test matching with only storage resource IDs."""
        matcher = ResourceMatcher(mock_config)

        # Extract only storage resource IDs
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            pd.DataFrame(), sample_storage_usage  # No pod data
        )

        # Match AWS resources
        result = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Only EBS volumes should match
        matched_count = result["resource_id_matched"].sum()
        assert matched_count == 2  # Only 2 EBS volumes matched

        # All matches should be type 'csi_handle'
        matched_rows = result[result["resource_id_matched"]]
        assert (matched_rows["match_type"] == "csi_handle").all()

    def test_match_by_resource_id_no_matches(self, mock_config):
        """Test matching with no matching resources."""
        matcher = ResourceMatcher(mock_config)

        # OCP resource IDs that don't match AWS
        ocp_resource_ids = {
            "node_resource_ids": {"i-different"},
            "pv_names": {"pv-different"},
            "csi_volume_handles": {"vol-different"},
        }

        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["i-0123456789abcdef0", "vol-0123456789abcdef"],
                "lineitem_productcode": ["AmazonEC2", "AmazonEBS"],
            }
        )

        result = matcher.match_by_resource_id(aws_data, ocp_resource_ids)

        # No resources should match
        matched_count = result["resource_id_matched"].sum()
        assert matched_count == 0

    def test_match_by_resource_id_empty_aws(self, mock_config):
        """Test matching with empty AWS DataFrame."""
        matcher = ResourceMatcher(mock_config)

        ocp_resource_ids = {
            "node_resource_ids": {"i-0123"},
            "pv_names": set(),
            "csi_volume_handles": set(),
        }

        result = matcher.match_by_resource_id(pd.DataFrame(), ocp_resource_ids)

        assert result.empty

    def test_match_by_resource_id_missing_column(self, mock_config):
        """Test matching with AWS DataFrame missing required column."""
        matcher = ResourceMatcher(mock_config)

        ocp_resource_ids = {
            "node_resource_ids": {"i-0123"},
            "pv_names": set(),
            "csi_volume_handles": set(),
        }

        # AWS DataFrame without lineitem_resourceid
        aws_data = pd.DataFrame({"lineitem_productcode": ["AmazonEC2"]})

        with pytest.raises(ValueError, match="missing 'lineitem_resourceid'"):
            matcher.match_by_resource_id(aws_data, ocp_resource_ids)

    def test_get_matched_resources_summary(
        self, mock_config, sample_pod_usage, sample_storage_usage, sample_aws_data
    ):
        """Test generation of matching summary."""
        matcher = ResourceMatcher(mock_config)

        # Extract and match
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, sample_storage_usage
        )
        matched_aws = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Get summary
        summary = matcher.get_matched_resources_summary(matched_aws)

        assert summary["total_resources"] == 6
        assert summary["matched"] == 4
        assert summary["unmatched"] == 2
        assert summary["match_rate"] == pytest.approx(66.67, rel=0.1)

        # Check by match type
        assert "by_match_type" in summary
        assert summary["by_match_type"]["node"] == 2
        assert summary["by_match_type"]["csi_handle"] == 2

    def test_get_matched_resources_summary_no_matching(self, mock_config):
        """Test summary with DataFrame that hasn't been matched."""
        matcher = ResourceMatcher(mock_config)

        aws_data = pd.DataFrame(
            {"lineitem_resourceid": ["i-0123"], "lineitem_productcode": ["AmazonEC2"]}
        )

        summary = matcher.get_matched_resources_summary(aws_data)

        assert summary["status"] == "not_matched"

    def test_validate_matching_results_pass(
        self, mock_config, sample_pod_usage, sample_storage_usage, sample_aws_data
    ):
        """Test validation of matching results (pass case)."""
        matcher = ResourceMatcher(mock_config)

        # Extract and match
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, sample_storage_usage
        )
        matched_aws = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Validation should pass with 50% match rate
        assert matcher.validate_matching_results(
            matched_aws, expected_match_rate_min=0.5
        )

    def test_validate_matching_results_fail(
        self, mock_config, sample_pod_usage, sample_storage_usage, sample_aws_data
    ):
        """Test validation of matching results (fail case)."""
        matcher = ResourceMatcher(mock_config)

        # Extract and match
        ocp_resource_ids = matcher.extract_ocp_resource_ids(
            sample_pod_usage, sample_storage_usage
        )
        matched_aws = matcher.match_by_resource_id(sample_aws_data, ocp_resource_ids)

        # Validation should fail with 90% minimum requirement
        with pytest.raises(ValueError, match="match rate.*below minimum"):
            matcher.validate_matching_results(matched_aws, expected_match_rate_min=0.9)

    def test_validate_matching_results_missing_column(self, mock_config):
        """Test validation with DataFrame missing matching column."""
        matcher = ResourceMatcher(mock_config)

        aws_data = pd.DataFrame({"lineitem_resourceid": ["i-0123"]})

        with pytest.raises(ValueError, match="missing 'resource_id_matched'"):
            matcher.validate_matching_results(aws_data)

    def test_suffix_matching_behavior(self, mock_config):
        """Test suffix matching behavior for various AWS resource ID formats."""
        matcher = ResourceMatcher(mock_config)

        # OCP resource IDs
        ocp_resource_ids = {
            "node_resource_ids": {"i-abc123"},
            "pv_names": set(),
            "csi_volume_handles": {"vol-xyz789"},
        }

        # AWS resource IDs with various formats
        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": [
                    "i-abc123",  # Exact match
                    "arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",  # Suffix match
                    "vol-xyz789",  # Exact match
                    "i-different",  # No match
                ],
                "lineitem_productcode": [
                    "AmazonEC2",
                    "AmazonEC2",
                    "AmazonEBS",
                    "AmazonEC2",
                ],
            }
        )

        result = matcher.match_by_resource_id(aws_data, ocp_resource_ids)

        # First 3 should match, last should not
        assert result.iloc[0]["resource_id_matched"]  # Exact match
        assert result.iloc[1]["resource_id_matched"]  # Suffix match (ARN)
        assert result.iloc[2]["resource_id_matched"]  # CSI handle match
        assert not result.iloc[3]["resource_id_matched"]  # No match


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
