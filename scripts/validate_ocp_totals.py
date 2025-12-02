#!/usr/bin/env python3
"""
OCP-Only Validation: Validate CPU/Memory/Storage Totals

This validation script compares expected vs actual aggregated values
for OCP-only scenarios, similar to validate_ocp_aws_totals.py for OCP-on-AWS.

Expected values in manifest:
  expected_outcome:
    cpu_core_hours: 172.80
    memory_gigabyte_hours: 460.80
    storage_gigabyte_months: 0.0  # optional
    min_rows: 1
"""

import os
import sys
import yaml
import psycopg2
from decimal import Decimal
from typing import Dict, Any, Optional


def load_manifest(manifest_path: str) -> Dict[str, Any]:
    """Load test manifest."""
    with open(manifest_path, 'r') as f:
        return yaml.safe_load(f)


def get_db_connection():
    """Get database connection, supporting both local (podman) and CI environments."""
    import subprocess
    
    # Try direct psycopg2 connection first
    try:
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '15432'),
            database=os.getenv('POSTGRES_DB', 'koku'),
            user=os.getenv('POSTGRES_USER', 'koku'),
            password=os.getenv('POSTGRES_PASSWORD', 'koku123')
        )
        return conn, 'direct'
    except Exception:
        pass
    
    # Fall back to podman exec
    return None, 'podman'


def run_query_podman(query: str) -> str:
    """Run query via podman exec."""
    import subprocess
    result = subprocess.run(
        ['podman', 'exec', 'postgres-poc', 'psql', '-U', 'koku', '-d', 'koku', '-t', '-c', query],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def query_results(cluster_id: str) -> Dict[str, Any]:
    """Query aggregated results from PostgreSQL."""
    schema = os.getenv('ORG_ID', 'org1234567')
    
    conn, method = get_db_connection()
    
    if method == 'direct':
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_rows,
                    COALESCE(ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2), 0) as cpu_hours,
                    COALESCE(ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2), 0) as memory_hours,
                    COALESCE(ROUND(SUM(persistentvolumeclaim_usage_gigabyte_months)::numeric, 4), 0) as storage_months,
                    COUNT(DISTINCT namespace) as namespaces
                FROM {schema}.reporting_ocpusagelineitem_daily_summary
                WHERE cluster_id = %s;
            """, (cluster_id,))
            row = cursor.fetchone()
        conn.close()
    else:
        # Use podman exec
        query = f"""
            SELECT
                COUNT(*) as total_rows,
                COALESCE(ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2), 0) as cpu_hours,
                COALESCE(ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2), 0) as memory_hours,
                COALESCE(ROUND(SUM(persistentvolumeclaim_usage_gigabyte_months)::numeric, 4), 0) as storage_months,
                COUNT(DISTINCT namespace) as namespaces
            FROM {schema}.reporting_ocpusagelineitem_daily_summary
            WHERE cluster_id = '{cluster_id}';
        """
        result = run_query_podman(query)
        # Parse result: "  1 | 172.80 | 460.80 | 0.0000 | 1"
        parts = [p.strip() for p in result.split('|')]
        row = (
            int(parts[0]) if parts[0] else 0,
            float(parts[1]) if parts[1] else 0.0,
            float(parts[2]) if parts[2] else 0.0,
            float(parts[3]) if parts[3] else 0.0,
            int(parts[4]) if parts[4] else 0
        )
    
    return {
        'total_rows': row[0],
        'cpu_core_hours': float(row[1]) if row[1] else 0.0,
        'memory_gigabyte_hours': float(row[2]) if row[2] else 0.0,
        'storage_gigabyte_months': float(row[3]) if row[3] else 0.0,
        'namespaces': row[4]
    }


def validate_totals(manifest: Dict, results: Dict) -> bool:
    """
    Validate totals match expected values.
    
    Returns True if validation passes, False otherwise.
    """
    expected = manifest.get('expected_outcome', {})
    
    if not expected:
        print("⚠️  No expected_outcome defined in manifest - skipping value validation")
        # Still check basic sanity
        if results['total_rows'] == 0:
            print("❌ FAIL: No rows generated")
            return False
        print(f"✅ PASS: {results['total_rows']} rows generated (no expected values to compare)")
        return True
    
    validation_passed = True
    errors = []
    
    # Tolerance for floating point comparisons (1% or 0.1, whichever is larger)
    def within_tolerance(actual, expected_val, name):
        if expected_val == 0:
            tolerance = 0.1
        else:
            tolerance = max(abs(expected_val) * 0.01, 0.1)
        
        diff = abs(actual - expected_val)
        if diff > tolerance:
            return False, diff
        return True, diff
    
    # Validation 1: CPU core hours
    if 'cpu_core_hours' in expected:
        expected_cpu = float(expected['cpu_core_hours'])
        actual_cpu = results['cpu_core_hours']
        ok, diff = within_tolerance(actual_cpu, expected_cpu, 'CPU')
        
        if not ok:
            errors.append(f"CPU hours mismatch: expected {expected_cpu}, got {actual_cpu} (diff: {diff:.2f})")
            validation_passed = False
        else:
            print(f"✅ CPU Hours: {actual_cpu} (expected {expected_cpu})")
    
    # Validation 2: Memory GB-hours
    if 'memory_gigabyte_hours' in expected:
        expected_mem = float(expected['memory_gigabyte_hours'])
        actual_mem = results['memory_gigabyte_hours']
        ok, diff = within_tolerance(actual_mem, expected_mem, 'Memory')
        
        if not ok:
            errors.append(f"Memory hours mismatch: expected {expected_mem}, got {actual_mem} (diff: {diff:.2f})")
            validation_passed = False
        else:
            print(f"✅ Memory GB-Hours: {actual_mem} (expected {expected_mem})")
    
    # Validation 3: Storage GB-months (optional)
    if 'storage_gigabyte_months' in expected:
        expected_storage = float(expected['storage_gigabyte_months'])
        actual_storage = results['storage_gigabyte_months']
        ok, diff = within_tolerance(actual_storage, expected_storage, 'Storage')
        
        if not ok:
            errors.append(f"Storage months mismatch: expected {expected_storage}, got {actual_storage} (diff: {diff:.4f})")
            validation_passed = False
        else:
            print(f"✅ Storage GB-Months: {actual_storage} (expected {expected_storage})")
    
    # Validation 4: Row count (minimum)
    if 'min_rows' in expected:
        min_rows = expected['min_rows']
        if results['total_rows'] < min_rows:
            errors.append(f"Row count too low: expected >={min_rows}, got {results['total_rows']}")
            validation_passed = False
        else:
            print(f"✅ Row count: {results['total_rows']} (expected >={min_rows})")
    
    # Validation 5: Namespace count (optional)
    if 'namespaces' in expected:
        expected_ns = expected['namespaces']
        if results['namespaces'] != expected_ns:
            errors.append(f"Namespace count mismatch: expected {expected_ns}, got {results['namespaces']}")
            validation_passed = False
        else:
            print(f"✅ Namespaces: {results['namespaces']} (expected {expected_ns})")
    
    # Sanity checks
    if results['total_rows'] == 0:
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
        print("Usage: validate_ocp_totals.py <manifest_path> [cluster_id]")
        sys.exit(1)
    
    manifest_path = sys.argv[1]
    cluster_id = sys.argv[2] if len(sys.argv) > 2 else os.getenv('OCP_CLUSTER_ID', 'test-cluster-001')
    
    print("=" * 60)
    print("OCP-Only Validation: CPU/Memory/Storage Totals")
    print("=" * 60)
    print(f"Manifest: {manifest_path}")
    print(f"Cluster ID: {cluster_id}")
    print()
    
    # Load manifest
    manifest = load_manifest(manifest_path)
    
    # Query results
    print("Querying PostgreSQL...")
    results = query_results(cluster_id)
    
    print("\nActual Results:")
    print(f"  Total rows: {results['total_rows']}")
    print(f"  CPU core hours: {results['cpu_core_hours']}")
    print(f"  Memory GB-hours: {results['memory_gigabyte_hours']}")
    print(f"  Storage GB-months: {results['storage_gigabyte_months']}")
    print(f"  Namespaces: {results['namespaces']}")
    print()
    
    # Show expected if defined
    expected = manifest.get('expected_outcome', {})
    if expected:
        print("Expected Values:")
        if 'cpu_core_hours' in expected:
            print(f"  CPU core hours: {expected['cpu_core_hours']}")
        if 'memory_gigabyte_hours' in expected:
            print(f"  Memory GB-hours: {expected['memory_gigabyte_hours']}")
        if 'storage_gigabyte_months' in expected:
            print(f"  Storage GB-months: {expected['storage_gigabyte_months']}")
        if 'min_rows' in expected:
            print(f"  Min rows: {expected['min_rows']}")
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






