"""OCP Pod usage aggregation logic (replicates Trino SQL)."""

import uuid as uuid_lib
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .utils import (
    PerformanceTimer,
    coalesce,
    convert_bytes_to_gigabytes,
    convert_seconds_to_hours,
    filter_labels_by_enabled_keys,
    get_logger,
    labels_to_json_string,
    merge_label_dicts,
    parse_json_labels,
    safe_greatest,
)

# Try to import Arrow compute (optional high-performance dependency)
try:
    from .arrow_compute import ARROW_COMPUTE_AVAILABLE, get_arrow_processor

    ARROW_AVAILABLE = ARROW_COMPUTE_AVAILABLE
except ImportError:
    ARROW_AVAILABLE = False
    get_arrow_processor = None


class PodAggregator:
    """Aggregate OCP pod usage data (replicates Trino SQL lines 260-316)."""

    def __init__(self, config: Dict, enabled_tag_keys: List[str]):
        """Initialize pod aggregator.

        Args:
            config: Configuration dictionary
            enabled_tag_keys: List of enabled tag keys from PostgreSQL
        """
        self.config = config
        self.enabled_tag_keys = enabled_tag_keys
        self.logger = get_logger("aggregator_pod")

        # OCP configuration
        self.ocp_config = config["ocp"]
        self.report_period_id = self.ocp_config["report_period_id"]
        self.cluster_id = self.ocp_config["cluster_id"]
        self.cluster_alias = self.ocp_config["cluster_alias"]
        self.provider_uuid = self.ocp_config["provider_uuid"]

        # Performance configuration
        self.use_arrow = config.get("performance", {}).get("use_arrow_compute", False) and ARROW_AVAILABLE
        if self.use_arrow:
            self.arrow_processor = get_arrow_processor()
            self.logger.info("✓ Arrow compute enabled (10-100x faster label processing)")
        else:
            self.arrow_processor = None
            if config.get("performance", {}).get("use_arrow_compute", False) and not ARROW_AVAILABLE:
                self.logger.warning("Arrow compute requested but not available, using fallback")

        self.logger.info(
            "Initialized pod aggregator",
            cluster_id=self.cluster_id,
            enabled_tags_count=len(enabled_tag_keys),
            arrow_compute=self.use_arrow,
        )

    def aggregate(
        self,
        pod_usage_df: pd.DataFrame,
        node_capacity_df: pd.DataFrame,
        node_labels_df: Optional[pd.DataFrame] = None,
        namespace_labels_df: Optional[pd.DataFrame] = None,
        cost_category_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Aggregate pod usage data by day + namespace + node.

        This replicates the main SELECT in Trino SQL (lines 260-316).

        Args:
            pod_usage_df: openshift_pod_usage_line_items_daily
            node_capacity_df: Pre-calculated node capacity by day
            node_labels_df: openshift_node_labels_line_items_daily (optional)
            namespace_labels_df: openshift_namespace_labels_line_items_daily (optional)
            cost_category_df: reporting_ocp_cost_category_namespace (optional)

        Returns:
            Aggregated DataFrame ready for PostgreSQL insert
        """
        print("🚀🚀🚀 ENTERING aggregate() - BEFORE ANY PROCESSING", flush=True)
        self.logger.info(
            "🚀 ENTERING aggregate() method",
            pod_usage_rows=len(pod_usage_df),
            node_capacity_rows=len(node_capacity_df),
            node_labels_rows=len(node_labels_df) if node_labels_df is not None else 0,
            namespace_labels_rows=len(namespace_labels_df) if namespace_labels_df is not None else 0,
        )
        with PerformanceTimer("Pod usage aggregation", self.logger):
            # Step 1: Pre-process labels
            self.logger.info(f"Step 1: Preparing pod usage data (rows={len(pod_usage_df)})")
            pod_usage_df = self._prepare_pod_usage_data(pod_usage_df)
            self.logger.info(f"✓ Pod usage prepared (rows={len(pod_usage_df)})")

            # Step 2: Join with node labels
            if node_labels_df is not None and not node_labels_df.empty:
                self.logger.info(
                    f"Step 2: Joining node labels (pod_rows={len(pod_usage_df)}, "
                    f"node_label_rows={len(node_labels_df)})"
                )
                pod_usage_df = self._join_node_labels(pod_usage_df, node_labels_df)
                self.logger.info(f"✓ Node labels joined (result_rows={len(pod_usage_df)})")
            else:
                # No node labels - use empty JSON object (not None to avoid NaN issues)
                pod_usage_df["node_labels"] = "{}"

            # Step 3: Join with namespace labels
            if namespace_labels_df is not None and not namespace_labels_df.empty:
                self.logger.info(
                    f"Step 3: Joining namespace labels (pod_rows={len(pod_usage_df)}, "
                    f"namespace_label_rows={len(namespace_labels_df)})"
                )
                pod_usage_df = self._join_namespace_labels(pod_usage_df, namespace_labels_df)
                self.logger.info(f"✓ Namespace labels joined (result_rows={len(pod_usage_df)})")
            else:
                # No namespace labels - use empty JSON object (not None to avoid NaN issues)
                pod_usage_df["namespace_labels"] = "{}"

            # Step 4-6: Process labels (parse, merge, convert to JSON)
            # Use Arrow compute if available (10-100x faster), otherwise list comprehension (3-5x faster)
            self.logger.info(
                f"Step 4-6: Processing labels (rows={len(pod_usage_df)}, "
                f"method={'Arrow' if self.use_arrow else 'List comprehension'})"
            )

            label_results = self._process_labels_optimized(pod_usage_df)

            # Add processed label columns to DataFrame
            pod_usage_df["node_labels_dict"] = label_results["node_labels_dict"]
            pod_usage_df["namespace_labels_dict"] = label_results["namespace_labels_dict"]
            pod_usage_df["pod_labels_dict"] = label_results["pod_labels_dict"]
            pod_usage_df["merged_labels_dict"] = label_results["merged_labels_dict"]
            pod_usage_df["merged_labels"] = label_results["merged_labels"]

            self.logger.info("✓ Labels processed")

            # Step 7: Group and aggregate
            aggregated_df = self._group_and_aggregate(pod_usage_df)

            # Step 6: Join with node capacity
            aggregated_df = self._join_node_capacity(aggregated_df, node_capacity_df)

            # Step 7: Join with cost category (if available)
            if cost_category_df is not None and not cost_category_df.empty:
                aggregated_df = self._join_cost_category(aggregated_df, cost_category_df)
            else:
                aggregated_df["cost_category_id"] = None

            # Step 8: Format final output
            result_df = self._format_output(aggregated_df)

            self.logger.info(
                f"Pod aggregation complete (input_rows={len(pod_usage_df)}, output_rows={len(result_df)})"
            )

            return result_df

    def _process_single_chunk(self, chunk_data: tuple) -> pd.DataFrame:
        """Process a single chunk of pod usage data.

        This method is used for parallel chunk processing. It's extracted as a separate
        method so it can be called by worker threads/processes.

        Args:
            chunk_data: Tuple of (chunk_idx, chunk_df, node_labels_df, namespace_labels_df)

        Returns:
            Aggregated DataFrame for this chunk
        """
        import gc

        chunk_idx, chunk_df, node_labels_df, namespace_labels_df = chunk_data

        try:
            # Process this chunk using same logic as aggregate()
            chunk_prepared = self._prepare_pod_usage_data(chunk_df)

            # Join with labels
            if node_labels_df is not None and not node_labels_df.empty:
                chunk_prepared = self._join_node_labels(chunk_prepared, node_labels_df)
            else:
                # No node labels - use empty JSON object (not None to avoid NaN issues)
                chunk_prepared["node_labels"] = "{}"

            if namespace_labels_df is not None and not namespace_labels_df.empty:
                chunk_prepared = self._join_namespace_labels(chunk_prepared, namespace_labels_df)
            else:
                # No namespace labels - use empty JSON object (not None to avoid NaN issues)
                chunk_prepared["namespace_labels"] = "{}"

            # Parse and merge labels using optimized method
            # (Arrow compute if available, otherwise list comprehension)
            label_results = self._process_labels_optimized(chunk_prepared)
            chunk_prepared["node_labels_dict"] = label_results["node_labels_dict"]
            chunk_prepared["namespace_labels_dict"] = label_results["namespace_labels_dict"]
            chunk_prepared["pod_labels_dict"] = label_results["pod_labels_dict"]
            chunk_prepared["merged_labels_dict"] = label_results["merged_labels_dict"]
            chunk_prepared["merged_labels"] = label_results["merged_labels"]

            # Aggregate this chunk
            chunk_aggregated = self._group_and_aggregate(chunk_prepared)

            # Free memory immediately
            del chunk_df, chunk_prepared
            gc.collect()

            return chunk_aggregated

        except Exception as e:
            self.logger.error(f"Failed to process chunk {chunk_idx}: {e}")
            raise

    def aggregate_streaming(
        self,
        pod_usage_chunks,  # Iterator[pd.DataFrame]
        node_capacity_df: pd.DataFrame,
        node_labels_df: Optional[pd.DataFrame] = None,
        namespace_labels_df: Optional[pd.DataFrame] = None,
        cost_category_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Aggregate pod usage data in chunks (streaming mode for constant memory).

        This processes data in chunks to maintain constant memory usage regardless
        of dataset size. Each chunk is processed independently and then combined.

        Supports both serial and parallel chunk processing based on config.

        Args:
            pod_usage_chunks: Iterator of DataFrame chunks
            node_capacity_df: Pre-calculated node capacity by day
            node_labels_df: openshift_node_labels_line_items_daily (optional)
            namespace_labels_df: openshift_namespace_labels_line_items_daily (optional)
            cost_category_df: reporting_ocp_cost_category_namespace (optional)

        Returns:
            Aggregated DataFrame ready for PostgreSQL insert
        """
        import gc
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Check if parallel processing is enabled
        parallel_enabled = self.config.get("performance", {}).get("parallel_chunks", False)
        max_workers = self.config.get("performance", {}).get("max_workers", 4)

        with PerformanceTimer("Pod usage aggregation (streaming mode)", self.logger):
            aggregated_chunks = []
            total_input_rows = 0
            chunk_count = 0

            if parallel_enabled:
                # PARALLEL PROCESSING: Process multiple chunks simultaneously
                self.logger.info(f"Using parallel chunk processing (workers={max_workers})")

                # Collect chunks from iterator first (needed for parallel processing)
                chunk_list = list(pod_usage_chunks)
                total_input_rows = sum(len(chunk) for chunk in chunk_list)
                chunk_count = len(chunk_list)

                self.logger.info(
                    f"Collected {chunk_count} chunks for parallel processing",
                    total_rows=total_input_rows,
                )

                # Prepare chunk data tuples
                chunk_data_list = [
                    (idx, chunk, node_labels_df, namespace_labels_df) for idx, chunk in enumerate(chunk_list)
                ]

                # Process chunks in parallel
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all chunks for processing
                    future_to_chunk = {
                        executor.submit(self._process_single_chunk, chunk_data): chunk_data[0]
                        for chunk_data in chunk_data_list
                    }

                    # Collect results as they complete
                    for future in as_completed(future_to_chunk):
                        chunk_idx = future_to_chunk[future]
                        try:
                            chunk_aggregated = future.result()
                            aggregated_chunks.append(chunk_aggregated)

                            self.logger.info(
                                f"Chunk {chunk_idx + 1}/{chunk_count} completed (output_rows={len(chunk_aggregated)})"
                            )
                        except Exception as e:
                            self.logger.error(f"Chunk {chunk_idx} failed (error={e})")
                            raise

                del chunk_list, chunk_data_list
                gc.collect()

            else:
                # SERIAL PROCESSING: Process one chunk at a time (original logic)
                self.logger.info("Using serial chunk processing (single-threaded)")

                for chunk_idx, chunk_df in enumerate(pod_usage_chunks):
                    chunk_count += 1
                    total_input_rows += len(chunk_df)

                    self.logger.info(
                        f"Processing chunk {chunk_count} (rows={len(chunk_df)}, cumulative_rows={total_input_rows})"
                    )

                    # Process chunk
                    chunk_data = (
                        chunk_idx,
                        chunk_df,
                        node_labels_df,
                        namespace_labels_df,
                    )
                    chunk_aggregated = self._process_single_chunk(chunk_data)
                    aggregated_chunks.append(chunk_aggregated)

                    self.logger.debug(
                        f"Chunk {chunk_count} aggregated (output_rows={len(chunk_aggregated)})"
                    )

            self.logger.info(
                f"All chunks processed (chunks={chunk_count}, total_input_rows={total_input_rows})"
            )

            # Combine all aggregated chunks
            if not aggregated_chunks:
                self.logger.warning("No data to aggregate")
                return pd.DataFrame()

            combined_df = pd.concat(aggregated_chunks, ignore_index=True)
            self.logger.info(f"Chunks combined (combined_rows={len(combined_df)})")

            # Final aggregation to merge duplicate keys across chunks
            # (Same (date, namespace, node) might appear in multiple chunks)
            aggregated_df = self._final_aggregation_across_chunks(combined_df)
            self.logger.info(f"Final aggregation complete (final_rows={len(aggregated_df)})")

            # Free memory
            del combined_df
            gc.collect()

            # Join with node capacity and format output
            aggregated_df = self._join_node_capacity(aggregated_df, node_capacity_df)

            if cost_category_df is not None and not cost_category_df.empty:
                aggregated_df = self._join_cost_category(aggregated_df, cost_category_df)
            else:
                aggregated_df["cost_category_id"] = None

            result_df = self._format_output(aggregated_df)

            self.logger.info(
                "Streaming aggregation complete",
                input_rows=total_input_rows,
                output_rows=len(result_df),
                chunks_processed=chunk_count,
                compression_ratio=f"{total_input_rows / len(result_df):.1f}x" if len(result_df) > 0 else "N/A",
            )

            return result_df

    def _final_aggregation_across_chunks(self, df: pd.DataFrame) -> pd.DataFrame:
        """Re-aggregate across chunks to merge duplicate keys.

        Since we processed in chunks, the same (date, namespace, node) tuple
        might appear in multiple chunks. We need to sum them together.

        Args:
            df: Combined DataFrame from all chunks

        Returns:
            Final aggregated DataFrame with duplicate keys merged
        """
        # NOTE: 'source' is not in the input data, it's added later in _format_output
        group_keys = ["usage_start", "namespace", "node", "merged_labels"]

        # Use same aggregation functions as _group_and_aggregate()
        # Note: At this point, all metrics are already in hours/GB-hours from chunk aggregation
        agg_funcs = {
            "resource_id": lambda x: x.iloc[0] if len(x) > 0 else None,
            # CPU metrics - sum across chunks
            "pod_usage_cpu_core_hours": "sum",
            "pod_request_cpu_core_hours": "sum",
            "pod_effective_usage_cpu_core_hours": "sum",
            "pod_limit_cpu_core_hours": "sum",
            # Memory metrics - sum across chunks
            "pod_usage_memory_gigabyte_hours": "sum",
            "pod_request_memory_gigabyte_hours": "sum",
            "pod_effective_usage_memory_gigabyte_hours": "sum",
            "pod_limit_memory_gigabyte_hours": "sum",
            # Capacity metrics from input data (max - should be same for all chunks with same key)
            "node_capacity_cpu_cores": "max",
            "node_capacity_memory_gigabytes": "max",
        }

        # Note: observed=True is critical when columns are categorical
        return df.groupby(group_keys, dropna=False, observed=True).agg(agg_funcs).reset_index()

    def _prepare_pod_usage_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare pod usage data (parse dates, parse labels).

        Args:
            df: Raw pod usage DataFrame

        Returns:
            Prepared DataFrame
        """
        df = df.copy()

        # Critical Filter: Exclude empty nodes (Trino SQL line 309: AND li.node != '')
        initial_count = len(df)
        df = df[df["node"].notna() & (df["node"] != "")]
        filtered_count = len(df)

        if initial_count > filtered_count:
            self.logger.warning(
                f"Filtered out {initial_count - filtered_count} rows with empty/null nodes",
                initial_rows=initial_count,
                filtered_rows=filtered_count,
            )

        # Parse interval_start as date
        # Handle both string and datetime formats
        if "interval_start" in df.columns:
            if pd.api.types.is_string_dtype(df["interval_start"]):
                # Handle nise string format: "2025-11-01 00:00:00 +0000 UTC"
                df["interval_start_clean"] = df["interval_start"].str.replace(r" \+\d{4} UTC$", "", regex=True)
                df["usage_start"] = pd.to_datetime(df["interval_start_clean"]).dt.date
                df.drop("interval_start_clean", axis=1, inplace=True)
            elif pd.api.types.is_datetime64_any_dtype(df["interval_start"]):
                # Already datetime, just extract date
                df["usage_start"] = df["interval_start"].dt.date
            else:
                # Try to convert to datetime first
                df["usage_start"] = pd.to_datetime(df["interval_start"]).dt.date

        # Parse pod_labels JSON
        df["pod_labels_dict"] = df["pod_labels"].apply(parse_json_labels)

        # Filter pod labels by enabled keys
        df["pod_labels_filtered"] = df["pod_labels_dict"].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        return df

    def _process_labels_optimized(self, pod_usage_df: pd.DataFrame) -> pd.DataFrame:
        """
        Process labels using the best available method (Arrow or list comprehension).

        Args:
            pod_usage_df: DataFrame with node_labels, namespace_labels, pod_labels columns

        Returns:
            DataFrame with processed label columns
        """
        if self.use_arrow:
            # Use Arrow compute (10-100x faster)
            return self.arrow_processor.process_labels_batch(
                node_labels_series=pod_usage_df["node_labels"],
                namespace_labels_series=pod_usage_df["namespace_labels"],
                pod_labels_series=pod_usage_df["pod_labels"],
                merge_func=self._merge_all_labels,
            )
        else:
            # Fallback to list comprehension (3-5x faster than .apply())
            node_labels_values = pod_usage_df["node_labels"].values
            namespace_labels_values = pod_usage_df["namespace_labels"].values
            pod_labels_values = pod_usage_df["pod_labels"].values

            # Parse JSON labels
            node_dicts = [parse_json_labels(x) if x is not None else {} for x in node_labels_values]
            namespace_dicts = [parse_json_labels(x) if x is not None else {} for x in namespace_labels_values]
            pod_dicts = [parse_json_labels(x) if x is not None else {} for x in pod_labels_values]

            # Merge labels
            merged_dicts = [
                self._merge_all_labels(n, ns, p) for n, ns, p in zip(node_dicts, namespace_dicts, pod_dicts)
            ]

            # Convert to JSON strings
            merged_json = [labels_to_json_string(x) for x in merged_dicts]

            return pd.DataFrame(
                {
                    "node_labels_dict": node_dicts,
                    "namespace_labels_dict": namespace_dicts,
                    "pod_labels_dict": pod_dicts,
                    "merged_labels_dict": merged_dicts,
                    "merged_labels": merged_json,
                }
            )

    def _join_node_labels(self, pod_df: pd.DataFrame, node_labels_df: pd.DataFrame) -> pd.DataFrame:
        """Join with node labels.

        Args:
            pod_df: Pod usage DataFrame
            node_labels_df: Node labels DataFrame

        Returns:
            Joined DataFrame
        """
        # Parse node labels
        node_labels_df = node_labels_df.copy()

        # Handle both interval_start (from parquet) and usage_start (from tests)
        if "interval_start" in node_labels_df.columns:
            if pd.api.types.is_string_dtype(node_labels_df["interval_start"]):
                node_labels_df["interval_start_clean"] = node_labels_df["interval_start"].str.replace(
                    r" \+\d{4} UTC$", "", regex=True
                )
                node_labels_df["usage_start"] = pd.to_datetime(node_labels_df["interval_start_clean"]).dt.date
                node_labels_df.drop("interval_start_clean", axis=1, inplace=True)
            elif pd.api.types.is_datetime64_any_dtype(node_labels_df["interval_start"]):
                node_labels_df["usage_start"] = node_labels_df["interval_start"].dt.date
            else:
                node_labels_df["usage_start"] = pd.to_datetime(node_labels_df["interval_start"]).dt.date
        elif "usage_start" not in node_labels_df.columns:
            self.logger.warning("Node labels missing both 'interval_start' and 'usage_start' columns")
            return pod_df

        node_labels_df["node_labels_dict"] = node_labels_df["node_labels"].apply(parse_json_labels)

        # Filter by enabled keys
        node_labels_df["node_labels_filtered"] = node_labels_df["node_labels_dict"].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        # Select columns for join
        node_labels_join = node_labels_df[["usage_start", "node", "node_labels_filtered"]].rename(
            columns={"node_labels_filtered": "node_labels"}
        )

        # CRITICAL: Deduplicate before join to avoid Cartesian product
        # Label data may have multiple rows per (usage_start, node) due to hourly intervals
        node_labels_join = node_labels_join.drop_duplicates(subset=["usage_start", "node"], keep="last")
        self.logger.info(
            f"Deduplicated node labels",
            before_rows=len(node_labels_df),
            after_rows=len(node_labels_join),
        )

        # Left join
        return pod_df.merge(node_labels_join, on=["usage_start", "node"], how="left")

    def _join_namespace_labels(self, pod_df: pd.DataFrame, namespace_labels_df: pd.DataFrame) -> pd.DataFrame:
        """Join with namespace labels.

        Args:
            pod_df: Pod usage DataFrame
            namespace_labels_df: Namespace labels DataFrame

        Returns:
            Joined DataFrame
        """
        # Parse namespace labels
        namespace_labels_df = namespace_labels_df.copy()

        # Handle both interval_start (from parquet) and usage_start (from tests)
        if "interval_start" in namespace_labels_df.columns:
            if pd.api.types.is_string_dtype(namespace_labels_df["interval_start"]):
                namespace_labels_df["interval_start_clean"] = namespace_labels_df["interval_start"].str.replace(
                    r" \+\d{4} UTC$", "", regex=True
                )
                namespace_labels_df["usage_start"] = pd.to_datetime(namespace_labels_df["interval_start_clean"]).dt.date
                namespace_labels_df.drop("interval_start_clean", axis=1, inplace=True)
            elif pd.api.types.is_datetime64_any_dtype(namespace_labels_df["interval_start"]):
                namespace_labels_df["usage_start"] = namespace_labels_df["interval_start"].dt.date
            else:
                namespace_labels_df["usage_start"] = pd.to_datetime(namespace_labels_df["interval_start"]).dt.date
        elif "usage_start" not in namespace_labels_df.columns:
            self.logger.warning("Namespace labels missing both 'interval_start' and 'usage_start' columns")
            return pod_df

        namespace_labels_df["namespace_labels_dict"] = namespace_labels_df["namespace_labels"].apply(parse_json_labels)

        # Filter by enabled keys
        namespace_labels_df["namespace_labels_filtered"] = namespace_labels_df["namespace_labels_dict"].apply(
            lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
        )

        # Select columns for join
        namespace_labels_join = namespace_labels_df[["usage_start", "namespace", "namespace_labels_filtered"]].rename(
            columns={"namespace_labels_filtered": "namespace_labels"}
        )

        # CRITICAL: Deduplicate before join to avoid Cartesian product
        # Label data may have multiple rows per (usage_start, namespace) due to hourly intervals
        namespace_labels_join = namespace_labels_join.drop_duplicates(subset=["usage_start", "namespace"], keep="last")
        self.logger.info(
            f"Deduplicated namespace labels",
            before_rows=len(namespace_labels_df),
            after_rows=len(namespace_labels_join),
        )

        # Left join
        return pod_df.merge(namespace_labels_join, on=["usage_start", "namespace"], how="left")

    def _merge_all_labels(
        self,
        node_labels: Optional[Dict],
        namespace_labels: Optional[Dict],
        pod_labels: Optional[Dict],
    ) -> Dict[str, str]:
        """Merge node + namespace + pod labels (replicates Trino map_concat).

        Trino SQL logic (lines 266-273):
        - COALESCE NULL labels to empty map: map(array[], array[])
        - Merge order: node → namespace → pod (later overrides earlier)

        Args:
            node_labels: Node label dictionary (None → {})
            namespace_labels: Namespace label dictionary (None → {})
            pod_labels: Pod label dictionary (None → {})

        Returns:
            Merged label dictionary
        """
        # COALESCE NULL to empty dict (Trino: cast(map(array[], array[]) as json))
        node_labels = node_labels if node_labels is not None else {}
        namespace_labels = namespace_labels if namespace_labels is not None else {}
        pod_labels = pod_labels if pod_labels is not None else {}

        return merge_label_dicts(node_labels, namespace_labels, pod_labels)

    def _group_and_aggregate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Group by (usage_start, namespace, node) and aggregate metrics.

        This replicates the GROUP BY and SUM/MAX logic in Trino SQL.

        Args:
            df: Prepared DataFrame

        Returns:
            Aggregated DataFrame
        """
        # Group by keys
        # NOTE: 'source' is not in the input data, it's added later in _format_output
        group_keys = ["usage_start", "namespace", "node", "merged_labels"]

        # Aggregation functions
        agg_funcs = {
            "resource_id": lambda x: (
                x.iloc[0] if len(x) > 0 else None
            ),  # Take first value (safer than max for mixed types)
            # CPU metrics (convert seconds to hours)
            "pod_usage_cpu_core_seconds": lambda x: convert_seconds_to_hours(x.sum()),
            "pod_request_cpu_core_seconds": lambda x: convert_seconds_to_hours(x.sum()),
            "pod_limit_cpu_core_seconds": lambda x: convert_seconds_to_hours(x.sum()),
            # Memory metrics (convert byte-seconds to GB-hours)
            "pod_usage_memory_byte_seconds": lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            "pod_request_memory_byte_seconds": lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            "pod_limit_memory_byte_seconds": lambda x: convert_bytes_to_gigabytes(convert_seconds_to_hours(x.sum())),
            # Capacity metrics from raw Parquet data (max)
            "node_capacity_cpu_core_seconds": lambda x: convert_seconds_to_hours(x.max()),
            "node_capacity_memory_byte_seconds": lambda x: convert_bytes_to_gigabytes(
                convert_seconds_to_hours(x.max())
            ),
        }

        # Calculate effective usage before grouping
        # Trino SQL line 277: coalesce(li.pod_effective_usage_cpu_core_seconds,
        #                             greatest(li.pod_usage_cpu_core_seconds, li.pod_request_cpu_core_seconds))
        df["pod_effective_usage_cpu_core_seconds"] = df.apply(
            lambda row: coalesce(
                row.get("pod_effective_usage_cpu_core_seconds"),
                safe_greatest(
                    row.get("pod_usage_cpu_core_seconds"),
                    row.get("pod_request_cpu_core_seconds"),
                ),
            ),
            axis=1,
        )

        # Same logic for memory (Trino SQL line 281)
        df["pod_effective_usage_memory_byte_seconds"] = df.apply(
            lambda row: coalesce(
                row.get("pod_effective_usage_memory_byte_seconds"),
                safe_greatest(
                    row.get("pod_usage_memory_byte_seconds"),
                    row.get("pod_request_memory_byte_seconds"),
                ),
            ),
            axis=1,
        )

        # Add effective usage to aggregation
        agg_funcs["pod_effective_usage_cpu_core_seconds"] = lambda x: convert_seconds_to_hours(x.sum())
        agg_funcs["pod_effective_usage_memory_byte_seconds"] = lambda x: convert_bytes_to_gigabytes(
            convert_seconds_to_hours(x.sum())
        )

        # Group and aggregate
        # Note: observed=True is critical when columns are categorical to avoid
        # creating rows for all category combinations (Cartesian product)
        aggregated = df.groupby(group_keys, dropna=False, observed=True).agg(agg_funcs).reset_index()

        # Rename columns to match output schema
        aggregated = aggregated.rename(
            columns={
                # Note: 'source' is not in aggregated data - it's added later in _format_output
                "pod_usage_cpu_core_seconds": "pod_usage_cpu_core_hours",
                "pod_request_cpu_core_seconds": "pod_request_cpu_core_hours",
                "pod_effective_usage_cpu_core_seconds": "pod_effective_usage_cpu_core_hours",
                "pod_limit_cpu_core_seconds": "pod_limit_cpu_core_hours",
                "pod_usage_memory_byte_seconds": "pod_usage_memory_gigabyte_hours",
                "pod_request_memory_byte_seconds": "pod_request_memory_gigabyte_hours",
                "pod_effective_usage_memory_byte_seconds": "pod_effective_usage_memory_gigabyte_hours",
                "pod_limit_memory_byte_seconds": "pod_limit_memory_gigabyte_hours",
                # Capacity columns (already converted to hours/GB-hours in agg_funcs)
                "node_capacity_cpu_core_seconds": "node_capacity_cpu_cores",
                "node_capacity_memory_byte_seconds": "node_capacity_memory_gigabytes",
            }
        )

        return aggregated

    def _join_node_capacity(self, aggregated_df: pd.DataFrame, node_capacity_df: pd.DataFrame) -> pd.DataFrame:
        """Join with pre-calculated node capacity.

        Args:
            aggregated_df: Aggregated pod usage
            node_capacity_df: Node capacity by day

        Returns:
            Joined DataFrame
        """
        if node_capacity_df.empty:
            aggregated_df["node_capacity_cpu_core_hours"] = None
            aggregated_df["node_capacity_memory_gigabyte_hours"] = None
            aggregated_df["node_capacity_cpu_cores"] = None
            aggregated_df["node_capacity_memory_gigabytes"] = None
            aggregated_df["cluster_capacity_cpu_core_hours"] = None
            aggregated_df["cluster_capacity_memory_gigabyte_hours"] = None
            return aggregated_df

        # Join with node capacity
        result = aggregated_df.merge(node_capacity_df, on=["usage_start", "node"], how="left")

        # Add missing capacity columns with defaults if not present
        capacity_columns = [
            "node_capacity_cpu_core_hours",
            "node_capacity_memory_gigabyte_hours",
            "node_capacity_cpu_cores",
            "node_capacity_memory_gigabytes",
            "cluster_capacity_cpu_core_hours",
            "cluster_capacity_memory_gigabyte_hours",
        ]
        for col in capacity_columns:
            if col not in result.columns:
                result[col] = None

        return result

    def _join_cost_category(self, aggregated_df: pd.DataFrame, cost_category_df: pd.DataFrame) -> pd.DataFrame:
        """Join with cost category namespace (LIKE matching).

        Args:
            aggregated_df: Aggregated DataFrame
            cost_category_df: Cost category DataFrame

        Returns:
            Joined DataFrame
        """
        # Implement LIKE matching with MAX aggregation (Trino SQL line 264)
        # If multiple patterns match, take MAX(cost_category_id) like Trino does

        def match_cost_category(namespace):
            matching_ids = []
            for _, row in cost_category_df.iterrows():
                pattern = row["namespace"]
                # Simple pattern match (% wildcard)
                if pattern.endswith("%"):
                    if namespace.startswith(pattern[:-1]):
                        matching_ids.append(row["cost_category_id"])
                elif namespace == pattern:
                    matching_ids.append(row["cost_category_id"])

            # Return MAX of matching IDs (or None if no matches)
            # This matches Trino SQL line 264: max(cat_ns.cost_category_id)
            return max(matching_ids) if matching_ids else None

        aggregated_df["cost_category_id"] = aggregated_df["namespace"].apply(match_cost_category)

        return aggregated_df

    def _format_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Format final output to match PostgreSQL schema.

        Args:
            df: Aggregated DataFrame

        Returns:
            Formatted DataFrame
        """
        # merged_labels is already a JSON string from _process_labels_optimized
        df["pod_labels"] = df["merged_labels"]

        # Add fixed columns
        # Bug #9 fix: Generate UUIDs - Koku DB requires uuid (NOT NULL, no default)
        df["uuid"] = [str(uuid_lib.uuid4()) for _ in range(len(df))]
        df["report_period_id"] = self.report_period_id
        df["cluster_id"] = self.cluster_id
        df["cluster_alias"] = self.cluster_alias
        df["data_source"] = "Pod"
        df["usage_end"] = df["usage_start"]  # Same as usage_start for daily

        # NOTE: "pod" column removed - Koku DB uses "resource_id" instead (Bug #7)
        # The aggregator already has "resource_id" from the grouping/processing

        # Storage columns (NULL for pod data)
        df["persistentvolumeclaim"] = None
        df["persistentvolume"] = None
        df["storageclass"] = None
        df["volume_labels"] = None
        df["persistentvolumeclaim_capacity_gigabyte"] = None
        df["persistentvolumeclaim_capacity_gigabyte_months"] = None
        df["volume_request_storage_gigabyte_months"] = None
        df["persistentvolumeclaim_usage_gigabyte_months"] = None
        # NOTE: csi_volume_handle column does NOT exist in Koku database - REMOVED (Bug #8)

        # all_labels = merge(pod_labels, volume_labels) - Trino SQL lines 651-654
        # For Pod data, volume_labels is NULL, so all_labels = pod_labels
        df["all_labels"] = df["pod_labels"]

        # Infrastructure cost (default JSON)
        df["infrastructure_usage_cost"] = '{"cpu": 0.000000000, "memory": 0.000000000, "storage": 0.000000000}'

        # Partition columns
        # Note: Trino SQL line 665 uses lpad(month, 2, '0') for zero-padding
        df["source_uuid"] = self.provider_uuid  # UUID column for database foreign key

        # Select columns in correct order (PostgreSQL schema - no partition columns)
        # NOTE: Partition columns (source, year, month, day) are for Hive/Trino only, not PostgreSQL
        # all_labels added per Trino SQL lines 651-654
        # NOTE: Koku database schema uses "resource_id" NOT "pod" (Bug #7)
        # NOTE: Koku database does NOT have "csi_volume_handle" column (Bug #8)
        output_columns = [
            "uuid",
            "report_period_id",
            "cluster_id",
            "cluster_alias",
            "data_source",
            "usage_start",
            "usage_end",
            "namespace",
            "node",
            "resource_id",  # Database column (NOT "pod" - Bug #7)
            "pod_labels",
            "pod_usage_cpu_core_hours",
            "pod_request_cpu_core_hours",
            "pod_effective_usage_cpu_core_hours",
            "pod_limit_cpu_core_hours",
            "pod_usage_memory_gigabyte_hours",
            "pod_request_memory_gigabyte_hours",
            "pod_effective_usage_memory_gigabyte_hours",
            "pod_limit_memory_gigabyte_hours",
            "node_capacity_cpu_cores",
            "node_capacity_cpu_core_hours",
            "node_capacity_memory_gigabytes",
            "node_capacity_memory_gigabyte_hours",
            "cluster_capacity_cpu_core_hours",
            "cluster_capacity_memory_gigabyte_hours",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "volume_labels",
            "all_labels",  # Trino SQL lines 651-654: merge(pod_labels, volume_labels)
            "persistentvolumeclaim_capacity_gigabyte",
            "persistentvolumeclaim_capacity_gigabyte_months",
            "volume_request_storage_gigabyte_months",
            "persistentvolumeclaim_usage_gigabyte_months",
            "source_uuid",
            "infrastructure_usage_cost",
            # "csi_volume_handle" - REMOVED: Column does NOT exist in Koku DB (Bug #8)
            "cost_category_id",
        ]

        return df[output_columns]


def calculate_node_capacity(
    pod_usage_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate node and cluster capacity (replicates CTEs in Trino SQL).

    Trino SQL Logic (lines 143-171):
    1. Inner query: MAX capacity per interval + node
    2. Outer query: SUM of max capacities per day + node
    3. Cluster capacity: SUM across all nodes per day

    IMPORTANT: This requires hourly interval data (openshift_pod_usage_line_items),
    NOT daily aggregated data (openshift_pod_usage_line_items_daily).

    The POC currently uses daily data, which is a simplification.
    For production, this should read from the hourly Parquet files.

    Args:
        pod_usage_df: Pod usage line items (ideally hourly)

    Returns:
        Tuple of (node_capacity_df, cluster_capacity_df)
    """
    logger = get_logger("capacity_calculator")

    with PerformanceTimer("Calculate node/cluster capacity", logger):
        # Parse usage_start
        df = pod_usage_df.copy()

        # Handle empty DataFrame
        if df.empty:
            logger.warning("Empty DataFrame passed to calculate_node_capacity, returning empty capacity")
            empty_node_capacity = pd.DataFrame(
                columns=[
                    "usage_start",
                    "node",
                    "node_capacity_cpu_cores",
                    "node_capacity_memory_gigabytes",
                    "node_capacity_cpu_core_hours",
                    "node_capacity_memory_gigabyte_hours",
                ]
            )
            empty_cluster_capacity = pd.DataFrame(
                columns=[
                    "usage_start",
                    "cluster_capacity_cpu_core_hours",
                    "cluster_capacity_memory_gigabyte_hours",
                ]
            )
            return empty_node_capacity, empty_cluster_capacity

        # Handle both string and datetime formats for interval_start
        if pd.api.types.is_string_dtype(df["interval_start"]):
            # Handle nise string format: "2025-11-01 00:00:00 +0000 UTC"
            df["interval_start_clean"] = df["interval_start"].str.replace(r" \+\d{4} UTC$", "", regex=True)
            df["usage_start"] = pd.to_datetime(df["interval_start_clean"]).dt.date
            df.drop("interval_start_clean", axis=1, inplace=True)
        elif pd.api.types.is_datetime64_any_dtype(df["interval_start"]):
            # Already datetime, just extract date
            df["usage_start"] = df["interval_start"].dt.date
        else:
            # Try to convert to datetime first
            df["usage_start"] = pd.to_datetime(df["interval_start"]).dt.date

        # Step 1: Get max capacity per interval + node (Trino lines 149-160)
        # NOTE: If input is already daily aggregated, this step is a no-op
        interval_capacity = (
            df.groupby(["interval_start", "node"])
            .agg(
                {
                    "node_capacity_cpu_core_seconds": "max",
                    "node_capacity_memory_byte_seconds": "max",
                }
            )
            .reset_index()
        )

        # Step 2: Sum across intervals for each day + node (Trino lines 143-164)
        # Handle both string and datetime formats
        if pd.api.types.is_string_dtype(interval_capacity["interval_start"]):
            interval_capacity["interval_start_clean"] = interval_capacity["interval_start"].str.replace(
                r" \+\d{4} UTC$", "", regex=True
            )
            interval_capacity["usage_start"] = pd.to_datetime(interval_capacity["interval_start_clean"]).dt.date
            interval_capacity.drop("interval_start_clean", axis=1, inplace=True)
        elif pd.api.types.is_datetime64_any_dtype(interval_capacity["interval_start"]):
            interval_capacity["usage_start"] = interval_capacity["interval_start"].dt.date
        else:
            interval_capacity["usage_start"] = pd.to_datetime(interval_capacity["interval_start"]).dt.date
        node_capacity = (
            interval_capacity.groupby(["usage_start", "node"])
            .agg(
                {
                    "node_capacity_cpu_core_seconds": "sum",
                    "node_capacity_memory_byte_seconds": "sum",
                }
            )
            .reset_index()
        )

        logger.debug(
            "Node capacity calculation",
            intervals=len(interval_capacity),
            node_days=len(node_capacity),
        )

        # Convert to hours and GB
        node_capacity["node_capacity_cpu_core_hours"] = node_capacity["node_capacity_cpu_core_seconds"] / 3600.0
        node_capacity["node_capacity_memory_gigabyte_hours"] = (
            node_capacity["node_capacity_memory_byte_seconds"] / 3600.0 * pow(2, -30)
        )

        # Step 3: Calculate cluster capacity (Trino lines 165-171)
        # Sum across all nodes per day
        cluster_capacity = (
            node_capacity.groupby("usage_start")
            .agg(
                {
                    "node_capacity_cpu_core_seconds": "sum",
                    "node_capacity_memory_byte_seconds": "sum",
                }
            )
            .reset_index()
        )

        cluster_capacity["cluster_capacity_cpu_core_hours"] = (
            cluster_capacity["node_capacity_cpu_core_seconds"] / 3600.0
        )
        cluster_capacity["cluster_capacity_memory_gigabyte_hours"] = (
            cluster_capacity["node_capacity_memory_byte_seconds"] / 3600.0 * pow(2, -30)
        )

        # Verify cluster capacity is > 0
        if (cluster_capacity["cluster_capacity_cpu_core_hours"] <= 0).any():
            logger.warning("Found days with zero or negative cluster CPU capacity")
        if (cluster_capacity["cluster_capacity_memory_gigabyte_hours"] <= 0).any():
            logger.warning("Found days with zero or negative cluster memory capacity")

        logger.debug(
            "Cluster capacity summary",
            days=len(cluster_capacity),
            total_cpu_hours=cluster_capacity["cluster_capacity_cpu_core_hours"].sum(),
            total_memory_gb_hours=cluster_capacity["cluster_capacity_memory_gigabyte_hours"].sum(),
        )

        # Join cluster capacity back to node capacity (each node gets the same cluster total)
        node_capacity = node_capacity.merge(
            cluster_capacity[
                [
                    "usage_start",
                    "cluster_capacity_cpu_core_hours",
                    "cluster_capacity_memory_gigabyte_hours",
                ]
            ],
            on="usage_start",
            how="left",
        )

        # Verify join was successful
        if node_capacity["cluster_capacity_cpu_core_hours"].isna().any():
            logger.error("Cluster capacity join failed - found NULL values")
        else:
            logger.debug("✓ Cluster capacity successfully joined to all nodes")

        logger.info(
            "Capacity calculation complete",
            node_capacity_rows=len(node_capacity),
            cluster_capacity_days=len(cluster_capacity),
        )

        return node_capacity, cluster_capacity
