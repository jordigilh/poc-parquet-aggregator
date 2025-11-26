"""
OCP-on-AWS Aggregator

Orchestrates the complete OCP-on-AWS cost attribution pipeline:
1. Load OCP data (pod + storage usage)
2. Load AWS CUR data (with network cost detection)
3. Match AWS resources to OCP by resource ID
4. Match AWS resources to OCP by tags
5. Calculate EBS volume disk capacities
6. Attribute AWS costs to OCP pods/namespaces
7. Attribute network costs to "Network unattributed" namespace
8. Generate combined output table

This aggregator integrates all 6 tested components (100% confidence).
"""

import uuid as uuid_lib
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .aws_data_loader import AWSDataLoader
from .cost_attributor import CostAttributor
from .disk_capacity_calculator import DiskCapacityCalculator
from .network_cost_handler import NetworkCostHandler
from .parquet_reader import ParquetReader
from .resource_matcher import ResourceMatcher
from .streaming_processor import StreamingProcessor
from .tag_matcher import TagMatcher
from .utils import PerformanceTimer, get_logger


class OCPAWSAggregator:
    """
    Main aggregator for OCP-on-AWS cost attribution.

    Orchestrates the complete pipeline from raw Parquet files to
    the final combined OCP+AWS summary table.
    """

    def __init__(self, config: Dict, enabled_tag_keys: List[str]):
        """
        Initialize OCP-AWS aggregator.

        Args:
            config: Configuration dictionary
            enabled_tag_keys: List of enabled AWS tag keys from PostgreSQL
        """
        self.config = config
        self.enabled_tag_keys = enabled_tag_keys
        self.logger = get_logger("aggregator_ocp_aws")

        # OCP configuration
        self.ocp_config = config["ocp"]
        self.cluster_id = self.ocp_config["cluster_id"]
        self.cluster_alias = self.ocp_config["cluster_alias"]
        self.provider_uuid = self.ocp_config["provider_uuid"]
        self.report_period_id = self.ocp_config["report_period_id"]

        # AWS configuration
        self.aws_config = config.get("aws", {})
        self.aws_provider_uuid = self.aws_config.get("provider_uuid")
        self.markup_percent = self.aws_config.get("markup_percent", 0.0)
        self.cost_entry_bill_id = self.aws_config.get("cost_entry_bill_id", 1)

        # Performance configuration
        self.perf_config = config.get("performance", {})

        # Handle use_streaming as string or boolean
        use_streaming_raw = self.perf_config.get("use_streaming", False)
        if isinstance(use_streaming_raw, str):
            self.use_streaming = use_streaming_raw.lower() == "true"
        else:
            self.use_streaming = bool(use_streaming_raw)

        chunk_size_raw = self.perf_config.get("chunk_size", 100000)
        self.chunk_size = (
            int(chunk_size_raw) if isinstance(chunk_size_raw, str) else chunk_size_raw
        )

        # Initialize components
        self.parquet_reader = ParquetReader(config)
        self.aws_loader = AWSDataLoader(config)
        self.resource_matcher = ResourceMatcher(config)
        self.tag_matcher = TagMatcher(config)
        self.disk_calculator = DiskCapacityCalculator(config)
        self.cost_attributor = CostAttributor(config)
        self.network_handler = NetworkCostHandler(config)

        # Initialize streaming processor (for chunk-based processing)
        # IMPORTANT: OCP-on-AWS streaming MUST use serial mode, not parallel!
        # Parallel mode defeats streaming because it collects all chunks into memory first.
        # Serial mode processes one chunk at a time, maintaining bounded memory.
        if self.use_streaming:
            # Create a modified config with parallel_chunks=false for true streaming
            streaming_config = dict(config)
            streaming_config["performance"] = dict(config.get("performance", {}))
            streaming_config["performance"]["parallel_chunks"] = False  # Force serial

            self.streaming_processor = StreamingProcessor(
                config=streaming_config, logger=self.logger, name="ocp_aws_streaming"
            )
        else:
            self.streaming_processor = None

        self.logger.info(
            "Initialized OCP-AWS aggregator",
            cluster_id=self.cluster_id,
            aws_provider=self.aws_provider_uuid,
            markup_percent=self.markup_percent,
            enabled_tag_keys=len(enabled_tag_keys),
            streaming=self.use_streaming,
        )

    def aggregate(
        self,
        year: str,
        month: str,
        cluster_id: Optional[str] = None,
        aws_provider_uuid: Optional[str] = None,
        db_writer=None,
        incremental_db_writes: bool = False,
    ) -> pd.DataFrame:
        """
        Run the complete OCP-AWS aggregation pipeline.

        Automatically selects between in-memory and streaming mode based on
        the use_streaming configuration.

        Args:
            year: Year to process (e.g., '2024')
            month: Month to process (e.g., '10')
            cluster_id: OCP cluster ID (overrides config if provided)
            aws_provider_uuid: AWS provider UUID (overrides config if provided)
            db_writer: Optional DatabaseWriter for incremental writes (streaming only)
            incremental_db_writes: If True and streaming, write chunks to DB immediately

        Returns:
            DataFrame ready for PostgreSQL insert into
            reporting_ocpawscostlineitem_project_daily_summary
            (Empty if incremental_db_writes=True, since data is already in DB)
        """
        # Override config if provided
        cluster_id = cluster_id or self.cluster_id
        aws_provider_uuid = aws_provider_uuid or self.aws_provider_uuid

        # Dispatch to appropriate processing mode
        if self.use_streaming:
            self.logger.info("Using STREAMING mode (bounded memory)")
            return self._aggregate_streaming(
                year,
                month,
                cluster_id,
                aws_provider_uuid,
                db_writer=db_writer,
                incremental_db_writes=incremental_db_writes,
            )
        else:
            self.logger.info("Using IN-MEMORY mode (faster, more memory)")
            return self._aggregate_inmemory(year, month, cluster_id, aws_provider_uuid)

    def _aggregate_inmemory(
        self, year: str, month: str, cluster_id: str, aws_provider_uuid: str
    ) -> pd.DataFrame:
        """
        Run aggregation in-memory (loads all data at once).

        Faster but uses more memory. Best for smaller datasets.
        """
        with PerformanceTimer(
            f"OCP-AWS aggregation IN-MEMORY ({year}-{month})", self.logger
        ):
            # Phase 1: Load OCP data
            self.logger.info(
                "Phase 1: Loading OCP data",
                year=year,
                month=month,
                cluster_id=cluster_id,
            )
            ocp_data = self._load_ocp_data(year, month, cluster_id)

            # Phase 2: Load AWS data
            self.logger.info(
                "Phase 2: Loading AWS data",
                year=year,
                month=month,
                provider=aws_provider_uuid,
            )
            aws_data = self._load_aws_data(year, month, aws_provider_uuid)

            # Phase 3: Match resources by ID
            self.logger.info("Phase 3: Matching resources by ID")
            matched_aws = self._match_resources(aws_data, ocp_data)

            # Phase 4: Match resources by tags
            self.logger.info("Phase 4: Matching resources by tags")
            matched_aws = self._match_tags(matched_aws, ocp_data, cluster_id)

            # Phase 5: Calculate disk capacities
            self.logger.info("Phase 5: Calculating disk capacities")
            disk_capacities = self._calculate_disk_capacities(
                matched_aws, ocp_data["storage_usage"], year, month, aws_provider_uuid
            )

            # Phase 6: Attribute costs
            self.logger.info("Phase 6: Attributing costs to OCP")
            attributed = self._attribute_costs(ocp_data, matched_aws, disk_capacities)

            # Phase 7: Format output
            self.logger.info("Phase 7: Formatting output")
            final_output = self._format_output(
                attributed, cluster_id, self.cluster_alias, self.provider_uuid
            )

            # Log summary
            self.logger.info(
                "✓ OCP-AWS aggregation complete (IN-MEMORY)",
                output_rows=len(final_output),
                total_unblended_cost=final_output["unblended_cost"].sum()
                if "unblended_cost" in final_output.columns
                else 0,
                unique_namespaces=final_output["namespace"].nunique()
                if "namespace" in final_output.columns
                else 0,
                unique_nodes=final_output["node"].nunique()
                if "node" in final_output.columns
                else 0,
            )

            return final_output

    def _aggregate_streaming(
        self,
        year: str,
        month: str,
        cluster_id: str,
        aws_provider_uuid: str,
        db_writer=None,
        incremental_db_writes: bool = False,
    ) -> pd.DataFrame:
        """
        Run aggregation in streaming mode (processes OCP data in chunks).

        Uses bounded memory regardless of dataset size. AWS data is kept
        in memory (typically small), OCP data is processed in chunks.

        Args:
            year: Year to process
            month: Month to process
            cluster_id: OCP cluster ID
            aws_provider_uuid: AWS provider UUID
            db_writer: Optional DatabaseWriter for incremental writes
            incremental_db_writes: If True, write each chunk to DB immediately
        """
        import gc

        with PerformanceTimer(
            f"OCP-AWS aggregation STREAMING ({year}-{month})", self.logger
        ):
            # Phase 1: Load reference data (kept in memory - typically small)
            self.logger.info("Phase 1: Loading reference data (labels, AWS)")

            # Load labels (small, keep in memory)
            node_labels = self.parquet_reader.read_node_labels_line_items(
                provider_uuid=self.provider_uuid, year=year, month=month
            )
            namespace_labels = self.parquet_reader.read_namespace_labels_line_items(
                provider_uuid=self.provider_uuid, year=year, month=month
            )

            # Load storage usage (needed for disk capacity calculation)
            storage_usage = self.parquet_reader.read_storage_usage_line_items(
                provider_uuid=self.provider_uuid,
                year=year,
                month=month,
                streaming=False,
            )
            if not storage_usage.empty:
                if (
                    "cluster_id" not in storage_usage.columns
                    or storage_usage["cluster_id"].isnull().all()
                ):
                    storage_usage["cluster_id"] = cluster_id
                if (
                    "cluster_alias" not in storage_usage.columns
                    or storage_usage["cluster_alias"].isnull().all()
                ):
                    storage_usage["cluster_alias"] = self.cluster_alias

            # Phase 2: Load AWS data (typically small, keep in memory)
            self.logger.info(
                "Phase 2: Loading AWS data",
                year=year,
                month=month,
                provider=aws_provider_uuid,
            )
            aws_data = self._load_aws_data(year, month, aws_provider_uuid)

            # Phase 3: Get OCP pod usage as chunks (streaming)
            self.logger.info("Phase 3: Reading OCP pod usage in chunks")
            pod_chunks = self.parquet_reader.read_pod_usage_line_items(
                provider_uuid=self.provider_uuid,
                year=year,
                month=month,
                streaming=True,  # Returns iterator
                chunk_size=self.chunk_size,
            )

            # Prepare reference data dictionary for chunk processing
            reference_data = {
                "aws_data": aws_data,
                "storage_usage": storage_usage,
                "node_labels": node_labels,
                "namespace_labels": namespace_labels,
                "cluster_id": cluster_id,
                "cluster_alias": self.cluster_alias,
                "year": year,
                "month": month,
                "aws_provider_uuid": aws_provider_uuid,
            }

            # Phase 4-6: Process each chunk
            self.logger.info(
                "Phase 4-6: Processing OCP chunks with AWS matching and attribution"
            )

            # INCREMENTAL DB WRITES MODE
            # Instead of collecting all chunks in memory, write each chunk to DB immediately
            if incremental_db_writes and db_writer is not None:
                self.logger.info(
                    "Using INCREMENTAL DB WRITES (true memory-bounded streaming)"
                )

                streaming_db = db_writer.create_streaming_writer("ocp_aws")
                total_rows = 0

                with streaming_db:
                    for chunk_idx, chunk_df in enumerate(pod_chunks):
                        if chunk_df.empty:
                            continue

                        # Process this chunk
                        attributed = self._process_ocp_chunk(
                            chunk_df, reference_data, chunk_idx
                        )

                        if attributed is not None and not attributed.empty:
                            # Format and write immediately
                            formatted = self._format_output(
                                attributed,
                                cluster_id,
                                self.cluster_alias,
                                self.provider_uuid,
                            )
                            streaming_db.write_chunk(formatted)
                            total_rows += len(formatted)

                            # Free memory immediately
                            del formatted, attributed

                        del chunk_df
                        gc.collect()

                        self.logger.info(
                            f"Chunk {chunk_idx + 1} processed and written",
                            rows=total_rows,
                        )

                # Return empty DataFrame since data is already in DB
                self.logger.info(
                    "✓ OCP-AWS aggregation complete (STREAMING + INCREMENTAL DB)",
                    output_rows=total_rows,
                )
                return pd.DataFrame()  # Data already written to DB

            # STANDARD STREAMING MODE (collect in memory, write at end)
            processed_chunks = self.streaming_processor.process_chunks(
                chunks=pod_chunks,
                reference_data=reference_data,
                process_fn=self._process_ocp_chunk,
                timer_name="OCP-AWS chunk processing",
            )

            # Phase 7: Format output
            self.logger.info("Phase 7: Formatting output")
            if processed_chunks.empty:
                final_output = pd.DataFrame()
            else:
                final_output = self._format_output(
                    processed_chunks, cluster_id, self.cluster_alias, self.provider_uuid
                )

            # Clean up
            gc.collect()

            # Log summary
            self.logger.info(
                "✓ OCP-AWS aggregation complete (STREAMING)",
                output_rows=len(final_output),
                total_unblended_cost=final_output["unblended_cost"].sum()
                if "unblended_cost" in final_output.columns
                else 0,
                unique_namespaces=final_output["namespace"].nunique()
                if "namespace" in final_output.columns
                else 0,
                unique_nodes=final_output["node"].nunique()
                if "node" in final_output.columns
                else 0,
            )

            return final_output

    def _process_ocp_chunk(
        self, chunk_df: pd.DataFrame, reference_data: Dict[str, Any], chunk_idx: int
    ) -> pd.DataFrame:
        """
        Process a single OCP pod usage chunk.

        This is called by StreamingProcessor for each chunk. It:
        1. Adds cluster metadata to chunk
        2. Matches chunk with AWS data
        3. Attributes costs

        Args:
            chunk_df: OCP pod usage chunk
            reference_data: Reference data (AWS, labels, etc.)
            chunk_idx: Chunk index for logging

        Returns:
            Processed chunk with attributed costs
        """
        import gc

        if chunk_df.empty:
            return pd.DataFrame()

        # Extract reference data
        aws_data = reference_data["aws_data"]
        storage_usage = reference_data["storage_usage"]
        cluster_id = reference_data["cluster_id"]
        cluster_alias = reference_data["cluster_alias"]
        year = reference_data["year"]
        month = reference_data["month"]
        aws_provider_uuid = reference_data["aws_provider_uuid"]

        # Add cluster metadata to chunk
        if (
            "cluster_id" not in chunk_df.columns
            or chunk_df["cluster_id"].isnull().all()
        ):
            chunk_df["cluster_id"] = cluster_id
        if (
            "cluster_alias" not in chunk_df.columns
            or chunk_df["cluster_alias"].isnull().all()
        ):
            chunk_df["cluster_alias"] = cluster_alias

        # Create OCP data dict for this chunk
        ocp_chunk_data = {
            "pod_usage": chunk_df,
            "storage_usage": storage_usage,  # Full storage for disk capacity
            "node_labels": reference_data["node_labels"],
            "namespace_labels": reference_data["namespace_labels"],
        }

        # Match resources (uses chunk's pod data)
        # Note: We don't copy aws_data here to save memory. _match_resources
        # should not modify aws_data in place. If it does, we need to fix that.
        matched_aws = self._match_resources(aws_data, ocp_chunk_data)

        # Match tags
        matched_aws = self._match_tags(matched_aws, ocp_chunk_data, cluster_id)

        # Calculate disk capacities (uses storage from reference data)
        disk_capacities = self._calculate_disk_capacities(
            matched_aws, storage_usage, year, month, aws_provider_uuid
        )

        # Attribute costs
        attributed = self._attribute_costs(ocp_chunk_data, matched_aws, disk_capacities)

        # Clean up
        del ocp_chunk_data, matched_aws
        gc.collect()

        return attributed

    def _load_ocp_data(
        self, year: str, month: str, cluster_id: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Load all OCP data sources.

        Args:
            year: Year to load
            month: Month to load
            cluster_id: OCP cluster ID

        Returns:
            Dictionary containing:
                - 'pod_usage': Pod usage DataFrame
                - 'storage_usage': Storage usage DataFrame
                - 'node_labels': Node labels DataFrame
                - 'namespace_labels': Namespace labels DataFrame
        """
        with PerformanceTimer("Load OCP data", self.logger):
            # Load pod usage
            pod_usage = self.parquet_reader.read_pod_usage_line_items(
                provider_uuid=self.provider_uuid,
                year=year,
                month=month,
                streaming=False,  # OCP data is typically smaller
            )

            # Load storage usage
            storage_usage = self.parquet_reader.read_storage_usage_line_items(
                provider_uuid=self.provider_uuid,
                year=year,
                month=month,
                streaming=False,
            )

            # Load labels
            node_labels = self.parquet_reader.read_node_labels_line_items(
                provider_uuid=self.provider_uuid, year=year, month=month
            )

            namespace_labels = self.parquet_reader.read_namespace_labels_line_items(
                provider_uuid=self.provider_uuid, year=year, month=month
            )

            # Add cluster_id and cluster_alias to pod usage for tag matching
            # This is required for Trino parity (matches cluster-level tags)
            # CRITICAL: Do NOT overwrite cluster_id if it already exists (multi-cluster scenario)
            if not pod_usage.empty:
                if (
                    "cluster_id" not in pod_usage.columns
                    or pod_usage["cluster_id"].isnull().all()
                ):
                    pod_usage["cluster_id"] = cluster_id
                    self.logger.info(f"Added cluster_id to pod_usage: {cluster_id}")
                else:
                    unique_clusters = pod_usage["cluster_id"].unique()
                    self.logger.info(
                        f"Preserving existing cluster_id(s) in pod_usage: {list(unique_clusters)}"
                    )

                if (
                    "cluster_alias" not in pod_usage.columns
                    or pod_usage["cluster_alias"].isnull().all()
                ):
                    pod_usage["cluster_alias"] = self.cluster_alias

            if not storage_usage.empty:
                if (
                    "cluster_id" not in storage_usage.columns
                    or storage_usage["cluster_id"].isnull().all()
                ):
                    storage_usage["cluster_id"] = cluster_id
                    self.logger.info(f"Added cluster_id to storage_usage: {cluster_id}")
                else:
                    unique_clusters = storage_usage["cluster_id"].unique()
                    self.logger.info(
                        f"Preserving existing cluster_id(s) in storage_usage: {list(unique_clusters)}"
                    )

                if (
                    "cluster_alias" not in storage_usage.columns
                    or storage_usage["cluster_alias"].isnull().all()
                ):
                    storage_usage["cluster_alias"] = self.cluster_alias

            self.logger.info(
                "✓ Loaded OCP data",
                pod_usage_rows=len(pod_usage),
                storage_usage_rows=len(storage_usage),
                node_labels_rows=len(node_labels),
                namespace_labels_rows=len(namespace_labels),
            )

            return {
                "pod_usage": pod_usage,
                "storage_usage": storage_usage,
                "node_labels": node_labels,
                "namespace_labels": namespace_labels,
            }

    def _load_aws_data(self, year: str, month: str, provider_uuid: str) -> pd.DataFrame:
        """
        Load AWS Cost and Usage Report data.

        Args:
            year: Year to load
            month: Month to load
            provider_uuid: AWS provider UUID

        Returns:
            AWS CUR DataFrame
        """
        with PerformanceTimer("Load AWS data", self.logger):
            # Load daily AWS data for matching
            # NOTE: AWS data is typically small (~100-1000 rows), so we always
            # load it in-memory (no streaming) regardless of use_streaming setting
            aws_data = self.aws_loader.read_aws_line_items_for_matching(
                provider_uuid=provider_uuid, year=year, month=month
            )

            self.logger.info(
                "✓ Loaded AWS data",
                rows=len(aws_data),
                unique_resources=aws_data["lineitem_resourceid"].nunique()
                if "lineitem_resourceid" in aws_data.columns
                else 0,
            )

            return aws_data

    def _match_resources(
        self, aws_df: pd.DataFrame, ocp_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Match AWS resources to OCP by resource ID.

        Args:
            aws_df: AWS CUR DataFrame
            ocp_data: Dictionary of OCP DataFrames

        Returns:
            AWS DataFrame with resource_id_matched column
        """
        with PerformanceTimer("Resource ID matching", self.logger):
            # Extract OCP resource IDs
            ocp_resource_ids = self.resource_matcher.extract_ocp_resource_ids(
                pod_usage_df=ocp_data["pod_usage"],
                storage_usage_df=ocp_data["storage_usage"],
            )

            # Match
            matched_aws = self.resource_matcher.match_by_resource_id(
                aws_df=aws_df, ocp_resource_ids=ocp_resource_ids
            )

            # Validate
            self.resource_matcher.validate_matching_results(matched_aws)

            # Log summary
            summary = self.resource_matcher.get_matched_resources_summary(matched_aws)
            self.logger.info("✓ Resource ID matching complete", **summary)

            # DEBUG: Check for cost columns after matching
            cost_cols = [c for c in matched_aws.columns if "cost" in c.lower()]
            cost_sum = (
                matched_aws["lineitem_unblendedcost"].sum()
                if "lineitem_unblendedcost" in matched_aws.columns
                else 0
            )
            self.logger.info(
                "DEBUG: After resource ID matching",
                matched_rows=len(matched_aws),
                cost_columns=cost_cols[:5],  # Show first 5
                lineitem_unblendedcost_sum=cost_sum,
                has_lineitem_unblendedcost="lineitem_unblendedcost"
                in matched_aws.columns,
            )

            return matched_aws

    def _match_tags(
        self, aws_df: pd.DataFrame, ocp_data: Dict[str, pd.DataFrame], cluster_id: str
    ) -> pd.DataFrame:
        """
        Match AWS resources to OCP by tags.

        Args:
            aws_df: AWS DataFrame (already has resource_id_matched column)
            ocp_data: Dictionary of OCP DataFrames
            cluster_id: OCP cluster ID

        Returns:
            AWS DataFrame with tag_matched and matched_tag columns
        """
        with PerformanceTimer("Tag matching", self.logger):
            # Extract OCP tag values (includes cluster_id, cluster_alias, pod_labels, volume_labels)
            ocp_tag_values = self.tag_matcher.extract_ocp_tag_values(
                cluster_id=cluster_id,
                pod_usage_df=ocp_data["pod_usage"],
                storage_usage_df=ocp_data.get(
                    "storage_usage"
                ),  # For volume_labels extraction
                cluster_alias=self.cluster_alias,  # For cluster_alias matching
            )

            # Get enabled keys from PostgreSQL
            # (In production, this would query the database)
            # For POC, we use the configured keys
            enabled_keys = set(self.enabled_tag_keys) if self.enabled_tag_keys else None

            # Match (skips resources already matched by resource_id)
            tagged_aws = self.tag_matcher.match_by_tags(
                aws_df=aws_df, ocp_tag_values=ocp_tag_values, enabled_keys=enabled_keys
            )

            # Validate
            self.tag_matcher.validate_tag_matching_results(tagged_aws)

            # Log summary
            summary = self.tag_matcher.get_tag_matching_summary(tagged_aws)
            self.logger.info("✓ Tag matching complete", **summary)

            return tagged_aws

    def _calculate_disk_capacities(
        self,
        matched_aws_df: pd.DataFrame,
        ocp_storage_usage: pd.DataFrame,
        year: str,
        month: str,
        provider_uuid: str,
    ) -> pd.DataFrame:
        """
        Calculate EBS volume capacities.

        Args:
            matched_aws_df: Matched AWS DataFrame
            ocp_storage_usage: OCP storage usage DataFrame
            year: Year
            month: Month
            provider_uuid: AWS provider UUID

        Returns:
            DataFrame with resource_id, capacity, usage_start columns
        """
        with PerformanceTimer("Disk capacity calculation", self.logger):
            # If matched AWS data is empty, nothing to calculate
            if matched_aws_df.empty:
                self.logger.info(
                    "No matched AWS data, skipping disk capacity calculation"
                )
                return pd.DataFrame(columns=["resource_id", "capacity", "usage_start"])

            # Extract CSI volume handles from OCP storage
            csi_handles = self.disk_calculator.extract_matched_volumes(
                ocp_storage_usage
            )

            if not csi_handles:
                self.logger.info("No storage volumes to calculate capacity for")
                return pd.DataFrame(columns=["resource_id", "capacity", "usage_start"])

            self.logger.info(
                f"Found {len(csi_handles)} CSI volume handles for capacity calculation",
                csi_handles=list(csi_handles),
            )

            # Filter matched AWS data to only storage volumes
            # Nise generates EBS with ProductCode=AmazonEC2 and UsageType contains "EBS:"
            # Also match by resource ID (use suffix matching like koku does)
            is_ebs_by_usage = matched_aws_df["lineitem_usagetype"].str.contains(
                "EBS:", na=False
            )
            is_ebs_by_product = matched_aws_df["lineitem_productcode"] == "AmazonEBS"

            # Use matched_resource_id if available (set by resource matcher)
            # Otherwise use suffix matching on lineitem_resourceid
            if "matched_resource_id" in matched_aws_df.columns:
                is_matched_by_resource_id = matched_aws_df["matched_resource_id"].isin(
                    csi_handles
                )
                self.logger.debug("Using matched_resource_id for CSI handle matching")
            else:
                # Fallback: suffix matching on lineitem_resourceid
                def matches_csi_handle_suffix(resource_id):
                    if pd.isna(resource_id):
                        return False
                    resource_id_str = str(resource_id)
                    for handle in csi_handles:
                        if resource_id_str.endswith(handle):
                            return True
                    return False

                is_matched_by_resource_id = matched_aws_df["lineitem_resourceid"].apply(
                    matches_csi_handle_suffix
                )
                self.logger.debug(
                    "Using suffix matching on lineitem_resourceid for CSI handle matching"
                )

            storage_aws = matched_aws_df[
                is_ebs_by_usage | is_ebs_by_product | is_matched_by_resource_id
            ].copy()

            self.logger.info(
                f"Filtered AWS data for storage volumes",
                by_usage_type=is_ebs_by_usage.sum(),
                by_product_code=is_ebs_by_product.sum(),
                by_resource_id=is_matched_by_resource_id.sum(),
                total_storage_rows=len(storage_aws),
            )

            if storage_aws.empty:
                self.logger.warning(
                    "No AWS storage line items found for matched volumes"
                )
                return pd.DataFrame(columns=["resource_id", "capacity", "usage_start"])

            # Calculate capacities
            capacities = self.disk_calculator.calculate_disk_capacities(
                aws_line_items_df=storage_aws,
                ocp_storage_usage_df=ocp_storage_usage,
                year=int(year),
                month=int(month),
            )

            # Validate
            if not capacities.empty:
                self.disk_calculator.validate_capacities(capacities)

            # Log summary
            summary = self.disk_calculator.get_capacity_summary(capacities)
            self.logger.info("✓ Disk capacity calculation complete", **summary)

            return capacities

    def _attribute_costs(
        self,
        ocp_data: Dict[str, pd.DataFrame],
        matched_aws_df: pd.DataFrame,
        disk_capacities: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Attribute AWS costs to OCP pods/namespaces.

        Handles three types of costs:
        1. Compute costs (regular attribution to namespaces)
        2. Network costs (attributed to "Network unattributed" namespace)
        3. Storage costs (TODO: Future implementation)

        Args:
            ocp_data: Dictionary of OCP DataFrames
            matched_aws_df: Matched AWS DataFrame
            disk_capacities: Disk capacities DataFrame

        Returns:
            DataFrame with attributed costs
        """
        with PerformanceTimer("Cost attribution", self.logger):
            # DEBUG: Check cost before attribution
            cost_sum_before = (
                matched_aws_df["lineitem_unblendedcost"].sum()
                if "lineitem_unblendedcost" in matched_aws_df.columns
                else 0
            )
            self.logger.info(
                "DEBUG: Before cost attribution",
                matched_aws_rows=len(matched_aws_df),
                lineitem_unblendedcost_sum=cost_sum_before,
                has_cost_column="lineitem_unblendedcost" in matched_aws_df.columns,
            )

            # Separate network costs from regular costs
            # Network costs are handled differently (assigned to "Network unattributed" namespace)
            non_network_aws, network_aws = self.network_handler.filter_network_costs(
                matched_aws_df
            )

            # DEBUG: Check cost after network filtering
            cost_sum_non_network = (
                non_network_aws["lineitem_unblendedcost"].sum()
                if "lineitem_unblendedcost" in non_network_aws.columns
                else 0
            )
            self.logger.info(
                "DEBUG: After network filtering",
                non_network_rows=len(non_network_aws),
                network_rows=len(network_aws),
                non_network_cost_sum=cost_sum_non_network,
            )

            # Attribute regular compute costs (pods on nodes)
            # Excludes network costs (data_transfer_direction IS NULL)
            # SCENARIO 19 FIX: Also exclude EBS storage from compute attribution
            # EBS storage is handled separately by attribute_storage_costs and attribute_tag_matched_storage
            compute_aws = non_network_aws.copy()
            if "lineitem_usagetype" in compute_aws.columns:
                # Filter out EBS storage - only keep EC2 instance costs for compute attribution
                is_ebs = compute_aws["lineitem_usagetype"].str.contains(
                    "EBS:", na=False
                )
                compute_aws = compute_aws[~is_ebs]
                self.logger.info(
                    f"Filtered EBS from compute attribution: {is_ebs.sum()} EBS rows excluded, {len(compute_aws)} compute rows remaining"
                )

            compute_attributed = self.cost_attributor.attribute_compute_costs(
                ocp_pod_usage_df=ocp_data["pod_usage"],
                aws_matched_df=compute_aws,  # Only non-network, non-EBS costs
            )

            self.logger.info(
                "✓ Computed compute cost attribution", rows=len(compute_attributed)
            )

            # Attribute network costs to "Network unattributed" namespace
            # Groups by node and data_transfer_direction
            network_attributed = self.network_handler.attribute_network_costs(
                network_df=network_aws, ocp_pod_usage_df=ocp_data["pod_usage"]
            )

            if not network_attributed.empty:
                self.logger.info(
                    "✓ Computed network cost attribution",
                    rows=len(network_attributed),
                    unique_nodes=network_attributed["node"].nunique(),
                )

            # Attribute storage costs (PVCs on volumes) - CSI-based
            storage_attributed = self.cost_attributor.attribute_storage_costs(
                ocp_storage_usage_df=ocp_data["storage_usage"],
                matched_aws_df=matched_aws_df,
                disk_capacities=disk_capacities,
            )

            if not storage_attributed.empty:
                self.logger.info(
                    "✓ Computed CSI storage cost attribution",
                    rows=len(storage_attributed),
                    unique_namespaces=storage_attributed["namespace"].nunique(),
                )

            # Track which resource_ids have been attributed
            csi_attributed_resource_ids = set()
            tag_attributed_resource_ids = set()

            # Get resource_ids from CSI-attributed storage
            if (
                not storage_attributed.empty
                and "resource_id" in storage_attributed.columns
            ):
                csi_attributed_resource_ids = set(
                    storage_attributed["resource_id"].dropna().unique()
                )

            # Attribute tag-matched storage costs (non-CSI - openshift_project tag)
            # SCENARIO 19 FIX: EBS volumes tagged with openshift_project but no CSI handle
            tag_matched_storage = self.cost_attributor.attribute_tag_matched_storage(
                matched_aws_df=matched_aws_df
            )

            if not tag_matched_storage.empty:
                self.logger.info(
                    "✓ Computed tag-matched storage cost attribution",
                    rows=len(tag_matched_storage),
                    unique_namespaces=tag_matched_storage["namespace"].nunique(),
                )
                # Track tag-attributed resource_ids (from matched_ocp_namespace)
                if "lineitem_resourceid" in matched_aws_df.columns:
                    tag_matched_rows = matched_aws_df[
                        matched_aws_df.get("matched_ocp_namespace", pd.Series([""]))
                        .fillna("")
                        .astype(str)
                        .str.len()
                        > 0
                    ]
                    tag_attributed_resource_ids = set(
                        tag_matched_rows["lineitem_resourceid"].unique()
                    )

            # Attribute untagged storage costs (EBS matched but no openshift_project tag)
            # SCENARIO 19 FIX: EBS volumes without openshift_project tags → "Storage unattributed"
            # Only attribute untagged storage when there's an OCP context (pod_usage or storage_usage)
            untagged_storage = pd.DataFrame()
            has_ocp_context = (
                not ocp_data["pod_usage"].empty or not ocp_data["storage_usage"].empty
            )
            if has_ocp_context:
                untagged_storage = self.cost_attributor.attribute_untagged_storage(
                    matched_aws_df=matched_aws_df,
                    csi_attributed_resource_ids=csi_attributed_resource_ids,
                    tag_attributed_resource_ids=tag_attributed_resource_ids,
                )

                if not untagged_storage.empty:
                    self.logger.info(
                        "✓ Computed untagged storage cost attribution",
                        rows=len(untagged_storage),
                        total_cost=f"${untagged_storage['unblended_cost'].sum():,.2f}",
                    )

            # Combine compute + network + storage costs
            # BUGFIX: Normalize all timestamps to timezone-naive before concat to prevent mixing tz-aware/naive
            def normalize_timestamps(df):
                """Ensure all datetime columns are timezone-naive."""
                if df.empty:
                    return df
                df = df.copy()
                for col in [
                    "usage_start",
                    "usage_end",
                    "lineitem_usagestartdate",
                    "lineitem_usageenddate",
                ]:
                    if col in df.columns and pd.api.types.is_datetime64tz_dtype(
                        df[col]
                    ):
                        df[col] = df[col].dt.tz_localize(None)
                return df

            frames_to_combine = [normalize_timestamps(compute_attributed)]
            if not network_attributed.empty:
                frames_to_combine.append(normalize_timestamps(network_attributed))
            if not storage_attributed.empty:
                frames_to_combine.append(normalize_timestamps(storage_attributed))
            if not tag_matched_storage.empty:
                frames_to_combine.append(normalize_timestamps(tag_matched_storage))
            if not untagged_storage.empty:
                frames_to_combine.append(normalize_timestamps(untagged_storage))

            combined = (
                pd.concat(frames_to_combine, ignore_index=True)
                if len(frames_to_combine) > 1
                else compute_attributed
            )

            # Log summary
            summary = self.cost_attributor.get_cost_summary(compute_attributed)
            if not network_attributed.empty:
                network_summary = self.network_handler.get_network_summary(
                    network_attributed
                )
                summary["network_costs"] = network_summary
            self.logger.info("✓ Cost attribution complete", **summary)

            return combined

    def _format_output(
        self,
        attributed_df: pd.DataFrame,
        cluster_id: str,
        cluster_alias: str,
        source_uuid: str,
    ) -> pd.DataFrame:
        """
        Format output to match PostgreSQL schema.

        Args:
            attributed_df: Attributed costs DataFrame
            cluster_id: OCP cluster ID
            cluster_alias: OCP cluster alias
            source_uuid: OCP source UUID

        Returns:
            DataFrame ready for PostgreSQL insert
        """
        with PerformanceTimer("Output formatting", self.logger):
            # Make a copy to avoid modifying the input
            output_df = attributed_df.copy()

            # BUGFIX: Normalize all timestamp columns to timezone-naive
            # This prevents "Cannot mix tz-aware with tz-naive values" errors
            # Handle mixed timezone data by processing element-wise
            def normalize_mixed_timezones(series):
                """Convert a series with mixed tz-aware/tz-naive datetimes to tz-naive."""

                def normalize_value(val):
                    if pd.isna(val):
                        return val
                    if hasattr(val, "tz") and val.tz is not None:
                        # tz-aware: remove timezone
                        return val.tz_localize(None)
                    return val

                return series.apply(normalize_value)

            for col in [
                "usage_start",
                "usage_end",
                "lineitem_usagestartdate",
                "lineitem_usageenddate",
            ]:
                if col in output_df.columns:
                    col_dtype = output_df[col].dtype
                    if pd.api.types.is_datetime64tz_dtype(col_dtype):
                        # Entire column is tz-aware: use vectorized operation
                        output_df[col] = output_df[col].dt.tz_localize(None)
                    elif pd.api.types.is_datetime64_any_dtype(col_dtype):
                        # Column might have mixed timezones: process element-wise
                        output_df[col] = normalize_mixed_timezones(output_df[col])
                    elif col_dtype == "object":
                        # Object dtype: might contain datetime objects with mixed timezones
                        # Convert to datetime first, then normalize
                        try:
                            output_df[col] = pd.to_datetime(
                                output_df[col], utc=True
                            ).dt.tz_localize(None)
                        except Exception:
                            # If conversion fails, try element-wise normalization
                            output_df[col] = normalize_mixed_timezones(output_df[col])

            # Generate UUIDs for each row
            output_df["uuid"] = [str(uuid_lib.uuid4()) for _ in range(len(output_df))]

            # Add metadata columns
            # BUGFIX: Only set cluster_id if not already present (multi-cluster support)
            # In multi-cluster scenarios, attributed_df already has correct cluster_id per row
            if (
                "cluster_id" not in output_df.columns
                or output_df["cluster_id"].isnull().all()
            ):
                output_df["cluster_id"] = cluster_id
            else:
                self.logger.info(
                    "Preserving existing cluster_id from data",
                    clusters=sorted(output_df["cluster_id"].dropna().unique().tolist()),
                )

            output_df["cluster_alias"] = cluster_alias
            output_df["source_uuid"] = source_uuid
            output_df["report_period_id"] = self.report_period_id
            output_df["cost_entry_bill_id"] = self.cost_entry_bill_id

            # Map usage_start (hourly timestamp) to usage_start/usage_end dates
            if "usage_start" in output_df.columns:
                # Convert hourly timestamp to date (Koku uses same date for both start and end)
                usage_date = pd.to_datetime(output_df["usage_start"]).dt.date
                output_df["usage_start"] = usage_date
                output_df["usage_end"] = usage_date
            elif "usage_date" in output_df.columns:
                # Fallback: handle old 'usage_date' column if present
                output_df["usage_start"] = pd.to_datetime(
                    output_df["usage_date"]
                ).dt.date
                output_df["usage_end"] = pd.to_datetime(output_df["usage_date"]).dt.date

            # Ensure required columns exist (with defaults)
            required_columns = {
                "uuid": None,
                "report_period_id": None,
                "cluster_id": None,
                "cluster_alias": None,
                "data_source": "Pod",  # Default to Pod
                "namespace": "",
                "node": "",
                "persistentvolumeclaim": "",
                "persistentvolume": "",
                "storageclass": "",
                "resource_id": "",
                "usage_start": None,
                "usage_end": None,
                "product_code": "",
                "product_family": "",
                "instance_type": "",
                "cost_entry_bill_id": None,
                "usage_account_id": "",
                "account_alias_id": None,
                "availability_zone": "",
                "region": "",
                "unit": "",
                "usage_amount": 0.0,
                "data_transfer_direction": "",
                "currency_code": "USD",
                "unblended_cost": 0.0,
                "markup_cost": 0.0,
                "blended_cost": 0.0,
                "markup_cost_blended": 0.0,
                "savingsplan_effective_cost": 0.0,
                "markup_cost_savingsplan": 0.0,
                "calculated_amortized_cost": 0.0,
                "markup_cost_amortized": 0.0,
                "pod_labels": {},  # JSON object, not string
                "tags": {},  # JSON object, not string
                "aws_cost_category": {},  # JSON object, not string
                "source_uuid": None,
            }

            # Fill missing columns with defaults
            for col, default_value in required_columns.items():
                if col not in output_df.columns:
                    output_df[col] = default_value

            # Select columns in the correct order
            final_columns = list(required_columns.keys())
            output_df = output_df[final_columns]

            # Convert categorical columns to object type before fillna
            # (fillna with new values fails on Categorical dtypes)
            for col in output_df.columns:
                if isinstance(output_df[col].dtype, pd.CategoricalDtype):
                    output_df[col] = output_df[col].astype("object")

            # Replace NaN with appropriate defaults
            output_df = output_df.fillna(
                {
                    "namespace": "",
                    "node": "",
                    "persistentvolumeclaim": "",
                    "persistentvolume": "",
                    "storageclass": "",
                    "resource_id": "",
                    "product_code": "",
                    "product_family": "",
                    "instance_type": "",
                    "usage_account_id": "",
                    "availability_zone": "",
                    "region": "",
                    "unit": "",
                    "data_transfer_direction": "",
                    "pod_labels": "{}",  # JSON string, not dict
                    "tags": "{}",  # JSON string, not dict
                    "aws_cost_category": "{}",  # JSON string, not dict
                    "usage_amount": 0.0,
                    "unblended_cost": 0.0,
                    "markup_cost": 0.0,
                    "blended_cost": 0.0,
                    "markup_cost_blended": 0.0,
                    "savingsplan_effective_cost": 0.0,
                    "markup_cost_savingsplan": 0.0,
                    "calculated_amortized_cost": 0.0,
                    "markup_cost_amortized": 0.0,
                }
            )

            self.logger.info(
                "✓ Output formatted",
                rows=len(output_df),
                columns=len(output_df.columns),
            )

            return output_df

    def get_pipeline_summary(self) -> Dict:
        """
        Get a summary of the aggregation pipeline configuration.

        Returns:
            Dictionary with pipeline configuration
        """
        return {
            "cluster_id": self.cluster_id,
            "cluster_alias": self.cluster_alias,
            "ocp_provider_uuid": self.provider_uuid,
            "aws_provider_uuid": self.aws_provider_uuid,
            "markup_percent": self.markup_percent,
            "enabled_tag_keys_count": len(self.enabled_tag_keys),
            "streaming_enabled": self.use_streaming,
            "chunk_size": self.chunk_size if self.use_streaming else None,
        }
