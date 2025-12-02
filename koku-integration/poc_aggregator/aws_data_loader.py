"""
AWS Cost and Usage Report (CUR) Data Loader

Reads AWS CUR Parquet files from S3/MinIO for OCP-on-AWS provider.
Extends ParquetReader functionality for AWS-specific schema and partitioning.

Key Features:
- Reads AWS CUR line items (daily aggregated)
- Column filtering (15 of 40+ columns)
- Streaming support for large datasets
- AWS-specific partitioning: source={provider}/year={year}/month={month}

Usage:
    aws_loader = AWSDataLoader(config)
    aws_df = aws_loader.read_aws_line_items_daily(
        provider_uuid="abc-123",
        year="2025",
        month="10",
        streaming=True
    )
"""

from pathlib import Path
from typing import Dict, Iterator, List, Optional

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .parquet_reader import ParquetReader
from .utils import PerformanceTimer, format_bytes, get_logger


class AWSDataLoader:
    """
    Load AWS Cost and Usage Report (CUR) data from Parquet files.

    This class reads AWS billing data that will be matched with OCP workloads
    to attribute AWS infrastructure costs to OpenShift namespaces.
    """

    def __init__(self, config: Dict):
        """
        Initialize AWS data loader.

        Args:
            config: Configuration dictionary with AWS section
        """
        self.config = config
        self.logger = get_logger("aws_data_loader")

        # Reuse the existing ParquetReader for S3 operations
        self.parquet_reader = ParquetReader(config)

        self.logger.info("Initialized AWS data loader")

    def _detect_network_costs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect network/data transfer costs per Trino logic.

        Trino reference: 1_resource_matching_by_cluster.sql Lines 119-130

        Network costs are identified by:
        - lineitem_productcode = 'AmazonEC2' AND
        - product_productfamily = 'Data Transfer'

        Direction is determined by:
        - 'in-bytes' → IN
        - 'out-bytes' → OUT
        - 'regional-bytes' + '-in' operation → IN
        - 'regional-bytes' + '-out' operation → OUT

        Args:
            df: AWS CUR DataFrame

        Returns:
            DataFrame with data_transfer_direction column added
        """
        # Initialize column
        df["data_transfer_direction"] = None

        # Check if required columns exist
        if "lineitem_productcode" not in df.columns or "product_productfamily" not in df.columns:
            self.logger.warning("Missing columns for network detection, skipping")
            return df

        # Identify network records
        is_network = (df["lineitem_productcode"] == "AmazonEC2") & (df["product_productfamily"] == "Data Transfer")

        if not is_network.any():
            self.logger.info("No network/data transfer costs found")
            return df

        # Determine direction for network records
        usage_type_lower = df["lineitem_usagetype"].str.lower()
        operation_lower = (
            df["lineitem_operation"].str.lower() if "lineitem_operation" in df.columns else pd.Series([""] * len(df))
        )

        # IN-bytes
        df.loc[
            is_network & usage_type_lower.str.contains("in-bytes", na=False),
            "data_transfer_direction",
        ] = "IN"

        # OUT-bytes
        df.loc[
            is_network & usage_type_lower.str.contains("out-bytes", na=False),
            "data_transfer_direction",
        ] = "OUT"

        # Regional IN
        df.loc[
            is_network
            & usage_type_lower.str.contains("regional-bytes", na=False)
            & operation_lower.str.contains("-in", na=False),
            "data_transfer_direction",
        ] = "IN"

        # Regional OUT
        df.loc[
            is_network
            & usage_type_lower.str.contains("regional-bytes", na=False)
            & operation_lower.str.contains("-out", na=False),
            "data_transfer_direction",
        ] = "OUT"

        network_in = (df["data_transfer_direction"] == "IN").sum()
        network_out = (df["data_transfer_direction"] == "OUT").sum()

        self.logger.info(
            "✓ Network cost detection complete",
            total_records=len(df),
            network_records=is_network.sum(),
            network_in=network_in,
            network_out=network_out,
        )

        return df

    def _handle_savings_plan_costs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle SavingsPlan and Tax line items per Trino logic.

        Trino reference: 1_resource_matching_by_cluster.sql Lines 132-149
        JIRA: COST-5098 (SavingsPlanCoveredUsage needs to be negated)

        Key logic:
        1. SavingsPlanCoveredUsage: set unblended/blended to 0 (prevents double-counting)
        2. calculated_amortized_cost = unblended_cost for Tax/Usage, else savingsplan_effective_cost

        Args:
            df: AWS CUR DataFrame

        Returns:
            DataFrame with SavingsPlan costs handled correctly
        """
        # Check if required columns exist
        if "lineitem_lineitemtype" not in df.columns:
            self.logger.warning("lineitem_lineitemtype column not found, skipping SavingsPlan handling")
            return df

        if "savingsplan_savingsplaneffectivecost" not in df.columns:
            self.logger.info("savingsplan_savingsplaneffectivecost column not found, no SavingsPlan data to handle")
            df["savingsplan_savingsplaneffectivecost"] = 0.0

        # SavingsPlanCoveredUsage: set unblended/blended to 0 (COST-5098)
        # BUT ONLY if there's a valid savingsplan_effectivecost
        # (nise's default instances have saving values that trigger SavingsPlanCoveredUsage even when not intended)
        is_sp_covered = (
            (df["lineitem_lineitemtype"] == "SavingsPlanCoveredUsage")
            & (df["savingsplan_savingsplaneffectivecost"].notna())
            & (df["savingsplan_savingsplaneffectivecost"] > 0)
        )
        sp_covered_count = is_sp_covered.sum()

        if sp_covered_count > 0:
            df.loc[is_sp_covered, "lineitem_unblendedcost"] = 0.0
            df.loc[is_sp_covered, "lineitem_blendedcost"] = 0.0
            self.logger.info(
                "Set SavingsPlanCoveredUsage costs to 0 (COST-5098)",
                records_affected=sp_covered_count,
            )

        # calculated_amortized_cost logic
        is_tax_or_usage = df["lineitem_lineitemtype"].isin(["Tax", "Usage"])

        # Ensure savingsplan_savingsplaneffectivecost exists
        if "savingsplan_savingsplaneffectivecost" not in df.columns:
            df["savingsplan_savingsplaneffectivecost"] = 0.0

        # Calculate amortized cost per Trino logic
        df["lineitem_calculated_amortizedcost"] = np.where(
            is_tax_or_usage,
            df["lineitem_unblendedcost"],
            df["savingsplan_savingsplaneffectivecost"],
        )

        self.logger.info(
            "✓ Calculated amortized cost logic applied",
            tax_or_usage_count=is_tax_or_usage.sum(),
            sp_effective_cost_count=(~is_tax_or_usage).sum(),
        )

        return df

    def _consolidate_resource_tags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Consolidate expanded resourceTags columns into single JSON column.

        Follows koku's handle_user_defined_json_columns() implementation exactly:
        koku/masu/util/aws/aws_post_processor.py:29-42

        Input columns: resourceTags/user:app, resourceTags/user:environment, etc.
        Output column: resourcetags (JSON string)

        Also handles direct OpenShift tag columns (openshift_cluster, openshift_node, openshift_project)
        that nise generates for tag-based matching scenarios.
        """
        import json

        # Koku's prefixes (case-sensitive)
        RESOURCE_TAG_PREFIX = "resourceTags/"

        # Direct tag columns that nise generates (both OpenShift-specific and generic)
        # These columns contain tag values directly instead of in resourceTags/* format
        DIRECT_TAG_COLUMNS = [
            # OpenShift-specific tags
            "openshift_cluster",
            "openshift_node",
            "openshift_project",
            # Generic tags (commonly used by customers for cost attribution)
            "app",
            "component",
            "environment",
            "tier",
            "team",
            "nodeclass",
            "node_role_kubernetes_io",
            "version",
            "storageclass",
        ]

        # Find all resourceTags/* columns (koku looks for prefix match)
        tag_columns = [col for col in df.columns if RESOURCE_TAG_PREFIX in col]

        # Find direct OpenShift tag columns
        direct_tag_columns = [col for col in DIRECT_TAG_COLUMNS if col in df.columns]

        if not tag_columns and not direct_tag_columns:
            self.logger.debug("No resourceTags columns found, adding empty JSON column")
            df["resourcetags"] = "{}"
            return df

        self.logger.info(
            f"Consolidating {len(tag_columns)} resourceTags/* columns + {len(direct_tag_columns)} direct tag columns into JSON"
        )

        # Koku's scrub function: removes prefix to get tag name
        def scrub_tag_name(col: str) -> str:
            return col.replace(RESOURCE_TAG_PREFIX, "")

        # Combine both types of tag columns
        all_tag_columns = tag_columns + direct_tag_columns
        tag_df = df[all_tag_columns]

        def consolidate_row(row):
            """Build tag dict for a single row, handling empty/null values."""
            tags = {}
            for col, val in row.items():
                if pd.notna(val) and val != "" and val is not None:
                    # For resourceTags/* columns, scrub the prefix
                    if RESOURCE_TAG_PREFIX in col:
                        tag_name = scrub_tag_name(col)
                    else:
                        # For direct columns, use as-is
                        tag_name = col
                    tags[tag_name] = val
            return json.dumps(tags) if tags else "{}"

        # Apply consolidation row by row
        df["resourcetags"] = tag_df.apply(consolidate_row, axis=1)

        # Drop individual tag columns (save memory)
        df = df.drop(columns=all_tag_columns)

        self.logger.info(f"✓ Consolidated resourceTags/* + direct tags into 'resourcetags' JSON column")
        return df

    def get_optimal_columns_aws_cur(self) -> List[str]:
        """
        Get the optimal set of columns to read from AWS CUR Parquet files.

        AWS CUR has 40+ columns, but we only need ~15 for matching and costing.
        This significantly reduces memory usage and improves performance.

        Returns:
            List of column names to read
        """
        return [
            # Resource identification
            "lineitem_resourceid",  # AWS resource ID (e.g., i-0123..., vol-0123...)
            "lineitem_usageaccountid",  # AWS account ID
            # Product/Service info
            "lineitem_productcode",  # AWS service (EC2, EBS, RDS, etc.)
            "lineitem_usagetype",  # Usage type (e.g., BoxUsage, EBS:VolumeUsage)
            "product_instancetype",  # EC2 instance type (m5.large, etc.)
            "product_region",  # AWS region (us-east-1, etc.)
            "product_productfamily",  # Product family (Compute Instance, Storage, etc.)
            # Cost columns (4 types)
            "lineitem_unblendedcost",  # Standard cost
            "lineitem_blendedcost",  # Blended cost (reserved instance aware)
            "savingsplan_savingsplaneffectivecost",  # Savings Plan effective cost
            "pricing_publicondemandcost",  # Public on-demand cost (amortized base)
            # Usage metrics
            "lineitem_usageamount",  # Usage amount (hours, GB, etc.)
            "pricing_unit",  # Unit of measure (Hrs, GB, etc.)
            # Time dimension
            "lineitem_usagestartdate",  # Usage start date
            # NOTE: 'resourcetags' handled separately - we read all resourcetags_* dynamically
        ]

    def read_aws_line_items_daily(
        self,
        provider_uuid: str,
        year: str,
        month: str,
        streaming: bool = False,
        chunk_size: int = 50000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """
        Read AWS CUR line items (daily aggregated).

        AWS CUR data is partitioned by: source={provider}/year={year}/month={month}

        Args:
            provider_uuid: AWS provider UUID
            year: Year (e.g., "2025")
            month: Month (e.g., "10")
            streaming: Whether to stream chunks (for large datasets)
            chunk_size: Chunk size for streaming

        Returns:
            DataFrame or Iterator of DataFrames (if streaming)

        Example AWS CUR Schema:
            lineitem_resourceid: "i-0123456789abcdef0"
            lineitem_usageaccountid: "123456789012"
            lineitem_productcode: "AmazonEC2"
            lineitem_unblendedcost: 1.234
            resourcetags: '{"openshift_cluster": "my-cluster", ...}'
        """
        with PerformanceTimer("Read AWS CUR line items", self.logger):
            # Build S3 path using AWS-specific partitioning
            # Format: data/{org_id}/AWS/source={provider_uuid}/year={year}/month={month}/
            path_template = self.config.get("aws", {}).get(
                "parquet_path_line_items",
                "data/${ORG_ID}/AWS/source={provider_uuid}/year={year}/month={month}/*",
            )

            # Replace placeholders
            org_id = self.config.get("organization", {}).get("org_id", "1234567")
            s3_prefix = path_template.replace("${ORG_ID}", org_id)
            s3_prefix = s3_prefix.replace("{provider_uuid}", provider_uuid)
            s3_prefix = s3_prefix.replace("{year}", year)
            s3_prefix = s3_prefix.replace("{month}", month)

            # List Parquet files
            files = self.parquet_reader.list_parquet_files(s3_prefix)

            if not files:
                self.logger.warning(
                    "No AWS CUR data found for the given period",
                    provider_uuid=provider_uuid,
                    year=year,
                    month=month,
                    path=s3_prefix,
                )
                return pd.DataFrame() if not streaming else iter([])

            self.logger.info(
                f"Found {len(files)} AWS CUR Parquet files",
                count=len(files),
                provider_uuid=provider_uuid,
            )

            # Get optimal columns for filtering
            # NOTE: We disable column filtering for AWS to capture all resourcetags_* columns
            # These will be consolidated after reading
            columns = None
            self.logger.info("Reading all AWS CUR columns (needed for resourcetags consolidation)")

            # Read files (streaming or standard)
            if streaming:
                self.logger.info("Using streaming mode for AWS CUR", chunk_size=chunk_size)

                def stream_all_files():
                    """Stream all AWS CUR files chunk by chunk."""
                    for file in files:
                        self.logger.debug(f"Streaming AWS CUR file: {file}")
                        yield from self.parquet_reader.read_parquet_streaming(file, chunk_size, columns=columns)

                return stream_all_files()
            else:
                # Standard mode: parallel reading
                parallel_workers = self.config.get("performance", {}).get("parallel_readers", 4)
                self.logger.info(f"Reading AWS CUR with {parallel_workers} parallel workers")

                df = self.parquet_reader._read_files_parallel(files, parallel_workers, columns=columns)

                self.logger.info(
                    "✓ Loaded AWS CUR data",
                    rows=len(df),
                    memory=format_bytes(df.memory_usage(deep=True).sum()),
                )

                # Consolidate resourceTags/* columns into single JSON column (koku approach)
                df = self._consolidate_resource_tags(df)

                # Detect network/data transfer costs (Trino compliance)
                df = self._detect_network_costs(df)

                # Handle SavingsPlan costs (Trino compliance - COST-5098)
                # Fixed: Remove saving: lines from regular EC2 manifests (nise checks "if saving is not None")
                df = self._handle_savings_plan_costs(df)

                # DEBUG: Check for cost columns
                cost_cols = [c for c in df.columns if "cost" in c.lower()]
                cost_sum = df["lineitem_unblendedcost"].sum() if "lineitem_unblendedcost" in df.columns else 0
                self.logger.info(
                    "DEBUG: AWS data loaded",
                    cost_columns=cost_cols,
                    lineitem_unblendedcost_sum=cost_sum,
                    has_lineitem_unblendedcost="lineitem_unblendedcost" in df.columns,
                )

                return df

    def read_aws_line_items_for_matching(
        self,
        provider_uuid: str,
        year: str,
        month: str,
        resource_types: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Read AWS CUR data specifically for resource matching.

        This is a convenience method that:
        1. Reads only essential columns for matching
        2. Filters by resource types if specified
        3. Removes rows with null resource IDs (can't be matched)

        Args:
            provider_uuid: AWS provider UUID
            year: Year
            month: Month
            resource_types: Optional list of product codes to filter
                           (e.g., ["AmazonEC2", "AmazonEBS"])

        Returns:
            DataFrame with AWS resources ready for matching
        """
        self.logger.info("Reading AWS CUR data for resource matching")

        # Read full dataset (will apply column filtering automatically)
        aws_df = self.read_aws_line_items_daily(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            streaming=False,  # Matching requires full dataset
        )

        if aws_df.empty:
            self.logger.warning("No AWS CUR data to match")
            return aws_df

        # Filter by resource types if specified
        if resource_types:
            before_count = len(aws_df)
            aws_df = aws_df[aws_df["lineitem_productcode"].isin(resource_types)]
            self.logger.info(
                f"Filtered AWS CUR by resource types",
                resource_types=resource_types,
                before=before_count,
                after=len(aws_df),
            )

        # Remove rows with null resource IDs (can't be matched by resource ID)
        # These might still be matchable by tags
        before_count = len(aws_df)
        aws_df_with_ids = aws_df[aws_df["lineitem_resourceid"].notna()]
        null_count = before_count - len(aws_df_with_ids)

        if null_count > 0:
            self.logger.warning(
                f"Found {null_count} AWS line items with null resource IDs",
                null_count=null_count,
                total=before_count,
                percentage=f"{null_count/before_count*100:.1f}%",
            )

        self.logger.info(
            "✓ AWS CUR data ready for matching",
            rows=len(aws_df_with_ids),
            unique_resources=aws_df_with_ids["lineitem_resourceid"].nunique(),
        )

        return aws_df_with_ids

    def validate_aws_cur_schema(self, df: pd.DataFrame) -> bool:
        """
        Validate that the AWS CUR DataFrame has the required schema.

        Args:
            df: AWS CUR DataFrame to validate

        Returns:
            True if schema is valid, raises exception otherwise
        """
        required_columns = [
            "lineitem_resourceid",
            "lineitem_productcode",
            "lineitem_unblendedcost",
            "resourcetags",
        ]

        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            error_msg = f"AWS CUR DataFrame missing required columns: {missing_columns}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.logger.debug("✓ AWS CUR schema validation passed")
        return True

    def get_aws_resource_summary(self, df: pd.DataFrame) -> Dict:
        """
        Get a summary of AWS resources in the dataset.

        Useful for debugging and validation.

        Args:
            df: AWS CUR DataFrame

        Returns:
            Dictionary with summary statistics
        """
        if df.empty:
            return {"status": "empty"}

        summary = {
            "total_rows": len(df),
            "unique_resources": df["lineitem_resourceid"].nunique(),
            "unique_accounts": df["lineitem_usageaccountid"].nunique(),
            "product_codes": df["lineitem_productcode"].value_counts().to_dict(),
            "total_cost_unblended": df["lineitem_unblendedcost"].sum(),
            "date_range": {
                "min": df["lineitem_usagestartdate"].min() if "lineitem_usagestartdate" in df.columns else None,
                "max": df["lineitem_usagestartdate"].max() if "lineitem_usagestartdate" in df.columns else None,
            },
        }

        self.logger.info("AWS resource summary", **summary)
        return summary
