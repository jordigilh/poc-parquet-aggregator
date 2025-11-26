"""
Unit tests for Tag Matcher

Tests the TagMatcher class for matching AWS resources to OCP by tags.
"""

import json

import pandas as pd
import pytest

from src.tag_matcher import TagMatcher


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {}


@pytest.fixture
def sample_pod_usage():
    """Sample OCP pod usage data."""
    return pd.DataFrame(
        {
            "namespace": ["backend", "frontend", "backend"],
            "pod": ["api-1", "web-1", "api-2"],
            "node": [
                "ip-10-0-1-100.ec2.internal",
                "ip-10-0-1-101.ec2.internal",
                "ip-10-0-1-100.ec2.internal",
            ],
        }
    )


@pytest.fixture
def sample_aws_data_with_tags():
    """Sample AWS CUR data with OpenShift tags."""
    return pd.DataFrame(
        {
            "lineitem_resourceid": [
                "db-instance-1",  # RDS with cluster tag
                "cache-node-1",  # ElastiCache with node tag
                "nat-gateway-1",  # NAT gateway with namespace tag
                "vol-no-tags",  # EBS without tags
                "i-wrong-cluster",  # EC2 with wrong cluster tag
            ],
            "lineitem_productcode": [
                "AmazonRDS",
                "AmazonElastiCache",
                "AmazonVPC",
                "AmazonEBS",
                "AmazonEC2",
            ],
            "resourcetags": [
                json.dumps({"openshift_cluster": "my-cluster", "env": "prod"}),
                json.dumps({"openshift_node": "ip-10-0-1-100.ec2.internal", "app": "cache"}),
                json.dumps({"openshift_project": "backend", "tier": "network"}),
                json.dumps({}),
                json.dumps({"openshift_cluster": "different-cluster"}),
            ],
            "resource_id_matched": [False, False, False, False, False],
        }
    )


@pytest.fixture
def sample_mixed_matching_data():
    """Sample data with mixed resource ID and tag matching."""
    return pd.DataFrame(
        {
            "lineitem_resourceid": [
                "i-0123456789abcdef0",  # Matched by resource ID
                "db-instance-1",  # Should match by tag
                "vol-xyz",  # No match
            ],
            "lineitem_productcode": ["AmazonEC2", "AmazonRDS", "AmazonEBS"],
            "resourcetags": [
                json.dumps({"env": "prod"}),
                json.dumps({"openshift_cluster": "my-cluster"}),
                json.dumps({}),
            ],
            "resource_id_matched": [True, False, False],
        }
    )


class TestTagMatcher:
    """Test suite for TagMatcher."""

    def test_initialization(self, mock_config):
        """Test tag matcher initialization."""
        matcher = TagMatcher(mock_config)
        assert matcher.config == mock_config
        assert matcher.logger is not None
        assert matcher.TAG_OPENSHIFT_CLUSTER == "openshift_cluster"
        assert matcher.TAG_OPENSHIFT_NODE == "openshift_node"
        assert matcher.TAG_OPENSHIFT_PROJECT == "openshift_project"

    def test_extract_ocp_tag_values(self, mock_config, sample_pod_usage):
        """Test extraction of OCP tag values."""
        matcher = TagMatcher(mock_config)

        tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        # Check cluster IDs
        assert "cluster_ids" in tag_values
        assert "my-cluster" in tag_values["cluster_ids"]

        # Check node names
        assert "node_names" in tag_values
        assert len(tag_values["node_names"]) == 2  # 2 unique nodes
        assert "ip-10-0-1-100.ec2.internal" in tag_values["node_names"]
        assert "ip-10-0-1-101.ec2.internal" in tag_values["node_names"]

        # Check namespaces
        assert "namespaces" in tag_values
        assert len(tag_values["namespaces"]) == 2  # 2 unique namespaces
        assert "backend" in tag_values["namespaces"]
        assert "frontend" in tag_values["namespaces"]

    def test_extract_ocp_tag_values_empty(self, mock_config):
        """Test extraction from empty DataFrame."""
        matcher = TagMatcher(mock_config)

        tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=pd.DataFrame())

        assert "my-cluster" in tag_values["cluster_ids"]
        assert len(tag_values["node_names"]) == 0
        assert len(tag_values["namespaces"]) == 0

    def test_parse_aws_tags_valid(self, mock_config):
        """Test parsing valid AWS tags."""
        matcher = TagMatcher(mock_config)

        tags_json = json.dumps({"openshift_cluster": "my-cluster", "env": "prod", "app": "backend"})

        tags = matcher.parse_aws_tags(tags_json)

        assert tags["openshift_cluster"] == "my-cluster"
        assert tags["env"] == "prod"
        assert tags["app"] == "backend"

    def test_parse_aws_tags_empty(self, mock_config):
        """Test parsing empty tags."""
        matcher = TagMatcher(mock_config)

        assert matcher.parse_aws_tags("{}") == {}
        assert matcher.parse_aws_tags("") == {}
        assert matcher.parse_aws_tags(None) == {}
        assert matcher.parse_aws_tags(pd.NA) == {}

    def test_parse_aws_tags_invalid(self, mock_config):
        """Test parsing invalid JSON."""
        matcher = TagMatcher(mock_config)

        assert matcher.parse_aws_tags("invalid json") == {}
        assert matcher.parse_aws_tags("{broken") == {}

    def test_filter_by_enabled_keys(self, mock_config):
        """Test filtering tags by enabled keys."""
        matcher = TagMatcher(mock_config)

        aws_tags = {
            "openshift_cluster": "my-cluster",
            "env": "prod",
            "app": "backend",
            "tier": "web",
        }

        enabled_keys = {"openshift_cluster", "env", "app"}

        filtered = matcher.filter_by_enabled_keys(aws_tags, enabled_keys)

        assert "openshift_cluster" in filtered
        assert "env" in filtered
        assert "app" in filtered
        assert "tier" not in filtered  # Not enabled

    def test_filter_by_enabled_keys_empty(self, mock_config):
        """Test filtering with no enabled keys."""
        matcher = TagMatcher(mock_config)

        aws_tags = {"openshift_cluster": "my-cluster", "env": "prod"}

        # If enabled_keys is None or empty, allow all
        filtered = matcher.filter_by_enabled_keys(aws_tags, None)
        assert filtered == aws_tags

        filtered = matcher.filter_by_enabled_keys(aws_tags, set())
        assert filtered == aws_tags

    def test_match_by_tags_cluster(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test matching by openshift_cluster tag."""
        matcher = TagMatcher(mock_config)

        # Extract OCP tag values
        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        # Match by tags
        result = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Check that tag matching columns were added
        assert "tag_matched" in result.columns
        assert "matched_tag" in result.columns
        assert "matched_ocp_cluster" in result.columns

        # First resource (RDS) should match by cluster tag
        rds_row = result.iloc[0]
        assert rds_row["tag_matched"]
        assert rds_row["matched_tag"] == "openshift_cluster=my-cluster"
        assert rds_row["matched_ocp_cluster"] == "my-cluster"

    def test_match_by_tags_node(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test matching by openshift_node tag."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        result = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Second resource (ElastiCache) should match by node tag
        cache_row = result.iloc[1]
        assert cache_row["tag_matched"]
        assert cache_row["matched_tag"] == "openshift_node=ip-10-0-1-100.ec2.internal"
        assert cache_row["matched_ocp_node"] == "ip-10-0-1-100.ec2.internal"

    def test_match_by_tags_namespace(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test matching by openshift_project tag."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        result = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Third resource (NAT gateway) should match by namespace tag
        nat_row = result.iloc[2]
        assert nat_row["tag_matched"]
        assert nat_row["matched_tag"] == "openshift_project=backend"
        assert nat_row["matched_ocp_namespace"] == "backend"

    def test_match_by_tags_no_match(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test resources that don't match."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        result = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Fourth resource (EBS without tags) should not match
        ebs_row = result.iloc[3]
        assert not ebs_row["tag_matched"]

        # Fifth resource (wrong cluster) should not match
        ec2_row = result.iloc[4]
        assert not ec2_row["tag_matched"]

    def test_match_by_tags_skip_resource_id_matched(self, mock_config, sample_pod_usage, sample_mixed_matching_data):
        """Test that resources already matched by resource ID are skipped."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        result = matcher.match_by_tags(sample_mixed_matching_data, ocp_tag_values)

        # First resource already matched by resource ID, should not be tag matched
        ec2_row = result.iloc[0]
        assert ec2_row["resource_id_matched"]
        assert not ec2_row["tag_matched"]

        # Second resource should match by tag
        rds_row = result.iloc[1]
        assert not rds_row["resource_id_matched"]
        assert rds_row["tag_matched"]

        # Third resource should not match
        vol_row = result.iloc[2]
        assert not vol_row["resource_id_matched"]
        assert not vol_row["tag_matched"]

    def test_match_by_tags_with_enabled_keys(self, mock_config, sample_pod_usage):
        """Test matching with enabled key filtering."""
        matcher = TagMatcher(mock_config)

        # Create AWS data with tags
        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["db-1", "db-2"],
                "lineitem_productcode": ["AmazonRDS", "AmazonRDS"],
                "resourcetags": [
                    json.dumps({"openshift_cluster": "my-cluster", "env": "prod"}),
                    json.dumps({"openshift_cluster": "my-cluster", "env": "prod"}),
                ],
                "resource_id_matched": [False, False],
            }
        )

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        # Only enable openshift_cluster key
        enabled_keys = {"openshift_cluster"}

        result = matcher.match_by_tags(aws_data, ocp_tag_values, enabled_keys)

        # Both should match because openshift_cluster is enabled
        assert result["tag_matched"].sum() == 2

    def test_match_by_tags_empty_aws(self, mock_config):
        """Test matching with empty AWS DataFrame."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = {
            "cluster_ids": {"my-cluster"},
            "node_names": set(),
            "namespaces": set(),
        }

        result = matcher.match_by_tags(pd.DataFrame(), ocp_tag_values)

        assert result.empty

    def test_match_by_tags_missing_column(self, mock_config):
        """Test matching with DataFrame missing required column."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = {
            "cluster_ids": {"my-cluster"},
            "node_names": set(),
            "namespaces": set(),
        }

        # AWS DataFrame without resourcetags
        aws_data = pd.DataFrame({"lineitem_resourceid": ["i-123"]})

        with pytest.raises(ValueError, match="missing 'resourcetags'"):
            matcher.match_by_tags(aws_data, ocp_tag_values)

    def test_get_tag_matching_summary(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test generation of tag matching summary."""
        matcher = TagMatcher(mock_config)

        # Extract and match
        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)
        matched_aws = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Get summary
        summary = matcher.get_tag_matching_summary(matched_aws)

        assert summary["total_resources"] == 5
        assert summary["tag_matched"] == 3  # cluster + node + namespace
        assert summary["matched_by_cluster"] == 1
        assert summary["matched_by_node"] == 1
        assert summary["matched_by_namespace"] == 1

    def test_get_tag_matching_summary_no_matching(self, mock_config):
        """Test summary with DataFrame that hasn't been matched."""
        matcher = TagMatcher(mock_config)

        aws_data = pd.DataFrame({"lineitem_resourceid": ["i-123"], "resourcetags": [json.dumps({})]})

        summary = matcher.get_tag_matching_summary(aws_data)

        assert summary["status"] == "not_matched"

    def test_validate_tag_matching_results_pass(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test validation of tag matching results (pass case)."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)
        matched_aws = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Validation should pass with 50% match rate
        assert matcher.validate_tag_matching_results(matched_aws, expected_match_rate_min=0.5)

    def test_validate_tag_matching_results_fail(self, mock_config, sample_pod_usage, sample_aws_data_with_tags):
        """Test validation of tag matching results (fail case)."""
        matcher = TagMatcher(mock_config)

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)
        matched_aws = matcher.match_by_tags(sample_aws_data_with_tags, ocp_tag_values)

        # Validation should fail with 90% minimum requirement
        with pytest.raises(ValueError, match="match rate.*below minimum"):
            matcher.validate_tag_matching_results(matched_aws, expected_match_rate_min=0.9)

    def test_validate_tag_matching_results_missing_column(self, mock_config):
        """Test validation with DataFrame missing matching column."""
        matcher = TagMatcher(mock_config)

        aws_data = pd.DataFrame({"lineitem_resourceid": ["i-123"]})

        with pytest.raises(ValueError, match="missing 'tag_matched'"):
            matcher.validate_tag_matching_results(aws_data)

    def test_tag_priority(self, mock_config, sample_pod_usage):
        """Test that cluster tag takes priority over node/namespace tags."""
        matcher = TagMatcher(mock_config)

        # Resource with multiple OpenShift tags
        aws_data = pd.DataFrame(
            {
                "lineitem_resourceid": ["multi-tag-resource"],
                "lineitem_productcode": ["AmazonRDS"],
                "resourcetags": [
                    json.dumps(
                        {
                            "openshift_cluster": "my-cluster",
                            "openshift_node": "ip-10-0-1-100.ec2.internal",
                            "openshift_project": "backend",
                        }
                    )
                ],
                "resource_id_matched": [False],
            }
        )

        ocp_tag_values = matcher.extract_ocp_tag_values(cluster_id="my-cluster", pod_usage_df=sample_pod_usage)

        result = matcher.match_by_tags(aws_data, ocp_tag_values)

        # Should match by cluster tag (highest priority)
        row = result.iloc[0]
        assert row["tag_matched"]
        assert row["matched_tag"] == "openshift_cluster=my-cluster"
        assert row["matched_ocp_cluster"] == "my-cluster"
        # Node and namespace should not be set (cluster took priority)
        assert pd.isna(row["matched_ocp_node"])
        assert pd.isna(row["matched_ocp_namespace"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
