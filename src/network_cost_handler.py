"""
Network Cost Handler for OCP-on-AWS

Handles network/data transfer costs which are attributed to nodes but not to namespaces.

Key Logic (from Trino SQL 2_summarize_data_by_cluster.sql, lines 804-904):
1. Exclude network costs from regular attribution (data_transfer_direction IS NOT NULL)
2. Assign network costs to the special namespace "Network unattributed"
3. Group by node and data_transfer_direction
4. Only process resource_id_matched records

Complexity: MEDIUM (6/10)
"""

from typing import Dict

import numpy as np
import pandas as pd

from .utils import PerformanceTimer, get_logger


class NetworkCostHandler:
    """
    Handle network/data transfer cost attribution.

    Network costs are special because they are:
    1. Associated with EC2 instances/nodes (resource_id_matched=True)
    2. NOT attributable to specific namespaces/pods
    3. Assigned to a special namespace: "Network unattributed"
    4. Grouped by node and direction (IN/OUT)
    """

    NETWORK_NAMESPACE = "Network unattributed"

    def __init__(self, config: Dict):
        """
        Initialize network cost handler.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger("network_cost_handler")

        # Get markup percentage from config
        self.markup_percent = config.get("aws", {}).get("markup", 0.0)

        self.logger.info(
            "Initialized network cost handler", markup_percent=self.markup_percent
        )

    def filter_network_costs(
        self, aws_matched_df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Separate network costs from regular costs.

        This implements the Trino SQL filter:
            WHERE data_transfer_direction IS NOT NULL
            AND data_transfer_direction != ''

        Args:
            aws_matched_df: AWS DataFrame with matched resources

        Returns:
            Tuple of (non_network_df, network_df)
        """
        with PerformanceTimer("Filter network costs", self.logger):
            if aws_matched_df.empty:
                return aws_matched_df.copy(), pd.DataFrame()

            # Check if data_transfer_direction column exists
            if "data_transfer_direction" not in aws_matched_df.columns:
                self.logger.warning(
                    "data_transfer_direction column not found. "
                    "Treating all costs as non-network."
                )
                return aws_matched_df.copy(), pd.DataFrame()

            # Filter network costs (direction IS NOT NULL AND != '')
            is_network = aws_matched_df["data_transfer_direction"].notna() & (
                aws_matched_df["data_transfer_direction"] != ""
            )

            network_df = aws_matched_df[is_network].copy()
            non_network_df = aws_matched_df[~is_network].copy()

            network_count = len(network_df)
            non_network_count = len(non_network_df)

            self.logger.info(
                "✓ Separated network costs",
                total_records=len(aws_matched_df),
                network_costs=network_count,
                non_network_costs=non_network_count,
                network_percentage=f"{network_count/len(aws_matched_df)*100:.1f}%",
            )

            return non_network_df, network_df

    def attribute_network_costs(
        self, network_df: pd.DataFrame, ocp_pod_usage_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Attribute network costs to the "Network unattributed" namespace.

        Implements Trino SQL logic from 2_summarize_data_by_cluster.sql (lines 844-904):
            'Network unattributed' AS namespace,
            ocp.node AS node,
            GROUP BY aws.row_uuid, ocp.node, aws.data_transfer_direction

        Args:
            network_df: DataFrame of network costs (from filter_network_costs)
            ocp_pod_usage_df: OCP pod usage data (to get node information)

        Returns:
            DataFrame with network costs attributed to "Network unattributed" namespace
        """
        with PerformanceTimer("Attribute network costs", self.logger):
            if network_df.empty:
                self.logger.info("No network costs to attribute")
                return pd.DataFrame()

            # Validate required columns in network_df
            required_aws_cols = [
                "lineitem_resourceid",
                "data_transfer_direction",
                "lineitem_unblendedcost",
                "lineitem_blendedcost",
                "lineitem_usageamount",
            ]
            missing_cols = [
                col for col in required_aws_cols if col not in network_df.columns
            ]
            if missing_cols:
                raise ValueError(
                    f"Network DataFrame missing required columns: {missing_cols}"
                )

            # Validate required columns in OCP data
            if (
                "node" not in ocp_pod_usage_df.columns
                or "resource_id" not in ocp_pod_usage_df.columns
            ):
                raise ValueError(
                    "OCP DataFrame missing required columns: node, resource_id"
                )

            # Join network costs with OCP data to get node information
            # Match on resource_id (suffix matching)
            self.logger.info(
                "Joining network costs with OCP node data",
                network_records=len(network_df),
                ocp_records=len(ocp_pod_usage_df),
            )

            # Create a mapping of resource_id to node
            # We need to match lineitem_resourceid (AWS) to resource_id (OCP)
            ocp_nodes = ocp_pod_usage_df[["resource_id", "node"]].drop_duplicates()

            # Perform suffix matching (similar to resource matcher logic)
            network_with_nodes = []

            for _, aws_row in network_df.iterrows():
                aws_resource_id = aws_row["lineitem_resourceid"]

                # Find matching OCP node by suffix matching
                matched_node = None
                for _, ocp_row in ocp_nodes.iterrows():
                    ocp_resource_id = ocp_row["resource_id"]
                    if aws_resource_id.endswith(ocp_resource_id):
                        matched_node = ocp_row["node"]
                        break

                if matched_node:
                    row_dict = aws_row.to_dict()
                    row_dict["node"] = matched_node
                    row_dict["namespace"] = self.NETWORK_NAMESPACE
                    network_with_nodes.append(row_dict)

            if not network_with_nodes:
                self.logger.warning(
                    "No network costs matched to OCP nodes. "
                    "Network costs will not be attributed."
                )
                return pd.DataFrame()

            result_df = pd.DataFrame(network_with_nodes)

            # Group by node and direction
            # Trino SQL: GROUP BY aws.row_uuid, ocp.node, aws.data_transfer_direction
            group_cols = ["node", "data_transfer_direction", "namespace"]

            # Aggregate costs
            agg_dict = {
                "lineitem_unblendedcost": "sum",
                "lineitem_blendedcost": "sum",
                "lineitem_usageamount": "sum",
            }

            # Add required timestamp columns
            if "lineitem_usagestartdate" in result_df.columns:
                agg_dict["lineitem_usagestartdate"] = "min"  # Start of period
            if "lineitem_usageenddate" in result_df.columns:
                agg_dict["lineitem_usageenddate"] = "max"  # End of period

            # Add optional cost columns if present
            if "savingsplan_savingsplaneffectivecost" in result_df.columns:
                agg_dict["savingsplan_savingsplaneffectivecost"] = "sum"
            if "calculated_amortized_cost" in result_df.columns:
                agg_dict["calculated_amortized_cost"] = "sum"

            aggregated = result_df.groupby(group_cols, as_index=False).agg(agg_dict)

            # Rename AWS columns to POC standard names for compatibility with _format_output
            column_mapping = {
                "lineitem_usagestartdate": "usage_start",
                "lineitem_usageenddate": "usage_end",
                "lineitem_unblendedcost": "unblended_cost",
                "lineitem_blendedcost": "blended_cost",
                "lineitem_usageamount": "usage_amount",
            }

            # Apply column renaming
            aggregated = aggregated.rename(
                columns={
                    k: v for k, v in column_mapping.items() if k in aggregated.columns
                }
            )

            # Normalize timestamps to timezone-naive to match compute costs
            if (
                "usage_start" in aggregated.columns
                and pd.api.types.is_datetime64tz_dtype(aggregated["usage_start"])
            ):
                aggregated["usage_start"] = aggregated["usage_start"].dt.tz_localize(
                    None
                )
            if (
                "usage_end" in aggregated.columns
                and pd.api.types.is_datetime64tz_dtype(aggregated["usage_end"])
            ):
                aggregated["usage_end"] = aggregated["usage_end"].dt.tz_localize(None)

            # Calculate markup costs (use renamed columns)
            aggregated["markup_cost"] = aggregated["unblended_cost"] * (
                self.markup_percent / 100.0
            )
            aggregated["markup_cost_blended"] = aggregated["blended_cost"] * (
                self.markup_percent / 100.0
            )

            if "savingsplan_savingsplaneffectivecost" in aggregated.columns:
                aggregated["markup_cost_savingsplan"] = aggregated[
                    "savingsplan_savingsplaneffectivecost"
                ] * (self.markup_percent / 100.0)

            if "calculated_amortized_cost" in aggregated.columns:
                aggregated["markup_cost_amortized"] = aggregated[
                    "calculated_amortized_cost"
                ] * (self.markup_percent / 100.0)

            self.logger.info(
                "✓ Network costs attributed",
                total_network_records=len(result_df),
                grouped_records=len(aggregated),
                unique_nodes=aggregated["node"].nunique(),
                total_cost=aggregated["unblended_cost"].sum(),
            )

            return aggregated

    def get_network_summary(self, network_df: pd.DataFrame) -> Dict:
        """
        Get summary statistics for network costs.

        Args:
            network_df: Network costs DataFrame

        Returns:
            Dictionary with summary statistics
        """
        if network_df.empty:
            return {"status": "no_network_costs"}

        summary = {
            "total_records": len(network_df),
            "unique_nodes": network_df["node"].nunique()
            if "node" in network_df.columns
            else 0,
            "direction_breakdown": (
                network_df["data_transfer_direction"].value_counts().to_dict()
                if "data_transfer_direction" in network_df.columns
                else {}
            ),
            "total_cost_unblended": (
                network_df["unblended_cost"].sum()
                if "unblended_cost" in network_df.columns
                else 0
            ),
            "total_usage_amount": (
                network_df["usage_amount"].sum()
                if "usage_amount" in network_df.columns
                else 0
            ),
        }

        self.logger.info("Network cost summary", **summary)
        return summary
