#!/usr/bin/env python3
"""
Collect POC results for comparison with Trino.

Usage:
    python scripts/collect_poc_results.py --date 2025-10-15 --output results/poc_results_2025-10-15.json
"""

import argparse
import json
import sys
from datetime import datetime

try:
    import psycopg2
except ImportError:
    print("❌ Error: 'psycopg2' package not installed")
    print("   Install with: pip install psycopg2-binary")
    sys.exit(1)


def connect_to_poc_db(host='localhost', port=15432, dbname='koku', user='koku', password='koku123'):
    """Connect to POC PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to POC database: {e}")
        print(f"   Connection details:")
        print(f"     Host: {host}")
        print(f"     Port: {port}")
        print(f"     Database: {dbname}")
        print(f"   Make sure local postgres-poc container is running:")
        print(f"     podman ps | grep postgres-poc")
        sys.exit(1)


def collect_results(conn, date, schema=None, output_file=None):
    """Collect POC results for specific date."""
    # Auto-detect schema from environment if not provided
    if not schema:
        import os
        org_id = os.getenv('ORG_ID', '1234567')
        schema = org_id if org_id.startswith('org') else f'org{org_id}'

    cursor = conn.cursor()

    table = f"{schema}.reporting_ocpawscostlineitem_project_daily_summary_p"

    print(f"\n📊 Collecting POC results for {date}...")
    print(f"   Schema: {schema}")
    print(f"   Table: {table}\n")

    # Query 1: Totals
    print("1. Querying totals...")
    try:
        cursor.execute(f"""
            SELECT
                COUNT(*) as row_count,
                COALESCE(SUM(unblended_cost), 0) as total_cost,
                COALESCE(SUM(blended_cost), 0) as total_blended_cost,
                COUNT(DISTINCT namespace) as namespaces,
                COUNT(DISTINCT cluster_id) as clusters,
                COUNT(DISTINCT cluster_alias) as cluster_aliases
            FROM {table}
            WHERE usage_start = %s
        """, (date,))
        totals = cursor.fetchone()

        if totals[0] == 0:
            print(f"❌ No data found for date {date}")
            print(f"   Table: {table}")
            print(f"   Did you run the POC aggregation for this date?")
            sys.exit(1)

        print(f"   ✓ {totals[0]:,} rows, ${float(totals[1]):.2f} total cost")

    except Exception as e:
        print(f"❌ Failed to query totals: {e}")
        sys.exit(1)

    # Query 2: Per-Namespace
    print("2. Querying per-namespace costs...")
    try:
        cursor.execute(f"""
            SELECT
                namespace,
                COALESCE(SUM(unblended_cost), 0) as namespace_cost,
                COALESCE(SUM(blended_cost), 0) as namespace_blended_cost,
                COUNT(*) as namespace_rows,
                COUNT(DISTINCT cluster_id) as namespace_clusters
            FROM {table}
            WHERE usage_start = %s
            GROUP BY namespace
            ORDER BY namespace_cost DESC
        """, (date,))
        namespaces = cursor.fetchall()
        print(f"   ✓ {len(namespaces)} namespaces")

    except Exception as e:
        print(f"❌ Failed to query namespaces: {e}")
        sys.exit(1)

    # Build results
    results = {
        'date': date,
        'collected_at': datetime.now().isoformat(),
        'source': 'poc_postgresql',
        'schema': schema,
        'totals': {
            'row_count': totals[0],
            'total_cost': float(totals[1]),
            'total_blended_cost': float(totals[2]),
            'namespaces': totals[3],
            'clusters': totals[4],
            'cluster_aliases': totals[5]
        },
        'namespace_breakdown': [
            {
                'namespace': ns[0],
                'cost': float(ns[1]),
                'blended_cost': float(ns[2]),
                'rows': ns[3],
                'clusters': ns[4]
            }
            for ns in namespaces
        ]
    }

    # Save
    if output_file:
        print(f"\n3. Saving to {output_file}...")
        try:
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"   ✓ Results saved")
        except Exception as e:
            print(f"❌ Failed to save: {e}")
            sys.exit(1)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"✅ POC Results Collected")
    print(f"{'=' * 60}")
    print(f"Date:       {date}")
    print(f"Rows:       {totals[0]:,}")
    print(f"Cost:       ${float(totals[1]):,.2f}")
    print(f"Namespaces: {totals[3]}")
    print(f"Clusters:   {totals[4]}")
    if output_file:
        print(f"Output:     {output_file}")
    print(f"{'=' * 60}")
    print(f"\n📝 Next Steps:")
    print(f"   1. Compare with Trino baseline")
    print(f"   2. Run: python scripts/compare_poc_vs_trino.py")

    return results


def main():
    parser = argparse.ArgumentParser(description='Collect POC results for Trino comparison')
    parser.add_argument('--date', type=str, required=True, help='Date to collect (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, help='Output JSON file')
    parser.add_argument('--host', type=str, default='localhost', help='PostgreSQL host (default: localhost)')
    parser.add_argument('--port', type=int, default=15432, help='PostgreSQL port (default: 15432)')
    parser.add_argument('--dbname', type=str, default='koku', help='Database name (default: koku)')
    parser.add_argument('--user', type=str, default='koku', help='Database user (default: koku)')
    parser.add_argument('--password', type=str, default='koku123', help='Database password (default: koku123)')
    parser.add_argument('--schema', type=str, help='Schema (default: from ORG_ID env var or org1234567)')
    parser.add_argument('--org-id', type=str, help='Organization ID (alternative to --schema, will be prefixed with "org" if needed)')

    args = parser.parse_args()

    # Determine schema
    schema = args.schema
    if not schema and args.org_id:
        # Convert org_id to schema format
        schema = args.org_id if args.org_id.startswith('org') else f'org{args.org_id}'

    # Connect to POC database
    conn = connect_to_poc_db(args.host, args.port, args.dbname, args.user, args.password)

    # Collect results
    collect_results(conn, args.date, schema, args.output)

    conn.close()


if __name__ == '__main__':
    main()

