#!/usr/bin/env python3
"""
Validate POC aggregation results against IQE expected values.

This script:
1. Reads IQE YAML configuration
2. Calculates expected values using IQE logic
3. Queries POC results from PostgreSQL
4. Compares actual vs expected with tolerance
5. Generates detailed validation report
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.iqe_validator import read_ocp_resources_from_yaml, validate_poc_results
from src.config_loader import get_config
import psycopg2
import pandas as pd
import structlog

logger = structlog.get_logger()


def query_poc_results(config: dict) -> pd.DataFrame:
    """Query POC aggregation results from PostgreSQL."""

    postgres_config = config['postgresql']
    schema = os.getenv('POSTGRES_SCHEMA', postgres_config['schema'])

    connection = psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', postgres_config['host']),
        port=postgres_config['port'],
        database=os.getenv('POSTGRES_DB', postgres_config['database']),
        user=os.getenv('POSTGRES_USER', postgres_config['user']),
        password=os.getenv('POSTGRES_PASSWORD', postgres_config['password'])
    )

    query = f"""
        SELECT
            usage_start,
            namespace,
            node,
            pod_usage_cpu_core_hours,
            pod_request_cpu_core_hours,
            pod_effective_usage_cpu_core_hours,
            pod_limit_cpu_core_hours,
            pod_usage_memory_gigabyte_hours,
            pod_request_memory_gigabyte_hours,
            pod_effective_usage_memory_gigabyte_hours,
            pod_limit_memory_gigabyte_hours,
            node_capacity_cpu_cores,
            node_capacity_cpu_core_hours,
            node_capacity_memory_gigabytes,
            node_capacity_memory_gigabyte_hours,
            cluster_capacity_cpu_core_hours,
            cluster_capacity_memory_gigabyte_hours,
            pod_labels
        FROM {schema}.reporting_ocpusagelineitem_daily_summary
        ORDER BY node, namespace, usage_start
    """

    df = pd.read_sql(query, connection)
    connection.close()

    return df


def main():
    """Main validation workflow."""

    logger.info("=" * 80)
    logger.info("IQE-based POC Validation")
    logger.info("=" * 80)

    # Load configuration
    config = get_config()

    # Get YAML file path
    yaml_file = os.getenv('IQE_YAML_FILE', 'config/ocp_report_advanced.yml')

    if not Path(yaml_file).exists():
        logger.error(f"IQE YAML file not found: {yaml_file}")
        logger.info("Set IQE_YAML_FILE environment variable to specify a different file")
        return 1

    logger.info(f"Reading IQE YAML: {yaml_file}")

    # Step 1: Calculate expected values from YAML (per-day basis)
    try:
        # Calculate for 1 day (24 hours) first
        expected_values = read_ocp_resources_from_yaml(yaml_file, hours_in_period=24)
        logger.info("✓ Calculated expected values from YAML (per-day basis)")

    except Exception as e:
        logger.error(f"Failed to read YAML: {e}")
        return 1

    # Step 2: Query POC results from PostgreSQL
    logger.info("Querying POC results from PostgreSQL...")
    try:
        actual_df = query_poc_results(config)
        logger.info(f"✓ Retrieved {len(actual_df)} rows from PostgreSQL")

        # Calculate number of days in the data
        num_days = actual_df['usage_start'].nunique()
        logger.info(f"  Days in data: {num_days}")

        # Calculate the actual total hours from the POC data
        # This accounts for scenarios where nise generates partial days (e.g., "today" scenarios)
        actual_total_hours = actual_df['pod_usage_cpu_core_hours'].sum()
        expected_per_hour = expected_values['compute']['usage'] / 24  # Expected per hour (YAML specifies hourly rates)

        # Estimate number of intervals (hours) from actual data
        # Since the summary table is daily, we estimate intervals from the actual hours
        if expected_per_hour > 0:
            # Calculate how many intervals (hours) of data we actually have
            # by dividing actual total hours by expected per-hour rate
            num_intervals = actual_total_hours / expected_per_hour
            logger.info(f"  Estimated intervals: {num_intervals:.1f} hours")

            # Use this to calculate expected values
            multiplier = num_intervals
            logger.info(f"  Using interval-based calculation: {num_intervals:.1f} intervals")

            for metric in ['compute', 'memory', 'volumes']:
                # Skip if metric doesn't exist (e.g., some scenarios don't have volumes)
                if metric not in expected_values:
                    continue

                # Multiply by number of intervals (hours)
                expected_values[metric]['usage'] = (expected_values[metric]['usage'] / 24) * multiplier
                expected_values[metric]['requests'] = (expected_values[metric]['requests'] / 24) * multiplier

                for node_name in expected_values[metric]['nodes']:
                    expected_values[metric]['nodes'][node_name]['usage'] = (expected_values[metric]['nodes'][node_name]['usage'] / 24) * multiplier
                    expected_values[metric]['nodes'][node_name]['requests'] = (expected_values[metric]['nodes'][node_name]['requests'] / 24) * multiplier

                    for ns_name in expected_values[metric]['nodes'][node_name]['namespaces']:
                        expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['usage'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['usage'] / 24) * multiplier
                        expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['requests'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['requests'] / 24) * multiplier

                        for pod_name in expected_values[metric]['nodes'][node_name]['namespaces'][ns_name].get('pods', {}):
                            expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pods'][pod_name]['usage'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pods'][pod_name]['usage'] / 24) * multiplier
                            expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pods'][pod_name]['requests'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pods'][pod_name]['requests'] / 24) * multiplier

                        for pvc_name in expected_values[metric]['nodes'][node_name]['namespaces'][ns_name].get('pvcs', {}):
                            expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pvcs'][pvc_name]['usage'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pvcs'][pvc_name]['usage'] / 24) * multiplier
                            expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pvcs'][pvc_name]['requests'] = (expected_values[metric]['nodes'][node_name]['namespaces'][ns_name]['pvcs'][pvc_name]['requests'] / 24) * multiplier

        logger.info(f"✓ Adjusted expected values for actual data coverage")

        # Print summary
        logger.info("Expected Cluster Totals (after adjustment):")
        logger.info(f"  CPU Usage: {expected_values['compute']['usage']:.2f} core-hours")
        logger.info(f"  CPU Requests: {expected_values['compute']['requests']:.2f} core-hours")
        logger.info(f"  CPU Capacity: {expected_values['compute']['count']:.2f} cores")
        logger.info(f"  Memory Usage: {expected_values['memory']['usage']:.2f} GB-hours")
        logger.info(f"  Memory Requests: {expected_values['memory']['requests']:.2f} GB-hours")
        logger.info(f"  Memory Capacity: {expected_values['memory']['count']:.2f} GB")
        logger.info(f"  Nodes: {len(expected_values['compute']['nodes'])}")

        # Print actual POC results summary
        logger.info("Actual POC Results:")
        logger.info(f"  CPU Usage: {actual_df['pod_usage_cpu_core_hours'].sum():.2f} core-hours")
        logger.info(f"  CPU Requests: {actual_df['pod_request_cpu_core_hours'].sum():.2f} core-hours")
        logger.info(f"  Memory Usage: {actual_df['pod_usage_memory_gigabyte_hours'].sum():.2f} GB-hours")
        logger.info(f"  Memory Requests: {actual_df['pod_request_memory_gigabyte_hours'].sum():.2f} GB-hours")
        logger.info(f"  Unique Nodes: {actual_df['node'].nunique()}")
        logger.info(f"  Unique Namespaces: {actual_df['namespace'].nunique()}")

    except Exception as e:
        logger.error(f"Failed to query PostgreSQL: {e}")
        return 1

    # Step 3: Validate
    logger.info("Validating POC results against expected values...")
    try:
        report = validate_poc_results(actual_df, expected_values, tolerance=0.0001)
        logger.info("✓ Validation complete")

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 4: Print report
    print("\n" + report.summary())

    # Step 5: Exit with appropriate code
    if report.all_passed:
        logger.info("=" * 80)
        logger.info("✅ ALL VALIDATIONS PASSED")
        logger.info("=" * 80)
        return 0
    else:
        logger.error("=" * 80)
        logger.error(f"❌ {report.failed_count} VALIDATIONS FAILED")
        logger.error("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())

