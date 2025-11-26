#!/usr/bin/env python3
"""
Export production PostgreSQL results (from Trino aggregation) for comparison.

Usage:
    # List available dates
    python scripts/export_postgres_baseline.py --list-dates --start 2025-10-01 --end 2025-10-31
    
    # Export specific date
    python scripts/export_postgres_baseline.py --date 2025-10-15 --output baselines/postgres_baseline.json
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


def connect_to_postgres(host='localhost', port=5432, dbname='postgres', user='koku', password='koku'):
    """Connect to production PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password
        )
        print(f"✓ Connected to PostgreSQL (host={host}, port={port}, dbname={dbname})")
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        print(f"   Make sure port-forward is running:")
        print(f"   oc port-forward -n cost-mgmt svc/postgresql 5432:5432")
        sys.exit(1)


def list_dates(conn, schema, start_date, end_date):
    """List dates with OCP-AWS data in production."""
    cursor = conn.cursor()
    
    table = f"{schema}.reporting_ocpawscostlineitem_project_daily_summary_p"
    
    query = f"""
    SELECT 
        usage_start,
        COUNT(*) as row_count,
        SUM(unblended_cost) as total_cost,
        COUNT(DISTINCT namespace) as namespaces,
        COUNT(DISTINCT cluster_id) as clusters
    FROM {table}
    WHERE usage_start >= %s
      AND usage_start <= %s
    GROUP BY usage_start
    ORDER BY usage_start DESC
    """
    
    print(f"\n🔍 Querying production PostgreSQL for dates {start_date} to {end_date}...")
    print(f"   Table: {table}\n")
    
    try:
        cursor.execute(query, (start_date, end_date))
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
        print(f"\n📝 Pick a date with good volume (1000+ rows, $100+ cost)")
        
    except Exception as e:
        print(f"❌ Query failed: {e}")
        sys.exit(1)


def export_date(conn, schema, date, output_file):
    """Export production PostgreSQL data for specific date."""
    cursor = conn.cursor()
    
    table = f"{schema}.reporting_ocpawscostlineitem_project_daily_summary_p"
    
    print(f"\n📊 Exporting production baseline for {date}...")
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
    
    # Query 3: Provider UUIDs
    print("3. Querying provider UUIDs...")
    try:
        cursor.execute(f"""
            SELECT DISTINCT 
                source_uuid
            FROM {table}
            WHERE usage_start = %s
            LIMIT 1
        """, (date,))
        row = cursor.fetchone()
        if row:
            source_uuid = str(row[0])
            print(f"   ✓ Source UUID: {source_uuid}")
        else:
            source_uuid = None
            print(f"   ⚠️  No source UUID found")
        
    except Exception as e:
        print(f"⚠️  Failed to query source UUID: {e}")
        source_uuid = None
    
    # Build baseline
    baseline = {
        'date': str(date),
        'exported_at': datetime.now().isoformat(),
        'source': 'production_postgresql',
        'schema': schema,
        'source_uuid': source_uuid,
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
    print(f"✅ Production Baseline Exported")
    print(f"{'=' * 60}")
    print(f"Date:       {date}")
    print(f"Rows:       {totals[0]:,}")
    print(f"Cost:       ${float(totals[1]):,.2f}")
    print(f"Namespaces: {totals[3]}")
    print(f"Clusters:   {totals[4]}")
    print(f"Output:     {output_file}")
    print(f"{'=' * 60}")
    print(f"\n📝 Next Steps:")
    print(f"   1. Run POC aggregation for same date")
    print(f"   2. Use: python scripts/collect_poc_results.py --date {date}")
    print(f"   3. Compare: python scripts/compare_poc_vs_trino.py")
    
    return baseline


def main():
    parser = argparse.ArgumentParser(description='Export production PostgreSQL baseline for POC comparison')
    parser.add_argument('--list-dates', action='store_true', help='List available dates')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--date', type=str, help='Specific date to export (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, help='Output JSON file')
    parser.add_argument('--host', type=str, default='localhost', help='PostgreSQL host (default: localhost)')
    parser.add_argument('--port', type=int, default=5432, help='PostgreSQL port (default: 5432)')
    parser.add_argument('--dbname', type=str, default='postgres', help='Database name (default: postgres)')
    parser.add_argument('--user', type=str, default='koku', help='Database user (default: koku)')
    parser.add_argument('--password', type=str, default='koku', help='Database password (default: koku)')
    parser.add_argument('--schema', type=str, help='Schema (default: from ORG_ID env var or org1234567)')
    parser.add_argument('--org-id', type=str, help='Organization ID (alternative to --schema)')
    
    args = parser.parse_args()
    
    # Determine schema
    schema = args.schema
    if not schema and args.org_id:
        schema = args.org_id if args.org_id.startswith('org') else f'org{args.org_id}'
    if not schema:
        import os
        org_id = os.getenv('ORG_ID', '1234567')
        schema = org_id if org_id.startswith('org') else f'org{org_id}'
    
    # Connect to production PostgreSQL
    conn = connect_to_postgres(args.host, args.port, args.dbname, args.user, args.password)
    
    if args.list_dates:
        if not args.start or not args.end:
            print("❌ Error: --start and --end required for --list-dates")
            sys.exit(1)
        list_dates(conn, schema, args.start, args.end)
    
    elif args.date:
        if not args.output:
            print("❌ Error: --output required for date export")
            sys.exit(1)
        export_date(conn, schema, args.date, args.output)
    
    else:
        parser.print_help()
        sys.exit(1)
    
    conn.close()


if __name__ == '__main__':
    main()

