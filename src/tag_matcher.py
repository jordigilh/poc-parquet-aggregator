"""
Tag Matcher for OCP-on-AWS

Matches AWS resources to OCP resources by special OpenShift tags.

Special Tags:
- openshift_cluster: Matches to OCP cluster_id
- openshift_node: Matches to OCP node name
- openshift_project: Matches to OCP namespace

Key Logic:
1. Parse AWS resourcetags (JSON string)
2. Filter by enabled tag keys (from PostgreSQL)
3. Match special OpenShift tags to OCP resources
4. Only match resources NOT already matched by resource ID
5. Track which tags matched

Complexity: MEDIUM-HIGH (7/10)
"""

import json
from typing import Dict, List, Set

import pandas as pd

from .utils import PerformanceTimer, get_logger


class TagMatcher:
    """
    Match AWS resources to OCP resources by tags.

    This class implements tag-based matching for AWS resources that
    couldn't be matched by resource ID. It looks for special OpenShift
    tags on AWS resources and matches them to OCP clusters/nodes/namespaces.
    """

    # Special OpenShift tag keys
    TAG_OPENSHIFT_CLUSTER = "openshift_cluster"
    TAG_OPENSHIFT_NODE = "openshift_node"
    TAG_OPENSHIFT_PROJECT = "openshift_project"

    SPECIAL_TAGS = [TAG_OPENSHIFT_CLUSTER, TAG_OPENSHIFT_NODE, TAG_OPENSHIFT_PROJECT]

    def __init__(self, config: Dict):
        """
        Initialize tag matcher.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger("tag_matcher")

        self.logger.info("Initialized tag matcher")

    def extract_ocp_tag_values(
        self,
        cluster_id: str,
        pod_usage_df: pd.DataFrame,
        storage_usage_df: pd.DataFrame = None,
        cluster_alias: str = None,
    ) -> Dict[str, Set[str]]:
        """
        Extract all unique OCP values for tag matching.

        Args:
            cluster_id: OCP cluster ID
            pod_usage_df: OCP pod usage DataFrame
            storage_usage_df: OCP storage usage DataFrame (optional)
            cluster_alias: OCP cluster alias (optional)

        Returns:
            Dictionary with sets of:
                - 'cluster_ids': Set of cluster IDs
                - 'cluster_aliases': Set of cluster aliases
                - 'node_names': Set of node names
                - 'namespaces': Set of namespaces
                - 'pod_labels': Set of "key=value" strings from pod labels
                - 'volume_labels': Set of "key=value" strings from volume labels
        """
        with PerformanceTimer("Extract OCP tag values", self.logger):
            tag_values = {
                "cluster_ids": set(),
                "cluster_aliases": set(),
                "node_names": set(),
                "namespaces": set(),
                "pod_labels": set(),
                "volume_labels": set(),
            }

            # Extract cluster IDs from data (multi-cluster support)
            if not pod_usage_df.empty and "cluster_id" in pod_usage_df.columns:
                cluster_ids = pod_usage_df["cluster_id"].dropna().unique()
                tag_values["cluster_ids"] = set(cluster_ids)
                self.logger.info(
                    f"Extracted {len(tag_values['cluster_ids'])} unique cluster IDs from data: {sorted(tag_values['cluster_ids'])}"
                )
            else:
                # Fallback to parameter if cluster_id column doesn't exist
                tag_values["cluster_ids"] = {cluster_id}
                self.logger.info(f"Using cluster_id parameter (no cluster_id column in data): {cluster_id}")

            # Extract node names
            if not pod_usage_df.empty and "node" in pod_usage_df.columns:
                node_names = pod_usage_df["node"].dropna().unique()
                tag_values["node_names"] = set(node_names)
                self.logger.info(f"Extracted {len(tag_values['node_names'])} unique node names")

            # Extract namespaces
            if not pod_usage_df.empty and "namespace" in pod_usage_df.columns:
                namespaces = pod_usage_df["namespace"].dropna().unique()
                tag_values["namespaces"] = set(namespaces)
                self.logger.info(f"Extracted {len(tag_values['namespaces'])} unique namespaces")

            # Extract cluster_aliases (Gap #1 fix)
            if cluster_alias:
                tag_values["cluster_aliases"] = {cluster_alias}
                self.logger.info(f"Added cluster_alias: {cluster_alias}")

            # Extract pod_labels (Gap #2 - part 1)
            if not pod_usage_df.empty and "pod_labels" in pod_usage_df.columns:
                pod_label_count = 0
                for labels_json in pod_usage_df["pod_labels"].dropna().unique():
                    labels_dict = self.parse_ocp_labels(labels_json)
                    for key, value in labels_dict.items():
                        tag_values["pod_labels"].add(f"{key}={value}")
                        pod_label_count += 1

                self.logger.info(
                    f"Extracted {pod_label_count} unique pod label key=value pairs from {len(pod_usage_df['pod_labels'].dropna().unique())} unique label sets"
                )

            # Extract volume_labels (Gap #2 - part 2)
            if storage_usage_df is not None and not storage_usage_df.empty:
                volume_label_count = 0

                # Extract from persistentvolume_labels
                if "persistentvolume_labels" in storage_usage_df.columns:
                    for labels_json in storage_usage_df["persistentvolume_labels"].dropna().unique():
                        labels_dict = self.parse_ocp_labels(labels_json)
                        for key, value in labels_dict.items():
                            tag_values["volume_labels"].add(f"{key}={value}")
                            volume_label_count += 1

                # Extract from persistentvolumeclaim_labels
                if "persistentvolumeclaim_labels" in storage_usage_df.columns:
                    for labels_json in storage_usage_df["persistentvolumeclaim_labels"].dropna().unique():
                        labels_dict = self.parse_ocp_labels(labels_json)
                        for key, value in labels_dict.items():
                            tag_values["volume_labels"].add(f"{key}={value}")
                            volume_label_count += 1

                self.logger.info(
                    f"Extracted {volume_label_count} volume label key=value pairs, {len(tag_values['volume_labels'])} unique"
                )

            total_values = (
                len(tag_values["cluster_ids"])
                + len(tag_values["cluster_aliases"])
                + len(tag_values["node_names"])
                + len(tag_values["namespaces"])
                + len(tag_values["pod_labels"])
                + len(tag_values["volume_labels"])
            )

            self.logger.info(
                "✓ Extracted OCP tag values",
                clusters=len(tag_values["cluster_ids"]),
                cluster_aliases=len(tag_values["cluster_aliases"]),
                nodes=len(tag_values["node_names"]),
                namespaces=len(tag_values["namespaces"]),
                pod_labels=len(tag_values["pod_labels"]),
                volume_labels=len(tag_values["volume_labels"]),
                total=total_values,
            )

            return tag_values

    def parse_ocp_labels(self, labels_json: str) -> Dict[str, str]:
        """
        Parse OCP labels from JSON string format.

        OCP labels are stored as JSON strings in Parquet:
        - pod_labels: {"app": "frontend", "tier": "web"}
        - persistentvolume_labels: {"storage": "ssd", "environment": "prod"}

        Args:
            labels_json: JSON string of labels

        Returns:
            Dictionary of label key-value pairs
        """
        if not labels_json or pd.isna(labels_json):
            return {}

        try:
            # Handle both JSON dict and pipe-separated format
            if labels_json.startswith("{"):
                # JSON format: {"app": "frontend"}
                return json.loads(labels_json)
            elif "|" in labels_json:
                # Pipe format: app:frontend|tier:web
                labels = {}
                for pair in labels_json.split("|"):
                    if ":" in pair:
                        key, value = pair.split(":", 1)
                        labels[key.strip()] = value.strip()
                return labels
            else:
                return {}
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.debug(f"Failed to parse OCP labels: {e}")
            return {}

    def parse_aws_tags(self, tags_json: str) -> Dict[str, str]:
        """
        Parse AWS resource tags from JSON string.

        Args:
            tags_json: JSON string of AWS tags

        Returns:
            Dictionary of tags, or empty dict if parsing fails
        """
        if pd.isna(tags_json) or tags_json == "" or tags_json == "{}":
            return {}

        try:
            tags = json.loads(tags_json)
            if not isinstance(tags, dict):
                return {}
            return tags
        except (json.JSONDecodeError, TypeError) as e:
            self.logger.debug(f"Failed to parse AWS tags: {e}")
            return {}

    def filter_by_enabled_keys(self, aws_tags: Dict[str, str], enabled_keys: Set[str]) -> Dict[str, str]:
        """
        Filter AWS tags to only include enabled keys.

        This implements the Trino SQL:
            map_filter(
                cast(json_parse(aws.resourcetags) as map(varchar, varchar)),
                (k, v) -> contains(enabled_keys, k)
            )

        Args:
            aws_tags: Dictionary of AWS tags
            enabled_keys: Set of enabled tag keys from PostgreSQL

        Returns:
            Filtered dictionary with only enabled tags
        """
        if not enabled_keys:
            # If no enabled keys specified, allow all
            return aws_tags

        return {k: v for k, v in aws_tags.items() if k in enabled_keys}

    def match_by_tags(
        self,
        aws_df: pd.DataFrame,
        ocp_tag_values: Dict[str, Set[str]],
        enabled_keys: Set[str] = None,
    ) -> pd.DataFrame:
        """
        Match AWS resources to OCP by tags.

        This implements tag-based matching:

        1. **Cluster matching**: openshift_cluster tag matches cluster_id
        2. **Node matching**: openshift_node tag matches node name
        3. **Namespace matching**: openshift_project tag matches namespace

        Only matches resources that were NOT already matched by resource ID.

        Equivalent to Trino SQL:
            array_join(
                filter(matched_tags, x -> STRPOS(resourcetags, x) != 0),
                ','
            ) as matched_tag

        Args:
            aws_df: AWS line items DataFrame with 'resourcetags' column
            ocp_tag_values: Dictionary of OCP values to match against
            enabled_keys: Set of enabled tag keys (None = allow all)

        Returns:
            DataFrame with added columns:
                - 'tag_matched': Boolean indicating if matched by tags
                - 'matched_tag': The tag that matched (e.g., 'openshift_cluster=my-cluster')
                - 'matched_ocp_cluster': OCP cluster ID that matched
                - 'matched_ocp_node': OCP node name that matched
                - 'matched_ocp_namespace': OCP namespace that matched
        """
        with PerformanceTimer("Match AWS resources by tags", self.logger):
            # Create a copy to avoid modifying original
            aws_df = aws_df.copy()

            # Initialize tag matching columns (required even for empty DataFrames)
            aws_df["tag_matched"] = False
            aws_df["matched_tag"] = None
            aws_df["matched_ocp_cluster"] = None
            aws_df["matched_ocp_node"] = None
            aws_df["matched_ocp_namespace"] = None

            if aws_df.empty:
                self.logger.warning("AWS DataFrame is empty, no matching possible")
                return aws_df

            # Validate AWS DataFrame has required column
            if "resourcetags" not in aws_df.columns:
                raise ValueError("AWS DataFrame missing 'resourcetags' column")

            # Track matching statistics
            stats = {
                "total_aws_resources": len(aws_df),
                "already_matched_by_resource_id": 0,
                "matched_by_cluster_tag": 0,
                "matched_by_cluster_alias": 0,
                "matched_by_node_tag": 0,
                "matched_by_namespace_tag": 0,
                "matched_by_pod_labels": 0,
                "matched_by_volume_labels": 0,
                "total_tag_matched": 0,
                "tags_parsed": 0,
                "tags_failed_to_parse": 0,
            }

            # Skip resources already matched by resource ID
            if "resource_id_matched" in aws_df.columns:
                already_matched = aws_df["resource_id_matched"].sum()
                stats["already_matched_by_resource_id"] = already_matched
                self.logger.info(f"Skipping {already_matched} resources already matched by resource ID")

            self.logger.info(f"Starting tag matching for {len(aws_df)} AWS resources")

            # Iterate through AWS resources
            for idx, row in aws_df.iterrows():
                # Skip if already matched by resource ID
                if "resource_id_matched" in row and row["resource_id_matched"]:
                    continue

                # Skip if already matched by tag (in case of duplicate processing)
                if row["tag_matched"]:
                    continue

                # Parse AWS tags
                tags_json = row["resourcetags"]
                aws_tags = self.parse_aws_tags(tags_json)

                if not aws_tags:
                    stats["tags_failed_to_parse"] += 1
                    continue

                stats["tags_parsed"] += 1

                # Filter by enabled keys
                if enabled_keys:
                    aws_tags = self.filter_by_enabled_keys(aws_tags, enabled_keys)

                if not aws_tags:
                    continue

                # Check for special OpenShift tags
                matched = False
                matched_tag_str = None

                # Priority 1: Cluster tag (matches cluster_id OR cluster_alias)
                if self.TAG_OPENSHIFT_CLUSTER in aws_tags:
                    cluster_value = aws_tags[self.TAG_OPENSHIFT_CLUSTER]

                    # Check against cluster_id
                    if cluster_value in ocp_tag_values["cluster_ids"]:
                        aws_df.at[idx, "tag_matched"] = True
                        aws_df.at[idx, "matched_tag"] = f"{self.TAG_OPENSHIFT_CLUSTER}={cluster_value}"
                        aws_df.at[idx, "matched_ocp_cluster"] = cluster_value
                        stats["matched_by_cluster_tag"] += 1
                        matched = True
                        matched_tag_str = f"{self.TAG_OPENSHIFT_CLUSTER}={cluster_value}"

                    # Also check against cluster_alias (Gap #1 fix)
                    elif cluster_value in ocp_tag_values.get("cluster_aliases", set()):
                        aws_df.at[idx, "tag_matched"] = True
                        aws_df.at[idx, "matched_tag"] = f"{self.TAG_OPENSHIFT_CLUSTER}={cluster_value} (alias)"
                        aws_df.at[idx, "matched_ocp_cluster"] = cluster_value
                        stats["matched_by_cluster_alias"] += 1
                        matched = True
                        matched_tag_str = f"{self.TAG_OPENSHIFT_CLUSTER}={cluster_value} (alias)"

                # Priority 2: Node tag
                if not matched and self.TAG_OPENSHIFT_NODE in aws_tags:
                    node_value = aws_tags[self.TAG_OPENSHIFT_NODE]
                    if node_value in ocp_tag_values["node_names"]:
                        aws_df.at[idx, "tag_matched"] = True
                        aws_df.at[idx, "matched_tag"] = f"{self.TAG_OPENSHIFT_NODE}={node_value}"
                        aws_df.at[idx, "matched_ocp_node"] = node_value
                        stats["matched_by_node_tag"] += 1
                        matched = True
                        matched_tag_str = f"{self.TAG_OPENSHIFT_NODE}={node_value}"

                # Priority 3: Project/Namespace tag
                if not matched and self.TAG_OPENSHIFT_PROJECT in aws_tags:
                    namespace_value = aws_tags[self.TAG_OPENSHIFT_PROJECT]
                    if namespace_value in ocp_tag_values["namespaces"]:
                        aws_df.at[idx, "tag_matched"] = True
                        aws_df.at[idx, "matched_tag"] = f"{self.TAG_OPENSHIFT_PROJECT}={namespace_value}"
                        aws_df.at[idx, "matched_ocp_namespace"] = namespace_value
                        stats["matched_by_namespace_tag"] += 1
                        matched = True
                        matched_tag_str = f"{self.TAG_OPENSHIFT_PROJECT}={namespace_value}"

                # Priority 4: Generic tags matched against pod_labels (Gap #2 - part 1)
                # Trino SQL line 9: any_match(..., x->strpos(ocp.pod_labels, ...) != 0)
                if not matched:
                    for tag_key, tag_value in aws_tags.items():
                        # Skip special OpenShift tags (already checked above)
                        if tag_key in [
                            self.TAG_OPENSHIFT_CLUSTER,
                            self.TAG_OPENSHIFT_NODE,
                            self.TAG_OPENSHIFT_PROJECT,
                        ]:
                            continue

                        # Check if this tag appears in pod_labels
                        tag_str = f"{tag_key}={tag_value}"
                        if tag_str in ocp_tag_values.get("pod_labels", set()):
                            aws_df.at[idx, "tag_matched"] = True
                            aws_df.at[idx, "matched_tag"] = f"{tag_str} (pod_labels)"
                            aws_df.at[idx, "match_type"] = "pod_labels"
                            stats["matched_by_pod_labels"] += 1
                            matched = True
                            matched_tag_str = f"{tag_str} (pod_labels)"
                            break

                # Priority 5: Generic tags matched against volume_labels (Gap #2 - part 2)
                # Trino SQL line 10: any_match(..., x->strpos(ocp.volume_labels, ...) != 0)
                if not matched:
                    for tag_key, tag_value in aws_tags.items():
                        # Skip special OpenShift tags
                        if tag_key in [
                            self.TAG_OPENSHIFT_CLUSTER,
                            self.TAG_OPENSHIFT_NODE,
                            self.TAG_OPENSHIFT_PROJECT,
                        ]:
                            continue

                        # Check if this tag appears in volume_labels
                        tag_str = f"{tag_key}={tag_value}"
                        if tag_str in ocp_tag_values.get("volume_labels", set()):
                            aws_df.at[idx, "tag_matched"] = True
                            aws_df.at[idx, "matched_tag"] = f"{tag_str} (volume_labels)"
                            aws_df.at[idx, "match_type"] = "volume_labels"
                            stats["matched_by_volume_labels"] += 1
                            matched = True
                            matched_tag_str = f"{tag_str} (volume_labels)"
                            break

                if matched:
                    self.logger.debug(f"Matched AWS resource by tag: {matched_tag_str}")

            # Calculate total matched
            stats["total_tag_matched"] = aws_df["tag_matched"].sum()

            # Calculate combined match rate (resource ID + tags)
            if "resource_id_matched" in aws_df.columns:
                total_matched = (aws_df["resource_id_matched"] | aws_df["tag_matched"]).sum()
                stats["combined_match_rate"] = (
                    total_matched / stats["total_aws_resources"] * 100 if stats["total_aws_resources"] > 0 else 0
                )
            else:
                stats["combined_match_rate"] = (
                    stats["total_tag_matched"] / stats["total_aws_resources"] * 100
                    if stats["total_aws_resources"] > 0
                    else 0
                )

            self.logger.info(
                "✓ Tag matching complete",
                total_aws=stats["total_aws_resources"],
                tag_matched=stats["total_tag_matched"],
                by_cluster=stats["matched_by_cluster_tag"],
                by_cluster_alias=stats["matched_by_cluster_alias"],
                by_node=stats["matched_by_node_tag"],
                by_namespace=stats["matched_by_namespace_tag"],
                by_pod_labels=stats["matched_by_pod_labels"],
                by_volume_labels=stats["matched_by_volume_labels"],
                combined_match_rate=f"{stats['combined_match_rate']:.2f}%",
            )

            # Log warning if still low match rate
            if stats["combined_match_rate"] < 70:
                self.logger.warning(
                    f"Low combined match rate: {stats['combined_match_rate']:.2f}% "
                    "(Some AWS resources may not have OpenShift tags)"
                )

            return aws_df

    def get_tag_matching_summary(self, aws_df: pd.DataFrame) -> Dict:
        """
        Get a summary of tag matching results.

        Args:
            aws_df: AWS DataFrame with tag matching columns

        Returns:
            Dictionary with summary statistics
        """
        if "tag_matched" not in aws_df.columns:
            return {"status": "not_matched"}

        summary = {
            "total_resources": len(aws_df),
            "tag_matched": aws_df["tag_matched"].sum(),
            "matched_by_cluster": (
                (aws_df["matched_ocp_cluster"].notna()).sum() if "matched_ocp_cluster" in aws_df.columns else 0
            ),
            "matched_by_node": (
                (aws_df["matched_ocp_node"].notna()).sum() if "matched_ocp_node" in aws_df.columns else 0
            ),
            "matched_by_namespace": (
                (aws_df["matched_ocp_namespace"].notna()).sum() if "matched_ocp_namespace" in aws_df.columns else 0
            ),
        }

        # Combined matching statistics
        if "resource_id_matched" in aws_df.columns:
            summary["resource_id_matched"] = aws_df["resource_id_matched"].sum()
            summary["combined_matched"] = (aws_df["resource_id_matched"] | aws_df["tag_matched"]).sum()
            summary["combined_match_rate"] = (
                summary["combined_matched"] / summary["total_resources"] * 100 if summary["total_resources"] > 0 else 0
            )

        if "lineitem_productcode" in aws_df.columns:
            summary["tag_matched_by_product"] = (
                aws_df[aws_df["tag_matched"]]["lineitem_productcode"].value_counts().to_dict()
            )

        self.logger.info("Tag matching summary", **summary)
        return summary

    def validate_tag_matching_results(self, aws_df: pd.DataFrame, expected_match_rate_min: float = 0.0) -> bool:
        """
        Validate that tag matching results are reasonable.

        Args:
            aws_df: AWS DataFrame with tag matching columns
            expected_match_rate_min: Minimum expected combined match rate (0.0 to 1.0)

        Returns:
            True if validation passes, raises exception otherwise
        """
        if "tag_matched" not in aws_df.columns:
            raise ValueError("AWS DataFrame missing 'tag_matched' column")

        # Calculate combined match rate
        if "resource_id_matched" in aws_df.columns:
            matched_count = (aws_df["resource_id_matched"] | aws_df["tag_matched"]).sum()
        else:
            matched_count = aws_df["tag_matched"].sum()

        total_count = len(aws_df)
        match_rate = matched_count / total_count if total_count > 0 else 0

        if match_rate < expected_match_rate_min:
            error_msg = (
                f"Combined match rate ({match_rate:.2%}) below minimum " f"expected ({expected_match_rate_min:.2%})"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.logger.debug("✓ Tag matching validation passed")
        return True
