#!/usr/bin/env python3
"""
Validate POC aggregation correctness by comparing PostgreSQL results
against expected values calculated from nise raw CSV data.

This is a SELF-CONTAINED validator that doesn't depend on Core.
"""

import sys
import os
import pandas as pd
import psycopg2
from pathlib import Path
from decimal import Decimal


def calculate_expected_aggregates(nise_data_dir, cluster_id):
    """
    Calculate expected aggregation values from nise CSV files.

    This replicates the aggregation logic to verify POC correctness.
    """
    print(f"📊 Calculating expected aggregates from nise data: {nise_data_dir}")

    # Find pod usage CSV files for this specific cluster only (including split files)
    pod_csv_files = list(Path(nise_data_dir).glob('*ocp_pod_usage*.csv'))

    if not pod_csv_files:
        print(f"❌ No pod usage CSV files found in {nise_data_dir}")
        return None

    # Filter to only files matching cluster_id
    # Cluster ID format: benchmark-small-f9383c1b
    # CSV file format: October-2025-benchmark-small-f9383c1b-ocp_pod_usage.csv
    filtered_files = []
    for f in pod_csv_files:
        if cluster_id in f.name:
            filtered_files.append(f)

    if not filtered_files:
        print(f"❌ No CSV files found for cluster {cluster_id}")
        print(f"   Available files:")
        for f in pod_csv_files:
            print(f"     - {f.name}")
        return None

    pod_csv_files = filtered_files
    print(f"   Found {len(pod_csv_files)} pod usage CSV file(s) for cluster {cluster_id}")

    # Read and combine all pod usage files
    dfs = []
    for csv_file in pod_csv_files:
        df = pd.read_csv(csv_file)
        dfs.append(df)
        print(f"   - {csv_file.name}: {len(df)} rows")

    pod_usage = pd.concat(dfs, ignore_index=True)
    print(f"   Total input rows: {len(pod_usage)}")

    # Parse interval_start to date
    pod_usage['interval_start_clean'] = pod_usage['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)
    pod_usage['usage_date'] = pd.to_datetime(pod_usage['interval_start_clean']).dt.date

    # Filter out rows with null nodes (like POC does)
    initial_rows = len(pod_usage)
    pod_usage = pod_usage[pod_usage['node'].notna() & (pod_usage['node'] != '')]
    filtered_rows = len(pod_usage)
    print(f"   Filtered out {initial_rows - filtered_rows} rows with null nodes")

    # Group by date, namespace, node (like POC daily summary)
    # NOTE: POC groups by date+namespace+node+resource_id, but for validation
    # we'll do date+namespace+node to check totals
    expected = pod_usage.groupby(['usage_date', 'namespace', 'node']).agg({
        'pod_usage_cpu_core_seconds': 'sum',
        'pod_request_cpu_core_seconds': 'sum',
        'pod_limit_cpu_core_seconds': 'sum',
        'pod_usage_memory_byte_seconds': 'sum',
        'pod_request_memory_byte_seconds': 'sum',
        'pod_limit_memory_byte_seconds': 'sum',
    }).reset_index()

    # Convert to hours and gigabytes (like POC does)
    expected['cpu_usage_core_hours'] = expected['pod_usage_cpu_core_seconds'] / 3600
    expected['cpu_request_core_hours'] = expected['pod_request_cpu_core_seconds'] / 3600
    expected['cpu_limit_core_hours'] = expected['pod_limit_cpu_core_seconds'] / 3600

    expected['memory_usage_gb_hours'] = expected['pod_usage_memory_byte_seconds'] / (1024**3 * 3600)
    expected['memory_request_gb_hours'] = expected['pod_request_memory_byte_seconds'] / (1024**3 * 3600)
    expected['memory_limit_gb_hours'] = expected['pod_limit_memory_byte_seconds'] / (1024**3 * 3600)

    print(f"   Expected aggregated rows: {len(expected)}")
    print(f"   ✅ Expected values calculated")

    return expected


def query_poc_results(cluster_id, year, month):
    """Query POC aggregation results from PostgreSQL."""
    print(f"\n📊 Querying POC results from PostgreSQL...")

    # Get connection info from environment
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'database': os.getenv('POSTGRES_DB', 'koku'),
        'user': os.getenv('POSTGRES_USER', 'koku'),
        'password': os.getenv('POSTGRES_PASSWORD', 'koku123'),
    }
    schema = os.getenv('POSTGRES_SCHEMA', 'org1234567')

    print(f"   Connecting to {db_config['host']}:{db_config['port']}/{db_config['database']}")

    conn = psycopg2.connect(**db_config)

    # Query aggregated results
    # Group by date, namespace, node to match expected calculation
    # Filter by year/month to avoid comparing against old data from previous runs
    query = f"""
        SELECT
            usage_start,
            namespace,
            node,
            SUM(pod_usage_cpu_core_hours) as cpu_usage_core_hours,
            SUM(pod_request_cpu_core_hours) as cpu_request_core_hours,
            SUM(pod_limit_cpu_core_hours) as cpu_limit_core_hours,
            SUM(pod_usage_memory_gigabyte_hours) as memory_usage_gb_hours,
            SUM(pod_request_memory_gigabyte_hours) as memory_request_gb_hours,
            SUM(pod_limit_memory_gigabyte_hours) as memory_limit_gb_hours,
            COUNT(*) as row_count
        FROM {schema}.reporting_ocpusagelineitem_daily_summary
        WHERE cluster_id = %s
          AND EXTRACT(YEAR FROM usage_start) = %s
          AND EXTRACT(MONTH FROM usage_start) = %s
        GROUP BY usage_start, namespace, node
        ORDER BY usage_start, namespace, node
    """

    actual = pd.read_sql(query, conn, params=[cluster_id, int(year), int(month)])
    conn.close()

    print(f"   POC aggregated rows: {len(actual)}")
    print(f"   ✅ POC results retrieved")

    return actual


def compare_results(expected, actual, tolerance=0.01):
    """
    Compare expected vs actual aggregation results.

    Args:
        expected: DataFrame with expected values
        actual: DataFrame with actual POC values
        tolerance: Acceptable relative difference (0.01 = 1%)

    Returns:
        True if all values match within tolerance
    """
    print(f"\n🔍 Comparing expected vs actual results...")
    print(f"   Tolerance: {tolerance*100:.1f}%")

    # Rename columns for merge
    expected = expected.rename(columns={'usage_date': 'usage_start'})

    # Convert usage_start to same type
    expected['usage_start'] = pd.to_datetime(expected['usage_start'])
    actual['usage_start'] = pd.to_datetime(actual['usage_start'])

    # Merge on keys
    merged = expected.merge(
        actual,
        on=['usage_start', 'namespace', 'node'],
        suffixes=('_expected', '_actual'),
        how='outer',
        indicator=True
    )

    # Check for missing rows
    missing_in_actual = merged[merged['_merge'] == 'left_only']
    missing_in_expected = merged[merged['_merge'] == 'right_only']

    if len(missing_in_actual) > 0:
        print(f"\n⚠️  {len(missing_in_actual)} rows in expected but NOT in actual:")
        print(missing_in_actual[['usage_start', 'namespace', 'node']].head(5))

    if len(missing_in_expected) > 0:
        print(f"\n⚠️  {len(missing_in_expected)} rows in actual but NOT in expected:")
        print(missing_in_expected[['usage_start', 'namespace', 'node']].head(5))

    # Compare values for matched rows
    both = merged[merged['_merge'] == 'both'].copy()

    if len(both) == 0:
        print("\n❌ NO MATCHING ROWS! Expected and actual have completely different data.")
        return False

    print(f"\n   Matched rows: {len(both)}")

    # Metrics to compare
    metrics = [
        'cpu_usage_core_hours',
        'cpu_request_core_hours',
        'cpu_limit_core_hours',
        'memory_usage_gb_hours',
        'memory_request_gb_hours',
        'memory_limit_gb_hours',
    ]

    all_pass = True
    failures = []

    for metric in metrics:
        expected_col = f"{metric}_expected"
        actual_col = f"{metric}_actual"

        # Calculate relative difference
        both['diff'] = both[actual_col] - both[expected_col]
        both['rel_diff'] = abs(both['diff'] / both[expected_col].replace(0, 1))  # Avoid div by zero

        # Find rows exceeding tolerance
        bad_rows = both[both['rel_diff'] > tolerance]

        if len(bad_rows) > 0:
            all_pass = False
            max_diff = bad_rows['rel_diff'].max()
            failures.append({
                'metric': metric,
                'bad_rows': len(bad_rows),
                'max_diff_pct': max_diff * 100
            })

            print(f"\n   ❌ {metric}: {len(bad_rows)} rows exceed {tolerance*100:.1f}% tolerance")
            print(f"      Max difference: {max_diff*100:.1f}%")
            print(f"      Sample bad rows:")
            sample = bad_rows[['namespace', 'node', expected_col, actual_col, 'rel_diff']].head(3)
            for _, row in sample.iterrows():
                print(f"        {row['namespace']}/{row['node']}: "
                      f"expected={row[expected_col]:.4f}, "
                      f"actual={row[actual_col]:.4f}, "
                      f"diff={row['rel_diff']*100:.2f}%")
        else:
            print(f"   ✅ {metric}: All values within tolerance")

    # Summary
    print(f"\n{'='*80}")
    if all_pass:
        print("✅ ALL VALIDATION CHECKS PASSED")
        print(f"   - {len(both)} rows matched")
        print(f"   - {len(metrics)} metrics validated")
        print(f"   - All within {tolerance*100:.1f}% tolerance")
        return True
    else:
        print("❌ VALIDATION FAILED")
        print(f"   - {len(failures)} metrics had errors:")
        for f in failures:
            print(f"     • {f['metric']}: {f['bad_rows']} bad rows (max {f['max_diff_pct']:.1f}% diff)")
        return False


def main():
    """Main validation function."""
    if len(sys.argv) < 2:
        print("Usage: validate_benchmark_correctness.py <nise_data_dir> [cluster_id] [year] [month]")
        print("")
        print("Example:")
        print("  validate_benchmark_correctness.py /tmp/nise-small-20251121_085332")
        print("  validate_benchmark_correctness.py /tmp/nise-small-20251121_085332 benchmark-small-abc 2025 10")
        sys.exit(1)

    nise_data_dir = sys.argv[1]

    # Extract cluster_id, year, month from metadata if not provided
    if len(sys.argv) >= 5:
        cluster_id = sys.argv[2]
        year = sys.argv[3]
        month = sys.argv[4]
    else:
        # Try to read from metadata
        import json
        metadata_files = list(Path(nise_data_dir).glob('metadata_*.json'))
        if metadata_files:
            with open(metadata_files[0]) as f:
                metadata = json.load(f)
                cluster_id = metadata.get('cluster_id')
                year = metadata.get('year', '2025')
                month = metadata.get('month', '10')
        else:
            print("❌ Could not find metadata file or determine cluster_id")
            sys.exit(1)

    print("="*80)
    print("POC AGGREGATION CORRECTNESS VALIDATION")
    print("="*80)
    print(f"Nise data: {nise_data_dir}")
    print(f"Cluster ID: {cluster_id}")
    print(f"Year/Month: {year}/{month}")
    print("="*80)

    # Step 1: Calculate expected values from nise CSV
    expected = calculate_expected_aggregates(nise_data_dir, cluster_id)
    if expected is None:
        print("\n❌ Failed to calculate expected values")
        sys.exit(1)

    # Step 2: Query actual POC results
    try:
        actual = query_poc_results(cluster_id, year, month)
    except Exception as e:
        print(f"\n❌ Failed to query POC results: {e}")
        sys.exit(1)

    # Step 3: Compare
    success = compare_results(expected, actual, tolerance=0.01)

    # Exit code
    if success:
        print("\n✅ CORRECTNESS VALIDATION PASSED")
        sys.exit(0)
    else:
        print("\n❌ CORRECTNESS VALIDATION FAILED")
        sys.exit(1)


if __name__ == '__main__':
    main()

