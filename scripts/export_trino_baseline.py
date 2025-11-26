#!/usr/bin/env python3
"""
Export production Trino results for comparison.

Usage:
    # List available dates
    python scripts/export_trino_baseline.py --list-dates --start 2025-10-01 --end 2025-10-31

    # Export specific date
    python scripts/export_trino_baseline.py --date 2025-10-15 --output baselines/trino_baseline_2025-10-15.json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from decimal import Decimal

try:
    import trino
except ImportError:
    print("❌ Error: 'trino' package not installed")
    print("   Install with: pip install trino")
    sys.exit(1)


def connect_to_trino(host='localhost', port=8080, catalog='postgres', schema=None, user=None):
    """Connect to Trino (queries PostgreSQL tables via Trino)."""
    import os
    
    # Auto-detect schema from environment if not provided
    if not schema:
        org_id = os.getenv('ORG_ID', 'org1234567')
        schema = org_id if org_id.startswith('org') else f'org{org_id}'
    
    # Auto-detect user from oc whoami if not provided
    if not user:
        try:
            import subprocess
            result = subprocess.run(['oc', 'whoami'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                user = result.stdout.strip()
        except:
            user = 'admin'  # Fallback
    
    try:
        conn = trino.dbapi.connect(
            host=host,
            port=port,
            user=user,
            catalog=catalog,  # Use 'postgres' catalog to query PostgreSQL tables
            schema=schema,
            http_scheme='http'
        )
        print(f"✓ Connected to Trino (user={user}, catalog={catalog}, schema={schema})")
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to Trino: {e}")
        print(f"   Make sure port-forward is running:")
        print(f"   oc port-forward -n cost-mgmt svc/trino-coordinator 8080:8080")
        sys.exit(1)


def list_dates(conn, start_date, end_date):
    """List dates with OCP-AWS data."""
    cursor = conn.cursor()

    query = f"""
    SELECT 
        usage_start,
        COUNT(*) as row_count,
        SUM(unblended_cost) as total_cost,
        COUNT(DISTINCT namespace) as namespaces,
        COUNT(DISTINCT cluster_id) as clusters
    FROM reporting_ocpawscostlineitem_project_daily_summary_p
    WHERE usage_start >= DATE '{start_date}'
      AND usage_start <= DATE '{end_date}'
    GROUP BY usage_start
    ORDER BY usage_start DESC
    """

    print(f"\n🔍 Querying Trino for dates {start_date} to {end_date}...\n")

    try:
        cursor.execute(query)
        results = cursor.fetchall()

        if not results:
            print(f"❌ No data found for date range {start_date} to {end_date}")
            return

        print(f"{'Date':<12} {'Rows':>10} {'Cost':>15} {'NS':>5} {'Clusters':>8}")
        print("-" * 60)

        for row in results:
            date = row[0]
            row_count = row[1]
            cost = row[2] or 0
            namespaces = row[3]
            clusters = row[4]
            print(f"{date!s:<12} {row_count:>10,} ${cost:>14,.2f} {namespaces:>5} {clusters:>8}")

        print(f"\n✓ Found {len(results)} dates with data")
        print(f"\nPick a date with good volume (1000+ rows, $100+ cost)")

    except Exception as e:
        print(f"❌ Query failed: {e}")
        sys.exit(1)


def export_date(conn, date, output_file):
    """Export Trino data for specific date."""
    cursor = conn.cursor()

    print(f"\n📊 Exporting Trino baseline for {date}...\n")

    # Query 1: Totals
    print("1. Querying totals...")
    try:
        cursor.execute(f"""
            SELECT 
                COUNT(*) as row_count,
                SUM(unblended_cost) as total_cost,
                SUM(blended_cost) as total_blended_cost,
                COUNT(DISTINCT namespace) as namespaces,
                COUNT(DISTINCT cluster_id) as clusters,
                COUNT(DISTINCT cluster_alias) as cluster_aliases
            FROM managed_reporting_ocpawscostlineitem_project_daily_summary
            WHERE usage_start = DATE '{date}'
        """)
        totals = cursor.fetchone()

        if totals[0] == 0:
            print(f"❌ No data found for date {date}")
            sys.exit(1)

        print(f"   ✓ {totals[0]:,} rows, ${totals[1] or 0:.2f} total cost")

    except Exception as e:
        print(f"❌ Failed to query totals: {e}")
        sys.exit(1)

    # Query 2: Per-Namespace
    print("2. Querying per-namespace costs...")
    try:
        cursor.execute(f"""
            SELECT 
                namespace,
                SUM(unblended_cost) as namespace_cost,
                SUM(blended_cost) as namespace_blended_cost,
                COUNT(*) as namespace_rows,
                COUNT(DISTINCT cluster_id) as namespace_clusters
            FROM managed_reporting_ocpawscostlineitem_project_daily_summary
            WHERE usage_start = DATE '{date}'
            GROUP BY namespace
            ORDER BY namespace_cost DESC
        """)
        namespaces = cursor.fetchall()
        print(f"   ✓ {len(namespaces)} namespaces")

    except Exception as e:
        print(f"❌ Failed to query namespaces: {e}")
        sys.exit(1)

    # Query 3: Provider UUIDs (for POC to use)
    print("3. Querying provider UUIDs...")
    try:
        cursor.execute(f"""
            SELECT DISTINCT 
                source,
                ocp_source
            FROM managed_reporting_ocpawscostlineitem_project_daily_summary
            WHERE usage_start = DATE '{date}'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            aws_provider_uuid = row[0]
            ocp_provider_uuid = row[1]
            provider_uuids = {
                'aws': aws_provider_uuid,
                'ocp': ocp_provider_uuid
            }
            print(f"   ✓ Found provider UUIDs:")
            print(f"     AWS: {aws_provider_uuid}")
            print(f"     OCP: {ocp_provider_uuid}")
        else:
            provider_uuids = {}
            print(f"   ⚠️  No provider UUIDs found")
        
    except Exception as e:
        print(f"⚠️  Failed to query provider UUIDs: {e}")
        provider_uuids = {}

    # Build baseline
    baseline = {
        'date': date,
        'exported_at': datetime.now().isoformat(),
        'source': 'production_trino',
        'provider_uuids': provider_uuids,
        'totals': {
            'row_count': totals[0],
            'total_cost': float(totals[1] or 0),
            'total_blended_cost': float(totals[2] or 0),
            'namespaces': totals[3],
            'clusters': totals[4],
            'cluster_aliases': totals[5]
        },
        'namespace_breakdown': [
            {
                'namespace': ns[0],
                'cost': float(ns[1] or 0),
                'blended_cost': float(ns[2] or 0),
                'rows': ns[3],
                'clusters': ns[4]
            }
            for ns in namespaces
        ]
    }

    # Save
    print(f"\n4. Saving to {output_file}...")
    try:
        with open(output_file, 'w') as f:
            json.dump(baseline, f, indent=2)
        print(f"   ✓ Baseline saved")
    except Exception as e:
        print(f"❌ Failed to save: {e}")
        sys.exit(1)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"✅ Trino Baseline Exported")
    print(f"{'=' * 60}")
    print(f"Date:       {date}")
    print(f"Rows:       {totals[0]:,}")
    print(f"Cost:       ${totals[1] or 0:,.2f}")
    print(f"Namespaces: {totals[3]}")
    print(f"Clusters:   {totals[4]}")
    print(f"Output:     {output_file}")
    print(f"{'=' * 60}")
    print(f"\n📝 Next Steps:")
    print(f"   1. Set provider UUIDs:")
    if provider_uuids:
        print(f"      export OCP_PROVIDER_UUID=\"{provider_uuids.get('ocp', 'N/A')}\"")
        print(f"      export AWS_PROVIDER_UUID=\"{provider_uuids.get('aws', 'N/A')}\"")
    print(f"   2. Run POC with date: {date}")
    print(f"   3. Compare results with: python scripts/compare_poc_vs_trino.py")

    return baseline


def main():
    parser = argparse.ArgumentParser(description='Export Trino baseline for POC comparison')
    parser.add_argument('--list-dates', action='store_true', help='List available dates')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--date', type=str, help='Specific date to export (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, help='Output JSON file')
    parser.add_argument('--host', type=str, default='localhost', help='Trino host (default: localhost)')
    parser.add_argument('--port', type=int, default=8080, help='Trino port (default: 8080)')
    parser.add_argument('--user', type=str, help='Trino user (default: from "oc whoami" or "admin")')
    parser.add_argument('--catalog', type=str, default='hive', help='Trino catalog (default: hive)')
    parser.add_argument('--schema', type=str, help='Trino schema (default: from ORG_ID env var or org1234567)')
    parser.add_argument('--org-id', type=str, help='Organization ID (alternative to --schema, will be prefixed with "org" if needed)')
    
    args = parser.parse_args()
    
    # Determine schema
    schema = args.schema
    if not schema and args.org_id:
        # Convert org_id to schema format
        schema = args.org_id if args.org_id.startswith('org') else f'org{args.org_id}'
    
    # Connect to Trino
    conn = connect_to_trino(args.host, args.port, args.catalog, schema, args.user)

    if args.list_dates:
        if not args.start or not args.end:
            print("❌ Error: --start and --end required for --list-dates")
            sys.exit(1)
        list_dates(conn, args.start, args.end)

    elif args.date:
        if not args.output:
            print("❌ Error: --output required for date export")
            sys.exit(1)
        export_date(conn, args.date, args.output)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

