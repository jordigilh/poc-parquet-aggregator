#!/usr/bin/env python3
"""
Validate POC results against Trino.

Compares Pod + Storage aggregation results from POC (PostgreSQL)
with Trino's existing aggregation to ensure 1:1 parity.

Usage:
    python3 scripts/validate_against_trino.py <cluster_id> <provider_uuid> <year> <month>

Example:
    python3 scripts/validate_against_trino.py iqe-test-cluster abc-123-def 2025 10
"""

import sys
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd


def get_postgres_connection():
    """Get PostgreSQL connection (POC results)."""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'postgresql.cost-management.svc.cluster.local'),
        port=int(os.getenv('POSTGRES_PORT', 5432)),
        database=os.getenv('POSTGRES_DB', 'koku'),
        user=os.getenv('POSTGRES_USER', 'koku'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def get_trino_connection():
    """Get Trino connection (production results)."""
    try:
        import trino
        return trino.dbapi.connect(
            host=os.getenv('TRINO_HOST', 'trino-coordinator.cost-management.svc.cluster.local'),
            port=int(os.getenv('TRINO_PORT', 8080)),
            user=os.getenv('TRINO_USER', 'koku'),
            catalog='hive',
            schema=os.getenv('POSTGRES_SCHEMA', 'org1234567')
        )
    except ImportError:
        print("❌ ERROR: trino module not installed")
        print("Install with: pip install trino")
        sys.exit(1)


def query_postgres(cluster_id, provider_uuid, year, month):
    """Query POC results from PostgreSQL."""
    schema = os.getenv('POSTGRES_SCHEMA', 'org1234567')

    print("📊 Querying PostgreSQL (POC results)...")

    conn = get_postgres_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Get summary stats
    query = f"""
    SELECT
        data_source,
        COUNT(*) as row_count,
        COUNT(DISTINCT namespace) as unique_namespaces,
        COUNT(DISTINCT node) as unique_nodes,
        MIN(usage_start) as min_date,
        MAX(usage_start) as max_date,

        -- Pod metrics (should be NULL for Storage)
        SUM(pod_usage_cpu_core_hours) as total_cpu_usage,
        SUM(pod_request_cpu_core_hours) as total_cpu_request,
        SUM(pod_usage_memory_gigabyte_hours) as total_memory_usage,
        SUM(pod_request_memory_gigabyte_hours) as total_memory_request,

        -- Storage metrics (should be NULL for Pod)
        SUM(persistentvolumeclaim_capacity_gigabyte_months) as total_storage_capacity,
        SUM(volume_request_storage_gigabyte_months) as total_storage_request,
        SUM(persistentvolumeclaim_usage_gigabyte_months) as total_storage_usage,

        COUNT(DISTINCT persistentvolumeclaim) as unique_pvcs

    FROM {schema}.reporting_ocpusagelineitem_daily_summary
    WHERE cluster_id = %s
      AND source_uuid::text = %s
      AND EXTRACT(YEAR FROM usage_start) = %s
      AND EXTRACT(MONTH FROM usage_start) = %s
    GROUP BY data_source
    ORDER BY data_source
    """

    cursor.execute(query, (cluster_id, provider_uuid, year, month))
    results = cursor.fetchall()

    cursor.close()
    conn.close()

    return results


def query_trino(cluster_id, provider_uuid, year, month):
    """Query Trino results (production)."""
    schema = os.getenv('POSTGRES_SCHEMA', 'org1234567')

    print("📊 Querying Trino (production results)...")

    conn = get_trino_connection()
    cursor = conn.cursor()

    # Get summary stats
    query = f"""
    SELECT
        data_source,
        COUNT(*) as row_count,
        COUNT(DISTINCT namespace) as unique_namespaces,
        COUNT(DISTINCT node) as unique_nodes,
        MIN(usage_start) as min_date,
        MAX(usage_start) as max_date,

        -- Pod metrics
        SUM(pod_usage_cpu_core_hours) as total_cpu_usage,
        SUM(pod_request_cpu_core_hours) as total_cpu_request,
        SUM(pod_usage_memory_gigabyte_hours) as total_memory_usage,
        SUM(pod_request_memory_gigabyte_hours) as total_memory_request,

        -- Storage metrics
        SUM(persistentvolumeclaim_capacity_gigabyte_months) as total_storage_capacity,
        SUM(volume_request_storage_gigabyte_months) as total_storage_request,
        SUM(persistentvolumeclaim_usage_gigabyte_months) as total_storage_usage,

        COUNT(DISTINCT persistentvolumeclaim) as unique_pvcs

    FROM hive.{schema}.reporting_ocpusagelineitem_daily_summary
    WHERE cluster_id = '{cluster_id}'
      AND source = '{provider_uuid}'
      AND year = '{year}'
      AND month = '{month}'
    GROUP BY data_source
    ORDER BY data_source
    """

    cursor.execute(query)
    results = cursor.fetchall()

    cursor.close()
    conn.close()

    # Convert to dict format (same as PostgreSQL)
    columns = [
        'data_source', 'row_count', 'unique_namespaces', 'unique_nodes',
        'min_date', 'max_date', 'total_cpu_usage', 'total_cpu_request',
        'total_memory_usage', 'total_memory_request', 'total_storage_capacity',
        'total_storage_request', 'total_storage_usage', 'unique_pvcs'
    ]

    return [dict(zip(columns, row)) for row in results]


def compare_results(postgres_results, trino_results, tolerance=0.01):
    """
    Compare POC vs Trino results.

    Args:
        postgres_results: Results from PostgreSQL (POC)
        trino_results: Results from Trino (production)
        tolerance: Acceptable difference percentage (default 1%)

    Returns:
        dict with comparison results
    """
    print("\n" + "="*80)
    print("=== COMPARISON: POC (PostgreSQL) vs Trino ===")
    print("="*80)

    # Convert to DataFrames for easier comparison
    pg_df = pd.DataFrame(postgres_results)
    trino_df = pd.DataFrame(trino_results)

    if pg_df.empty:
        print("\n❌ ERROR: No data found in PostgreSQL (POC)")
        return {'all_match': False, 'error': 'No POC data'}

    if trino_df.empty:
        print("\n❌ ERROR: No data found in Trino")
        return {'all_match': False, 'error': 'No Trino data'}

    # Check data sources
    pg_sources = set(pg_df['data_source'].unique())
    trino_sources = set(trino_df['data_source'].unique())

    print(f"\nData Sources:")
    print(f"  POC:   {sorted(pg_sources)}")
    print(f"  Trino: {sorted(trino_sources)}")

    if pg_sources != trino_sources:
        print(f"\n⚠️  WARNING: Data source mismatch")
        print(f"  Only in POC:   {pg_sources - trino_sources}")
        print(f"  Only in Trino: {trino_sources - pg_sources}")

    # Compare each data source
    all_match = True
    comparison_results = []

    for data_source in sorted(pg_sources & trino_sources):
        print(f"\n{'='*80}")
        print(f"=== Data Source: {data_source} ===")
        print('='*80)

        pg_row = pg_df[pg_df['data_source'] == data_source].iloc[0]
        trino_row = trino_df[trino_df['data_source'] == data_source].iloc[0]

        source_match = True

        # Compare row count
        pg_count = pg_row['row_count']
        trino_count = trino_row['row_count']

        print(f"\n1. Row Count")
        print(f"   POC:   {pg_count:,}")
        print(f"   Trino: {trino_count:,}")

        if pg_count != trino_count:
            diff_pct = abs(pg_count - trino_count) / trino_count * 100
            print(f"   ❌ MISMATCH: {abs(pg_count - trino_count):,} rows difference ({diff_pct:.2f}%)")
            all_match = False
            source_match = False
        else:
            print(f"   ✅ MATCH")

        # Compare unique counts
        print(f"\n2. Unique Entities")

        for field in ['unique_namespaces', 'unique_nodes', 'unique_pvcs']:
            pg_val = pg_row[field]
            trino_val = trino_row[field]

            field_name = field.replace('unique_', '').replace('_', ' ').title()
            print(f"   {field_name}:")
            print(f"     POC:   {pg_val}")
            print(f"     Trino: {trino_val}")

            if pg_val != trino_val:
                print(f"     ❌ MISMATCH")
                all_match = False
                source_match = False
            else:
                print(f"     ✅ MATCH")

        # Compare metrics
        print(f"\n3. Metrics Comparison")

        metrics = {
            'total_cpu_usage': 'CPU Usage (core-hours)',
            'total_cpu_request': 'CPU Request (core-hours)',
            'total_memory_usage': 'Memory Usage (GB-hours)',
            'total_memory_request': 'Memory Request (GB-hours)',
            'total_storage_capacity': 'Storage Capacity (GB-months)',
            'total_storage_request': 'Storage Request (GB-months)',
            'total_storage_usage': 'Storage Usage (GB-months)'
        }

        for metric, label in metrics.items():
            pg_val = pg_row[metric]
            trino_val = trino_row[metric]

            # Skip if both NULL (expected for cross-data_source metrics)
            if pd.isna(pg_val) and pd.isna(trino_val):
                continue

            # Check if one is NULL but not the other
            if pd.isna(pg_val) != pd.isna(trino_val):
                print(f"   {label}:")
                print(f"     POC:   {pg_val}")
                print(f"     Trino: {trino_val}")
                print(f"     ❌ MISMATCH: One is NULL, other is not")
                all_match = False
                source_match = False
                continue

            # Compare values
            if not pd.isna(pg_val) and not pd.isna(trino_val):
                pg_val = float(pg_val)
                trino_val = float(trino_val)

                print(f"   {label}:")
                print(f"     POC:   {pg_val:,.2f}")
                print(f"     Trino: {trino_val:,.2f}")

                if trino_val == 0:
                    if pg_val != 0:
                        print(f"     ❌ MISMATCH")
                        all_match = False
                        source_match = False
                    else:
                        print(f"     ✅ MATCH (both zero)")
                else:
                    diff_pct = abs(pg_val - trino_val) / trino_val * 100

                    if diff_pct > tolerance * 100:
                        print(f"     ❌ MISMATCH: {diff_pct:.4f}% difference (tolerance: {tolerance*100}%)")
                        all_match = False
                        source_match = False
                    else:
                        print(f"     ✅ MATCH (within {tolerance*100}% tolerance)")

        # Compare dates
        print(f"\n4. Date Range")
        print(f"   POC:   {pg_row['min_date']} to {pg_row['max_date']}")
        print(f"   Trino: {trino_row['min_date']} to {trino_row['max_date']}")

        if pg_row['min_date'] != trino_row['min_date'] or pg_row['max_date'] != trino_row['max_date']:
            print(f"   ⚠️  Date range mismatch (may be expected)")
        else:
            print(f"   ✅ MATCH")

        comparison_results.append({
            'data_source': data_source,
            'match': source_match
        })

    # Final summary
    print("\n" + "="*80)
    print("=== FINAL SUMMARY ===")
    print("="*80)

    for result in comparison_results:
        status = "✅ PASS" if result['match'] else "❌ FAIL"
        print(f"{status}: {result['data_source']}")

    if all_match:
        print("\n✅✅✅ SUCCESS: POC matches Trino 1:1 ✅✅✅")
        print("Ready to proceed with OCP-in-AWS implementation!")
    else:
        print("\n❌ FAIL: Discrepancies found between POC and Trino")
        print("Review differences above and investigate before proceeding.")

    return {
        'all_match': all_match,
        'comparison_results': comparison_results,
        'tolerance': tolerance
    }


def main():
    """Main entry point."""
    if len(sys.argv) != 5:
        print("Usage: python3 scripts/validate_against_trino.py <cluster_id> <provider_uuid> <year> <month>")
        print("Example: python3 scripts/validate_against_trino.py iqe-test-cluster abc-123 2025 10")
        sys.exit(1)

    cluster_id = sys.argv[1]
    provider_uuid = sys.argv[2]
    year = sys.argv[3]
    month = sys.argv[4]

    print("="*80)
    print("=== Trino Validation: POC vs Production ===")
    print("="*80)
    print(f"Cluster ID:    {cluster_id}")
    print(f"Provider UUID: {provider_uuid}")
    print(f"Year:          {year}")
    print(f"Month:         {month}")
    print(f"Schema:        {os.getenv('POSTGRES_SCHEMA', 'org1234567')}")
    print("="*80)

    try:
        # Query both systems
        postgres_results = query_postgres(cluster_id, provider_uuid, year, month)
        trino_results = query_trino(cluster_id, provider_uuid, year, month)

        # Compare
        result = compare_results(postgres_results, trino_results)

        # Exit code
        sys.exit(0 if result['all_match'] else 1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

