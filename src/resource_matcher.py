"""
Resource ID Matcher for OCP-on-AWS

Matches AWS resources (EC2 instances, EBS volumes) to OCP resources (nodes, PVs)
by resource ID suffix matching.

Key Matching Logic:
1. **EC2 → Nodes**: Match AWS instance ID to OCP node resource_id
   - AWS: i-0123456789abcdef0
   - OCP Node: resource_id=i-0123456789abcdef0
   - Match: EXACT

2. **EBS → PVs**: Match AWS volume ID to OCP PV CSI handle
   - AWS: vol-0123456789abcdef
   - OCP PV: csi_volume_handle=vol-0123456789abcdef
   - Match: SUFFIX or CONTAINS

This is the first step in the OCP-on-AWS matching pipeline, followed by tag matching.

Complexity: HIGH (8/10)
"""

from typing import Dict, List, Set, Tuple

import pandas as pd

from .utils import PerformanceTimer, get_logger


class ResourceMatcher:
    """
    Match AWS resources to OCP resources by resource ID.

    This class implements the core resource ID matching algorithm that
    matches AWS EC2 instances to OCP nodes and AWS EBS volumes to OCP PVs.
    """

    def __init__(self, config: Dict):
        """
        Initialize resource matcher.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger("resource_matcher")

        self.logger.info("Initialized resource matcher")

    def extract_ocp_resource_ids(
        self, pod_usage_df: pd.DataFrame, storage_usage_df: pd.DataFrame
    ) -> Dict[str, Set[str]]:
        """
        Extract all unique OCP resource IDs for matching.

        Args:
            pod_usage_df: OCP pod usage DataFrame
            storage_usage_df: OCP storage usage DataFrame

        Returns:
            Dictionary with sets of:
                - 'node_resource_ids': Set of node resource IDs
                - 'pv_names': Set of PV names
                - 'csi_volume_handles': Set of CSI volume handles
        """
        with PerformanceTimer("Extract OCP resource IDs", self.logger):
            resource_ids = {
                "node_resource_ids": set(),
                "pv_names": set(),
                "csi_volume_handles": set(),
            }

            # Extract node resource IDs from pod usage
            if not pod_usage_df.empty and "resource_id" in pod_usage_df.columns:
                node_ids = pod_usage_df["resource_id"].dropna().unique()
                resource_ids["node_resource_ids"] = set(node_ids)
                self.logger.info(f"Extracted {len(resource_ids['node_resource_ids'])} unique node resource IDs")

            # Extract PV names and CSI volume handles from storage usage
            if not storage_usage_df.empty:
                if "persistentvolume" in storage_usage_df.columns:
                    pv_names = storage_usage_df["persistentvolume"].dropna().unique()
                    resource_ids["pv_names"] = set(pv_names)
                    self.logger.info(f"Extracted {len(resource_ids['pv_names'])} unique PV names")

                if "csi_volume_handle" in storage_usage_df.columns:
                    csi_handles = storage_usage_df["csi_volume_handle"].dropna().unique()
                    resource_ids["csi_volume_handles"] = set(csi_handles)
                    self.logger.info(f"Extracted {len(resource_ids['csi_volume_handles'])} unique CSI volume handles")

            total_resources = (
                len(resource_ids["node_resource_ids"])
                + len(resource_ids["pv_names"])
                + len(resource_ids["csi_volume_handles"])
            )

            self.logger.info(
                "✓ Extracted OCP resource IDs",
                nodes=len(resource_ids["node_resource_ids"]),
                pvs=len(resource_ids["pv_names"]),
                csi_handles=len(resource_ids["csi_volume_handles"]),
                total=total_resources,
            )

            return resource_ids

    def match_by_resource_id(self, aws_df: pd.DataFrame, ocp_resource_ids: Dict[str, Set[str]]) -> pd.DataFrame:
        """
        Match AWS resources to OCP by resource ID suffix matching.

        This implements the core matching logic:

        1. **EC2 → Nodes**: Match by exact suffix
           - AWS: 'i-0123456789abcdef0'
           - OCP: resource_id='i-0123456789abcdef0'
           - Match: aws_id.endswith(ocp_id)

        2. **EBS → PVs**: Match by suffix or contains
           - AWS: 'vol-0123456789abcdef'
           - OCP: csi_volume_handle='vol-0123456789abcdef'
           - Match: aws_id.endswith(ocp_id) or ocp_id in aws_id

        Equivalent to Trino SQL:
            substr(aws.lineitem_resourceid, -length(ocp.resource_id)) = ocp.resource_id

        Args:
            aws_df: AWS line items DataFrame with 'lineitem_resourceid' column
            ocp_resource_ids: Dictionary of OCP resource ID sets

        Returns:
            DataFrame with added columns:
                - 'resource_id_matched': Boolean indicating if matched
                - 'matched_resource_id': The OCP resource ID that matched
                - 'match_type': Type of match ('node', 'pv', 'csi_handle')
        """
        with PerformanceTimer("Match AWS resources by resource ID", self.logger):
            # Create a copy to avoid modifying original
            aws_df = aws_df.copy()

            # Initialize matching columns (required even for empty DataFrames)
            aws_df["resource_id_matched"] = False
            aws_df["matched_resource_id"] = None
            aws_df["match_type"] = None

            if aws_df.empty:
                self.logger.warning("AWS DataFrame is empty, no matching possible")
                return aws_df

            # Validate AWS DataFrame has required column
            if "lineitem_resourceid" not in aws_df.columns:
                raise ValueError("AWS DataFrame missing 'lineitem_resourceid' column")

            # Track matching statistics
            stats = {
                "total_aws_resources": len(aws_df),
                "matched_by_node": 0,
                "matched_by_pv": 0,
                "matched_by_csi": 0,
                "total_matched": 0,
            }

            # Get AWS resource IDs (drop nulls)
            aws_resources = aws_df["lineitem_resourceid"].dropna()

            self.logger.info(f"Starting resource ID matching for {len(aws_resources)} AWS resources")

            # Match 1: AWS EC2 instances → OCP nodes
            if ocp_resource_ids["node_resource_ids"]:
                self.logger.debug(f"Matching against {len(ocp_resource_ids['node_resource_ids'])} node resource IDs")

                for node_id in ocp_resource_ids["node_resource_ids"]:
                    # Find AWS resources that end with this node ID
                    mask = aws_resources.str.endswith(node_id, na=False)
                    matched_indices = aws_df[mask].index

                    if len(matched_indices) > 0:
                        aws_df.loc[matched_indices, "resource_id_matched"] = True
                        aws_df.loc[matched_indices, "matched_resource_id"] = node_id
                        aws_df.loc[matched_indices, "match_type"] = "node"
                        stats["matched_by_node"] += len(matched_indices)

                        self.logger.debug(f"Matched {len(matched_indices)} AWS resources to node {node_id}")

            # Match 2: AWS EBS volumes → OCP PV names
            # Trino SQL: substr(resource_id, -length(pv_name)) = pv_name (SUFFIX matching)
            if ocp_resource_ids["pv_names"]:
                self.logger.debug(f"Matching against {len(ocp_resource_ids['pv_names'])} PV names")

                for pv_name in ocp_resource_ids["pv_names"]:
                    # Find AWS resources that END WITH this PV name (Trino-compliant)
                    # Only match if not already matched
                    mask = aws_resources.str.endswith(pv_name, na=False) & (~aws_df["resource_id_matched"])
                    matched_indices = aws_df[mask].index

                    if len(matched_indices) > 0:
                        aws_df.loc[matched_indices, "resource_id_matched"] = True
                        aws_df.loc[matched_indices, "matched_resource_id"] = pv_name
                        aws_df.loc[matched_indices, "match_type"] = "pv"
                        stats["matched_by_pv"] += len(matched_indices)

                        self.logger.debug(f"Matched {len(matched_indices)} AWS resources to PV {pv_name}")

            # Match 3: AWS EBS volumes → OCP CSI volume handles
            if ocp_resource_ids["csi_volume_handles"]:
                self.logger.debug(f"Matching against {len(ocp_resource_ids['csi_volume_handles'])} CSI volume handles")

                for csi_handle in ocp_resource_ids["csi_volume_handles"]:
                    # Skip empty CSI handles
                    if not csi_handle or csi_handle == "":
                        continue

                    # Find AWS resources that end with this CSI handle
                    # Only match if not already matched
                    mask = aws_resources.str.endswith(csi_handle, na=False) & (~aws_df["resource_id_matched"])
                    matched_indices = aws_df[mask].index

                    if len(matched_indices) > 0:
                        aws_df.loc[matched_indices, "resource_id_matched"] = True
                        aws_df.loc[matched_indices, "matched_resource_id"] = csi_handle
                        aws_df.loc[matched_indices, "match_type"] = "csi_handle"
                        stats["matched_by_csi"] += len(matched_indices)

                        self.logger.debug(f"Matched {len(matched_indices)} AWS resources to CSI handle {csi_handle}")

            # Calculate total matched
            stats["total_matched"] = aws_df["resource_id_matched"].sum()
            stats["match_rate"] = (
                stats["total_matched"] / stats["total_aws_resources"] * 100 if stats["total_aws_resources"] > 0 else 0
            )

            self.logger.info(
                "✓ Resource ID matching complete",
                total_aws=stats["total_aws_resources"],
                matched=stats["total_matched"],
                match_rate=f"{stats['match_rate']:.2f}%",
                by_node=stats["matched_by_node"],
                by_pv=stats["matched_by_pv"],
                by_csi=stats["matched_by_csi"],
            )

            # Log warning if match rate is low
            if stats["match_rate"] < 50:
                self.logger.warning(
                    f"Low resource ID match rate: {stats['match_rate']:.2f}% "
                    "(This is expected if most AWS resources are matched by tags instead)"
                )

            return aws_df

    def get_matched_resources_summary(self, aws_df: pd.DataFrame) -> Dict:
        """
        Get a summary of matched resources.

        Args:
            aws_df: AWS DataFrame with matching columns

        Returns:
            Dictionary with summary statistics
        """
        if "resource_id_matched" not in aws_df.columns:
            return {"status": "not_matched"}

        summary = {
            "total_resources": len(aws_df),
            "matched": aws_df["resource_id_matched"].sum(),
            "unmatched": (~aws_df["resource_id_matched"]).sum(),
            "match_rate": (aws_df["resource_id_matched"].sum() / len(aws_df) * 100 if len(aws_df) > 0 else 0),
            "by_match_type": {},
        }

        if "match_type" in aws_df.columns:
            summary["by_match_type"] = aws_df[aws_df["resource_id_matched"]]["match_type"].value_counts().to_dict()

        if "lineitem_productcode" in aws_df.columns:
            summary["matched_by_product"] = (
                aws_df[aws_df["resource_id_matched"]]["lineitem_productcode"].value_counts().to_dict()
            )

        summary_str = ", ".join(f"{k}={v}" for k, v in summary.items())
        self.logger.info(f"Resource matching summary ({summary_str})")
        return summary

    def validate_matching_results(self, aws_df: pd.DataFrame, expected_match_rate_min: float = 0.0) -> bool:
        """
        Validate that resource matching results are reasonable.

        Args:
            aws_df: AWS DataFrame with matching columns
            expected_match_rate_min: Minimum expected match rate (0.0 to 1.0)

        Returns:
            True if validation passes, raises exception otherwise
        """
        if "resource_id_matched" not in aws_df.columns:
            raise ValueError("AWS DataFrame missing 'resource_id_matched' column")

        matched_count = aws_df["resource_id_matched"].sum()
        total_count = len(aws_df)
        match_rate = matched_count / total_count if total_count > 0 else 0

        if match_rate < expected_match_rate_min:
            error_msg = (
                f"Resource ID match rate ({match_rate:.2%}) below minimum " f"expected ({expected_match_rate_min:.2%})"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.logger.debug("✓ Resource matching validation passed")
        return True
