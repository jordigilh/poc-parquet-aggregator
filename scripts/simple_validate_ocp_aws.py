#!/usr/bin/env python3
"""
Simple OCP-AWS Results Validator
Checks basic correctness without querying implementation-specific columns.
"""

import sys
import psycopg2
import os

def main():
    # Get config from environment
    schema = os.getenv('ORG_ID', 'org1234567')
    host = os.getenv('POSTGRES_HOST', '127.0.0.1')
    port = os.getenv('POSTGRES_PORT', '15432')
    user = os.getenv('POSTGRES_USER', 'koku')
    password = os.getenv('POSTGRES_PASSWORD', 'koku123')
    database = os.getenv('POSTGRES_DB', 'koku')

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )

        with conn.cursor() as cursor:
            # Check row count
            cursor.execute(f"""
                SELECT COUNT(*) as total_rows,
                       COUNT(DISTINCT cluster_id) as clusters,
                       COUNT(DISTINCT namespace) as namespaces,
                       SUM(unblended_cost) as total_cost
                FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
            """)
            result = cursor.fetchone()
            total_rows, clusters, namespaces, total_cost = result

            print(f"✅ Validation Results:")
            print(f"   Total rows: {total_rows}")
            print(f"   Clusters: {clusters}")
            print(f"   Namespaces: {namespaces}")
            print(f"   Total cost: ${total_cost:.2f}" if total_cost else "   Total cost: $0.00")

            if total_rows == 0:
                print("❌ No rows found in database")
                sys.exit(1)

            if total_cost is None or total_cost <= 0:
                print("❌ No costs attributed (total cost is 0)")
                sys.exit(1)

            print("✅ Basic validation passed")
            sys.exit(0)

    except Exception as e:
        print(f"❌ Validation failed: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    main()

