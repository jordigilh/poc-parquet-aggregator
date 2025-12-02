#!/usr/bin/env python3
"""
Core-Style Validation: Validate Totals, Not Specific Matches

This validation approach mirrors Core's methodology:
- Validates total costs match expected values (within tolerance)
- Validates namespace-level costs (if specified)
- Validates row counts (approximately)
- Does NOT validate specific resource ID or tag matching

This is sufficient to prove the POC works correctly without requiring
complex test data alignment.
"""

import os
import sys
import yaml
import psycopg2
from pathlib import Path
from decimal import Decimal
from typing import Dict, Any


def load_manifest(manifest_path: str) -> Dict[str, Any]:
    """Load test manifest."""
    with open(manifest_path, 'r') as f:
        return yaml.safe_load(f)


def detect_cost_column(manifest: Dict[str, Any], manifest_path: str) -> str:
    """
    Detect which cost column to use for validation based on scenario type.

    For SavingsPlan scenarios, use 'savingsplan_effective_cost'.
    For regular scenarios, use 'unblended_cost'.

    Detection logic:
    1. Check if manifest has 'total_amortized_cost' in expected_outcome
    2. Check if manifest filename contains 'savingsplan'
    3. Default to 'unblended_cost'
    """
    expected = manifest.get('expected_outcome', {})

    # Check if this is a SavingsPlan scenario
    if 'total_amortized_cost' in expected:
        # Manifest explicitly specifies amortized cost validation
        return 'savingsplan_effective_cost'

    # Check filename
    if 'savingsplan' in manifest_path.lower():
        return 'savingsplan_effective_cost'

    # Default to unblended_cost for regular scenarios
    return 'unblended_cost'


def query_results(
    db_config: Dict[str, str],
    cost_column: str = 'unblended_cost',
    start_date: str = None,
    end_date: str = None
) -> Dict[str, Any]:
    """
    Query aggregated results from PostgreSQL.

    Args:
        db_config: Database connection configuration
        cost_column: Which cost column to query ('unblended_cost', 'calculated_amortized_cost',
                     'savingsplan_effective_cost')
        start_date: Filter by usage_start >= start_date (YYYY-MM-DD format)
        end_date: Filter by usage_start < end_date (YYYY-MM-DD format)
    """
    conn = psycopg2.connect(
        host=db_config['host'],
        port=db_config['port'],
        database=db_config['database'],
        user=db_config['user'],
        password=db_config['password']
    )

    schema = db_config.get('schema', 'org1234567')

    # Build WHERE clause for date filtering
    date_filter = ""
    if start_date and end_date:
        date_filter = f"WHERE usage_start::date >= '{start_date}' AND usage_start::date < '{end_date}'"

    # Query totals
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT
                COUNT(*) as total_rows,
                ROUND(SUM({cost_column})::numeric, 2) as total_cost,
                COUNT(DISTINCT cluster_id) as clusters,
                COUNT(DISTINCT namespace) as namespaces
            FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
            {date_filter};
        """)
        row = cursor.fetchone()
        totals = {
            'total_rows': row[0],
            'total_cost': float(row[1]) if row[1] else 0.0,
            'clusters': row[2],
            'namespaces': row[3]
        }

    # Query namespace-level costs
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT
                namespace,
                ROUND(SUM({cost_column})::numeric, 2) as cost
            FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
            {date_filter}
            GROUP BY namespace
            ORDER BY namespace;
        """)
        namespaces = {row[0]: float(row[1]) if row[1] else 0.0 for row in cursor.fetchall()}

    conn.close()

    return {
        'totals': totals,
        'namespaces': namespaces,
        'cost_column_used': cost_column
    }


def validate_totals(manifest: Dict, results: Dict) -> bool:
    """
    Validate totals match expected values (Core-style).

    Returns True if validation passes, False otherwise.
    """
    expected = manifest.get('expected_outcome', {})
    actual = results['totals']
    cost_column = results.get('cost_column_used', 'unblended_cost')

    validation_passed = True
    errors = []

    # Tolerance for floating point comparisons (10 cents)
    cost_tolerance = 0.10

    # Validation 1: Total cost
    # For SavingsPlan scenarios, check 'total_amortized_cost'
    # For regular scenarios, check 'total_cost' or 'attributed_cost'
    if cost_column == 'savingsplan_effective_cost':
        # SavingsPlan scenario: use total_amortized_cost or attributed_cost
        expected_cost_value = expected.get('total_amortized_cost') or expected.get('attributed_cost')
    else:
        # Regular scenario: use total_cost or attributed_cost
        expected_cost_value = expected.get('total_cost') or expected.get('attributed_cost')

    if expected_cost_value is not None:
        expected_cost = Decimal(str(expected_cost_value))
        actual_cost = Decimal(str(actual['total_cost']))
        diff = abs(actual_cost - expected_cost)

        # Critical check: If expected > $0 but actual = $0, this is a FAILURE
        if expected_cost > 0 and actual_cost == 0:
            errors.append(f"❌ CRITICAL: Expected cost ${expected_cost} but got $0.00 (matching likely failed)")
            validation_passed = False
        elif diff > Decimal(str(cost_tolerance)):
            errors.append(f"Total cost mismatch: expected ${expected_cost}, got ${actual_cost} (diff: ${diff})")
            validation_passed = False
        else:
            cost_type = "amortized" if cost_column == 'savingsplan_effective_cost' else "unblended"
            print(f"✅ Total cost ({cost_type}): ${actual_cost} (expected ${expected_cost}, within tolerance)")
    else:
        # Warning: No cost validation specified
        print(f"⚠️  No expected cost specified in manifest (skipping cost validation)")
        if actual['total_cost'] == 0:
            print(f"   WARNING: Actual cost is $0.00 - this may indicate matching failure")

    # Validation 2: Row count (approximate - within 20%)
    if 'min_rows' in expected:
        min_rows = expected['min_rows']
        if actual['total_rows'] < min_rows:
            errors.append(f"Row count too low: expected >={min_rows}, got {actual['total_rows']}")
            validation_passed = False
        else:
            print(f"✅ Row count: {actual['total_rows']} (expected >={min_rows})")

    # Validation 3: Namespace counts
    if 'namespaces' in expected:
        # Handle both old format (dict) and new format (int)
        if isinstance(expected['namespaces'], dict):
            # Old format: namespaces is a dict with namespace details
            expected_ns_count = len(expected['namespaces'])
        else:
            # New format: namespaces is an integer
            expected_ns_count = expected['namespaces']

        actual_ns_count = actual['namespaces']
        # Allow some variance (within 20%)
        tolerance_pct = 0.20
        if abs(actual_ns_count - expected_ns_count) > expected_ns_count * tolerance_pct:
            errors.append(f"Namespace count mismatch: expected ~{expected_ns_count}, got {actual_ns_count}")
            validation_passed = False
        else:
            print(f"✅ Namespaces: {actual_ns_count} (expected ~{expected_ns_count})")

    # Validation 4: Namespace-level costs (if specified)
    if 'namespace_costs' in expected:
        for ns_name, expected_cost in expected['namespace_costs'].items():
            actual_cost = results['namespaces'].get(ns_name, 0.0)
            expected_cost_dec = Decimal(str(expected_cost))
            actual_cost_dec = Decimal(str(actual_cost))
            diff = abs(actual_cost_dec - expected_cost_dec)

            if diff > Decimal(str(cost_tolerance)):
                errors.append(f"Namespace '{ns_name}' cost mismatch: expected ${expected_cost}, got ${actual_cost}")
                validation_passed = False
            else:
                print(f"✅ Namespace '{ns_name}': ${actual_cost} (expected ${expected_cost})")

    # Validation 5: Sanity checks
    if actual['total_cost'] == 0.0 and expected.get('total_cost', 0) > 0:
        errors.append("Total cost is $0 but expected non-zero")
        validation_passed = False

    if actual['total_rows'] == 0:
        errors.append("No rows generated")
        validation_passed = False

    # Print errors
    if errors:
        print("\n❌ Validation Errors:")
        for error in errors:
            print(f"  • {error}")

    return validation_passed


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_ocp_aws_totals.py <manifest_path>")
        sys.exit(1)

    manifest_path = sys.argv[1]

    # Database configuration (supports POSTGRES_SCHEMA env var for parallel mode)
    db_config = {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '15432'),
        'database': os.getenv('POSTGRES_DB', 'koku'),
        'user': os.getenv('POSTGRES_USER', 'koku'),
        'password': os.getenv('POSTGRES_PASSWORD', 'koku123'),
        'schema': os.getenv('POSTGRES_SCHEMA', 'org1234567')
    }

    print("=" * 60)
    print("Core-Style Validation: Totals and Costs")
    print("=" * 60)
    print(f"Manifest: {manifest_path}")
    print()

    # Load manifest
    manifest = load_manifest(manifest_path)

    # Detect which cost column to use
    cost_column = detect_cost_column(manifest, manifest_path)
    if cost_column != 'unblended_cost':
        print(f"✓ Detected SavingsPlan scenario - using '{cost_column}' for validation")
        print()

    # Extract date range from manifest for filtering
    start_date = manifest.get('start_date')
    end_date = manifest.get('end_date')
    if start_date and end_date:
        print(f"✓ Filtering results for date range: {start_date} to {end_date}")
        print()

    # Query results
    print("Querying PostgreSQL...")
    results = query_results(db_config, cost_column=cost_column, start_date=start_date, end_date=end_date)

    print("\nActual Results:")
    print(f"  Total rows: {results['totals']['total_rows']}")
    print(f"  Total cost: ${results['totals']['total_cost']}")
    print(f"  Clusters: {results['totals']['clusters']}")
    print(f"  Namespaces: {results['totals']['namespaces']}")
    print()

    # Validate
    print("Validating against expected outcomes...")
    print()

    if validate_totals(manifest, results):
        print()
        print("=" * 60)
        print("✅ VALIDATION PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print()
        print("=" * 60)
        print("❌ VALIDATION FAILED")
        print("=" * 60)
        sys.exit(1)


if __name__ == '__main__':
    main()

