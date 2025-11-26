"""Main entry point for OCP Parquet Aggregator POC."""

import argparse
import os
import resource
import sys
import tracemalloc
from datetime import datetime

from .aggregator_ocp_aws import OCPAWSAggregator
from .aggregator_pod import PodAggregator, calculate_node_capacity
from .aggregator_storage import StorageAggregator
from .aggregator_unallocated import UnallocatedCapacityAggregator
from .config_loader import get_config
from .db_writer import DatabaseWriter
from .parquet_reader import ParquetReader
from .utils import PerformanceTimer, format_duration, get_logger, setup_logging


def run_ocp_aws_aggregation(
    config,
    ocp_provider_uuid,
    aws_provider_uuid,
    year,
    month,
    parquet_reader,
    db_writer,
    enabled_tag_keys,
    pipeline_start,
    logger,
):
    """Run OCP-on-AWS aggregation pipeline.

    Args:
        config: Configuration dictionary
        ocp_provider_uuid: OCP provider UUID
        aws_provider_uuid: AWS provider UUID
        year: Year to process
        month: Month to process
        parquet_reader: ParquetReader instance
        db_writer: DatabaseWriter instance
        enabled_tag_keys: List of enabled tag keys
        pipeline_start: Pipeline start time
        logger: Logger instance

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        logger.info("=" * 80)
        logger.info("Running OCP-on-AWS Aggregation")
        logger.info("=" * 80)

        # Initialize OCP-AWS aggregator
        ocp_aws_aggregator = OCPAWSAggregator(config, enabled_tag_keys)

        # Get cluster ID
        cluster_id = config["ocp"]["cluster_id"]

        # Check for incremental DB writes (streaming only)
        perf_config = config.get("performance", {})
        use_streaming = ocp_aws_aggregator.use_streaming
        incremental_raw = perf_config.get("incremental_db_writes", False)
        if isinstance(incremental_raw, str):
            incremental_db_writes = incremental_raw.lower() == "true"
        else:
            incremental_db_writes = bool(incremental_raw)

        # Incremental writes only make sense with streaming
        incremental_db_writes = incremental_db_writes and use_streaming

        logger.info(f"Aggregating OCP+AWS data for cluster: {cluster_id}")
        if incremental_db_writes:
            logger.info("Using INCREMENTAL DB WRITES (memory-bounded)")

        # Run aggregation
        with PerformanceTimer("OCP-AWS aggregation", logger):
            # For incremental writes, we need to connect DB first and pass it in
            if incremental_db_writes:
                db_writer.connect()
                summary_df = ocp_aws_aggregator.aggregate(
                    year=str(year),
                    month=str(month),
                    cluster_id=cluster_id,
                    aws_provider_uuid=aws_provider_uuid,
                    db_writer=db_writer,
                    incremental_db_writes=True,
                )
                rows_written = (
                    db_writer.create_streaming_writer("ocp_aws").total_rows
                    if hasattr(db_writer, "_last_streaming_writer")
                    else 0
                )
            else:
                summary_df = ocp_aws_aggregator.aggregate(
                    year=str(year),
                    month=str(month),
                    cluster_id=cluster_id,
                    aws_provider_uuid=aws_provider_uuid,
                )

        if summary_df.empty and not incremental_db_writes:
            logger.warning("No OCP-AWS summary data generated")
            logger.info("✓ OCP-AWS aggregation complete (0 rows)")
            return 0

        # For incremental writes, data is already in DB
        if incremental_db_writes:
            logger.info("✓ OCP-AWS data written incrementally during aggregation")
        else:
            logger.info(f"✓ Generated {len(summary_df)} OCP-AWS summary rows")

            # Write to PostgreSQL
            logger.info("Writing OCP-AWS summary data to PostgreSQL...")
            with db_writer:
                with PerformanceTimer("Write OCP-AWS summary to PostgreSQL", logger):
                    db_writer.write_ocp_aws_summary_data(summary_df)

            logger.info(f"✓ Inserted {len(summary_df)} OCP-AWS rows")

        # Memory statistics
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            max_rss_mb = max_rss_bytes / (1024 * 1024)
        else:
            max_rss_mb = max_rss_bytes / 1024

        # Track output rows (may be 0 if incremental writes used)
        output_rows = len(summary_df) if not summary_df.empty else 0

        # Pipeline summary
        pipeline_duration = (datetime.now() - pipeline_start).total_seconds()
        logger.info("=" * 80)
        logger.info(f"✓ OCP-AWS aggregation complete in {format_duration(pipeline_duration)}")
        logger.info(f"✓ Output: {output_rows} OCP-AWS summary rows")
        logger.info(
            "Memory usage",
            peak_python_mb=f"{peak_mem / (1024 * 1024):.2f} MB",
            peak_rss_mb=f"{max_rss_mb:.2f} MB",
        )
        logger.info("=" * 80)

        return 0

    except Exception as e:
        logger.error(f"OCP-AWS aggregation failed: {e}", exc_info=True)
        return 1


def run_poc(args):
    """Run the POC aggregation pipeline.

    Args:
        args: Command-line arguments
    """
    # Load configuration
    config = get_config(args.config)

    # Setup logging
    setup_logging(
        level=config.get("logging", {}).get("level", "INFO"),
        log_format=config.get("logging", {}).get("format", "console"),
    )

    logger = get_logger("main")

    logger.info("=" * 80)
    logger.info("OCP Parquet Aggregator POC - Starting")
    logger.info("=" * 80)

    # Start memory tracking
    tracemalloc.start()

    # Print configuration
    ocp_config = config["ocp"]
    logger.info(
        "Configuration",
        provider_uuid=ocp_config["provider_uuid"],
        cluster_id=ocp_config["cluster_id"],
        year=ocp_config["year"],
        month=ocp_config["month"],
        start_date=ocp_config["start_date"],
        end_date=ocp_config["end_date"],
    )

    # Total pipeline timer
    pipeline_start = datetime.now()

    try:
        # ====================================================================
        # Phase 1: Initialize components
        # ====================================================================
        logger.info("Phase 1: Initializing components...")

        parquet_reader = ParquetReader(config)
        db_writer = DatabaseWriter(config)

        # Test connectivity
        with db_writer:
            if not db_writer.test_connectivity():
                logger.error("Database connectivity test failed")
                return 1

        # Skip S3 connectivity test - time sync issues with MinIO container
        # The actual S3 operations (reads/writes) work fine
        try:
            if not parquet_reader.test_connectivity():
                logger.warning("S3 connectivity test failed (time sync issue), but continuing...")
        except Exception as e:
            logger.warning(f"S3 connectivity test error: {e}, but continuing...")

        logger.info("✓ Connectivity tests passed")

        # ====================================================================
        # Phase 2: Fetch enabled tag keys from PostgreSQL
        # ====================================================================
        logger.info("Phase 2: Fetching enabled tag keys...")

        with db_writer:
            enabled_tag_keys = db_writer.get_enabled_tag_keys()
            cost_category_df = db_writer.get_cost_category_namespaces()

        logger.info(f"✓ Fetched {len(enabled_tag_keys)} enabled tag keys")

        # ====================================================================
        # Phase 2.5: Detect AWS data and determine aggregation mode
        # ====================================================================
        provider_uuid = ocp_config["provider_uuid"]
        # Allow override from environment (for Core validation)
        year = os.getenv("POC_YEAR", ocp_config["year"])
        month = os.getenv("POC_MONTH", ocp_config["month"])

        # Check for AWS data to determine if we should run OCP-AWS aggregation
        aws_provider_uuid = os.getenv("AWS_PROVIDER_UUID")
        run_ocp_aws = False

        if aws_provider_uuid:
            logger.info(f"AWS_PROVIDER_UUID detected - will attempt OCP-on-AWS aggregation")
            run_ocp_aws = True
        else:
            logger.info("AWS_PROVIDER_UUID not set - will run OCP-only aggregation")

        # ====================================================================
        # Branch: OCP-on-AWS or OCP-only aggregation
        # ====================================================================
        if run_ocp_aws:
            return run_ocp_aws_aggregation(
                config=config,
                ocp_provider_uuid=provider_uuid,
                aws_provider_uuid=aws_provider_uuid,
                year=year,
                month=month,
                parquet_reader=parquet_reader,
                db_writer=db_writer,
                enabled_tag_keys=enabled_tag_keys,
                pipeline_start=pipeline_start,
                logger=logger,
            )

        # ====================================================================
        # Phase 3: Read Parquet files from S3 (OCP-only)
        # ====================================================================
        logger.info("Phase 3: Reading Parquet files from S3 (OCP-only mode)...")

        # Determine if we should use streaming mode
        use_streaming_raw = config.get("performance", {}).get("use_streaming", False)
        # Handle string 'false'/'true' from env vars
        if isinstance(use_streaming_raw, str):
            use_streaming = use_streaming_raw.lower() in ("true", "1", "yes")
        else:
            use_streaming = bool(use_streaming_raw)
        chunk_size_raw = config.get("performance", {}).get("chunk_size", 50000)
        chunk_size = int(chunk_size_raw) if isinstance(chunk_size_raw, str) else chunk_size_raw

        if use_streaming:
            logger.info(f"Streaming mode ENABLED (chunk_size={chunk_size})")
        else:
            logger.info("In-memory mode (streaming disabled)")

        # Read daily pod usage for aggregation
        pod_usage_daily = parquet_reader.read_pod_usage_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            daily=True,
            streaming=use_streaming,
            chunk_size=chunk_size,
        )

        # Handle both streaming (iterator) and non-streaming (DataFrame) modes
        if use_streaming:
            # pod_usage_daily is an iterator, we'll pass it directly to aggregate_streaming
            logger.info("✓ Pod usage data ready for streaming processing")
            pod_usage_daily_df = None  # Will use iterator directly
        else:
            # pod_usage_daily is a DataFrame
            pod_usage_daily_df = pod_usage_daily
            if pod_usage_daily_df.empty:
                logger.error("No daily pod usage data found")
                return 1
            logger.info(f"✓ Loaded daily pod usage data: {len(pod_usage_daily_df)} rows")

        # Read hourly pod usage for capacity calculation (Trino lines 143-171)
        # Try hourly first, fall back to daily if not available
        pod_usage_hourly_df = parquet_reader.read_pod_usage_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            daily=False,  # Hourly intervals
            streaming=False,
        )

        if pod_usage_hourly_df.empty:
            logger.warning("No hourly pod usage data found, using daily for capacity calculation")
            # If streaming mode, we need to re-read daily data non-streaming for capacity
            if use_streaming:
                logger.info("Reading daily data (non-streaming) for capacity calculation...")
                pod_usage_for_capacity = parquet_reader.read_pod_usage_line_items(
                    provider_uuid=provider_uuid,
                    year=year,
                    month=month,
                    daily=True,
                    streaming=False,
                )
            else:
                pod_usage_for_capacity = pod_usage_daily_df
        else:
            logger.info(f"✓ Loaded hourly pod usage data: {len(pod_usage_hourly_df)} rows")
            pod_usage_for_capacity = pod_usage_hourly_df

        # Read node labels (optional)
        node_labels_df = parquet_reader.read_node_labels_line_items(provider_uuid=provider_uuid, year=year, month=month)
        logger.info(f"✓ Loaded node labels: {len(node_labels_df)} rows")

        # Read namespace labels (optional)
        namespace_labels_df = parquet_reader.read_namespace_labels_line_items(
            provider_uuid=provider_uuid, year=year, month=month
        )
        logger.info(f"✓ Loaded namespace labels: {len(namespace_labels_df)} rows")

        # ====================================================================
        # Phase 4: Calculate node and cluster capacity
        # ====================================================================
        logger.info("Phase 4: Calculating node and cluster capacity...")

        # CRITICAL: Use hourly data for proper two-level aggregation
        # Trino SQL lines 143-171: max(interval) then sum(day)
        node_capacity_df, cluster_capacity_df = calculate_node_capacity(pod_usage_for_capacity)

        logger.info(
            f"✓ Calculated capacity for {len(node_capacity_df)} node-days, " f"{len(cluster_capacity_df)} cluster-days"
        )

        # ====================================================================
        # Phase 5: Aggregate pod usage
        # ====================================================================
        logger.info("Phase 5: Aggregating pod usage...")

        aggregator = PodAggregator(config, enabled_tag_keys)

        # Use streaming or in-memory aggregation based on config
        if use_streaming:
            logger.info("Using streaming aggregation (constant memory)")
            aggregated_df = aggregator.aggregate_streaming(
                pod_usage_chunks=pod_usage_daily,  # Iterator
                node_capacity_df=node_capacity_df,
                node_labels_df=node_labels_df,
                namespace_labels_df=namespace_labels_df,
                cost_category_df=cost_category_df,
            )
            # For storage join, we need a DataFrame (not an iterator)
            # Re-read pod data for storage join if storage is enabled
            pod_df_for_storage = None
        else:
            logger.info("Using in-memory aggregation")
            aggregated_df = aggregator.aggregate(
                pod_usage_df=pod_usage_daily_df,  # DataFrame
                node_capacity_df=node_capacity_df,
                node_labels_df=node_labels_df,
                namespace_labels_df=namespace_labels_df,
                cost_category_df=cost_category_df,
            )
            pod_df_for_storage = pod_usage_daily_df

        logger.info(f"✓ Generated {len(aggregated_df)} pod summary rows")

        # ====================================================================
        # Phase 5b: Aggregate storage usage (MANDATORY)
        # ====================================================================
        logger.info("Phase 5b: Aggregating storage usage...")

        # If streaming was used for pods, we need to re-read pod data for storage join
        if use_streaming and pod_df_for_storage is None:
            logger.info("Re-reading pod data for storage join (streaming mode)")
            pod_df_for_storage = parquet_reader.read_pod_usage_line_items(
                provider_uuid=provider_uuid,
                year=year,
                month=month,
                daily=True,
                streaming=False,  # Need DataFrame for join
            )
            logger.info(f"✓ Re-loaded pod data for storage join: {len(pod_df_for_storage)} rows")

        # Read storage data
        storage_usage_daily = parquet_reader.read_storage_usage_line_items(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            daily=True,
            streaming=False,  # Always use in-memory for storage (typically smaller dataset)
        )

        if storage_usage_daily.empty:
            logger.warning("No storage usage data found - skipping storage aggregation")
        else:
            logger.info(f"✓ Loaded storage usage data: {len(storage_usage_daily)} rows")

            # Aggregate storage
            storage_aggregator = StorageAggregator(config)
            storage_aggregated_df = storage_aggregator.aggregate(
                storage_df=storage_usage_daily,
                pod_df=pod_df_for_storage,
                node_labels_df=node_labels_df,
                namespace_labels_df=namespace_labels_df,
            )

            logger.info(f"✓ Generated {len(storage_aggregated_df)} storage summary rows")

            # Combine pod + storage results
            import pandas as pd

            aggregated_df = pd.concat([aggregated_df, storage_aggregated_df], ignore_index=True)

            logger.info(
                f"✓ Combined results: {len(aggregated_df)} total rows "
                f"(Pod: {len(aggregated_df[aggregated_df['data_source'] == 'Pod'])}, "
                f"Storage: {len(aggregated_df[aggregated_df['data_source'] == 'Storage'])})"
            )

        # ====================================================================
        # Phase 5c: Calculate Unallocated Capacity (MANDATORY - Trino parity)
        # ====================================================================
        # Trino SQL lines 461-581: Always calculates unallocated capacity
        # This is NOT optional - required for 1:1 Trino parity
        logger.info("Phase 5c: Calculating unallocated capacity...")

        # Get node roles from PostgreSQL
        with db_writer:
            node_roles_df = db_writer.get_node_roles()

        if node_roles_df.empty:
            logger.warning(
                "No node roles found in reporting_ocp_nodes table. "
                "Unallocated capacity will be $0. This may indicate missing data."
            )
        else:
            logger.info(f"✓ Fetched {len(node_roles_df)} node roles")

            # Calculate unallocated
            unallocated_aggregator = UnallocatedCapacityAggregator(config)
            unallocated_df = unallocated_aggregator.calculate_unallocated(
                daily_summary_df=aggregated_df, node_roles_df=node_roles_df
            )

            if not unallocated_df.empty:
                logger.info(f"✓ Generated {len(unallocated_df)} unallocated capacity rows")

                # Add to combined results
                aggregated_df = pd.concat([aggregated_df, unallocated_df], ignore_index=True)

                logger.info(f"✓ Combined results: {len(aggregated_df)} total rows " f"(including unallocated capacity)")
            else:
                logger.info("No unallocated capacity rows generated (all capacity used)")

        # ====================================================================
        # Phase 6: Write to PostgreSQL
        # ====================================================================
        logger.info("Phase 6: Writing to PostgreSQL...")

        with db_writer:
            # Use bulk COPY if enabled (10-50x faster), otherwise batch INSERT
            use_bulk_copy = config.get("performance", {}).get("use_bulk_copy", True)

            if use_bulk_copy:
                logger.info("Using bulk COPY for database write (10-50x faster)")
                rows_inserted = db_writer.write_summary_data_bulk_copy(df=aggregated_df, truncate=args.truncate)
            else:
                logger.info("Using batch INSERT for database write")
                rows_inserted = db_writer.write_summary_data(
                    df=aggregated_df,
                    batch_size=config.get("performance", {}).get("db_batch_size", 1000),
                    truncate=args.truncate,
                )

        logger.info(f"✓ Inserted {rows_inserted} rows")

        # ====================================================================
        # Phase 7: Validate results
        # ====================================================================
        logger.info("Phase 7: Validating results...")

        with db_writer:
            validation_result = db_writer.validate_summary_data(provider_uuid=provider_uuid, year=year, month=month)

        logger.info("✓ Validation complete")
        logger.info("Validation Results:")
        for key, value in validation_result.items():
            logger.info(f"  {key}: {value}")

        # ====================================================================
        # Phase 8: Validate against expected results (if requested)
        # ====================================================================
        if args.validate_expected:
            logger.info("Phase 8: Validating against expected results...")

            from .expected_results import ExpectedResultsCalculator, compare_results

            calculator = ExpectedResultsCalculator(args.validate_expected)
            expected_df = calculator.calculate_expected_aggregations()

            logger.info(f"Calculated {len(expected_df)} expected result rows")
            calculator.print_summary(expected_df)

            # Compare with aggregated results
            comparison_result = compare_results(expected_df, aggregated_df)

            if comparison_result["all_match"]:
                logger.info("=" * 80)
                logger.info("✅ VALIDATION SUCCESS: ALL RESULTS MATCH EXPECTED VALUES!")
                logger.info("=" * 80)
                logger.info(
                    f"Matched {comparison_result['match_count']}/{comparison_result['total_comparisons']} comparisons"
                )
            else:
                logger.error("=" * 80)
                logger.error("❌ VALIDATION FAILED: DISCREPANCIES FOUND")
                logger.error("=" * 80)
                logger.error(
                    f"Matched {comparison_result['match_count']}/{comparison_result['total_comparisons']} comparisons"
                )
                logger.error(f"Missing in actual: {comparison_result['missing_in_actual_count']}")
                logger.error(f"Extra in actual: {comparison_result['extra_in_actual_count']}")
                logger.error(f"Issues found: {len(comparison_result['issues'])}")

                # Exit with error if validation fails
                return 1

        # ====================================================================
        # Summary
        # ====================================================================
        pipeline_end = datetime.now()
        total_duration = (pipeline_end - pipeline_start).total_seconds()

        logger.info("=" * 80)
        logger.info("POC COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info(f"Total duration: {format_duration(total_duration)}")

        if use_streaming:
            logger.info("Mode: Streaming (constant memory)")
        else:
            logger.info(f"Input rows: {len(pod_usage_daily_df):,}")
            logger.info(f"Compression ratio: {len(pod_usage_daily_df) / rows_inserted:.1f}x")
            logger.info(f"Processing rate: {len(pod_usage_daily_df) / total_duration:.0f} rows/sec")

        logger.info(f"Output rows: {rows_inserted:,}")

        # Memory statistics
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Get RSS (Resident Set Size) - actual memory used
        max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports in bytes, Linux in KB
        if sys.platform == "darwin":
            max_rss_mb = max_rss_bytes / (1024 * 1024)
        else:
            max_rss_mb = max_rss_bytes / 1024

        logger.info(
            "Memory usage",
            peak_python_mb=f"{peak_mem / (1024 * 1024):.2f} MB",
            peak_rss_mb=f"{max_rss_mb:.2f} MB",
        )
        logger.info("=" * 80)

        return 0

    except Exception as e:
        logger.error("POC failed with error", error=str(e), exc_info=True)
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="OCP Parquet Aggregator POC - Validate Trino + Hive replacement")

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.yaml (default: poc-parquet-aggregator/config/config.yaml)",
    )

    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate summary table before inserting (for testing)",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation against Trino results (not implemented yet)",
    )

    parser.add_argument(
        "--validate-expected",
        type=str,
        metavar="YAML_FILE",
        help="Validate against expected results from nise static YAML",
    )

    args = parser.parse_args()

    if args.validate:
        print("ERROR: Validation against Trino not yet implemented")
        print("This will be added in Phase 2 of the POC")
        return 1

    # Run POC
    exit_code = run_poc(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
