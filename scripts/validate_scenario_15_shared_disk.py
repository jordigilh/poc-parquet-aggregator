#!/usr/bin/env python3
"""
Scenario 15 Validator: Multi-Cluster Shared CSI Disk

Validates that:
1. EBS cost is NOT duplicated across clusters
2. PVC capacities are aggregated across ALL clusters
3. Attribution ratio considers total PVC capacity
4. Unattributed storage is split across clusters

Expected outcome from manifest:
- Total EBS cost: $10.00
- Cluster Alpha (40 GB): (40/100) * $10 = $4.00
- Cluster Beta (30 GB):  (30/100) * $10 = $3.00
- Unattributed (30 GB):  (30/100) * $10 = $3.00 → split $1.50 per cluster
"""

import psycopg2
import sys
from decimal import Decimal

def validate_scenario_15():
    """Validate shared CSI disk attribution."""

    # Connect to PostgreSQL
    conn = psycopg2.connect(
        host='127.0.0.1',
        port=15432,
        database='koku',
        user='koku',
        password='koku123'
    )

    schema = 'org1234567'

    print("=" * 80)
    print("SCENARIO 15: Multi-Cluster Shared CSI Disk Validation")
    print("=" * 80)

    with conn.cursor() as cursor:
        # Query all storage costs
        cursor.execute(f"""
            SELECT
                cluster_id,
                namespace,
                ROUND(SUM(unblended_cost)::numeric, 2) as cost
            FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
            WHERE data_source = 'Storage'
            GROUP BY cluster_id, namespace
            ORDER BY cluster_id, namespace;
        """)

        results = cursor.fetchall()

        if not results:
            print("❌ NO STORAGE COSTS FOUND")
            return False

        print("\nStorage Cost Breakdown:")
        print("-" * 80)

        cluster_alpha_attributed = Decimal('0')
        cluster_alpha_unattributed = Decimal('0')
        cluster_beta_attributed = Decimal('0')
        cluster_beta_unattributed = Decimal('0')

        for cluster_id, namespace, cost in results:
            cost = Decimal(str(cost))
            print(f"  {cluster_id} / {namespace}: ${cost}")

            if cluster_id == 'cluster-alpha':
                if namespace == 'project-alpha':
                    cluster_alpha_attributed = cost
                elif namespace == 'Storage unattributed':
                    cluster_alpha_unattributed = cost
            elif cluster_id == 'cluster-beta':
                if namespace == 'project-beta':
                    cluster_beta_attributed = cost
                elif namespace == 'Storage unattributed':
                    cluster_beta_unattributed = cost

        # Query total EBS cost from AWS data
        cursor.execute(f"""
            SELECT ROUND(SUM(unblended_cost)::numeric, 2) as total_cost
            FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p;
        """)
        total_cost = Decimal(str(cursor.fetchone()[0]))

        print("\n" + "=" * 80)
        print("VALIDATION RESULTS")
        print("=" * 80)

        # Expected values
        expected_total = Decimal('11.50')  # $10 EBS + $1.50 compute
        expected_alpha_attributed = Decimal('4.00')
        expected_beta_attributed = Decimal('3.00')
        expected_unattributed_per_cluster = Decimal('1.50')

        tolerance = Decimal('0.05')

        all_passed = True

        # Test 1: Total cost (no duplication)
        if abs(total_cost - expected_total) <= tolerance:
            print(f"✅ Total cost: ${total_cost} (expected: ${expected_total})")
        else:
            print(f"❌ Total cost: ${total_cost} (expected: ${expected_total})")
            all_passed = False

        # Test 2: Cluster Alpha attribution
        if abs(cluster_alpha_attributed - expected_alpha_attributed) <= tolerance:
            print(f"✅ Cluster Alpha attributed: ${cluster_alpha_attributed} (expected: ${expected_alpha_attributed})")
        else:
            print(f"❌ Cluster Alpha attributed: ${cluster_alpha_attributed} (expected: ${expected_alpha_attributed})")
            print(f"   → This suggests PVC capacities were NOT aggregated across clusters!")
            all_passed = False

        # Test 3: Cluster Beta attribution
        if abs(cluster_beta_attributed - expected_beta_attributed) <= tolerance:
            print(f"✅ Cluster Beta attributed: ${cluster_beta_attributed} (expected: ${expected_beta_attributed})")
        else:
            print(f"❌ Cluster Beta attributed: ${cluster_beta_attributed} (expected: ${expected_beta_attributed})")
            all_passed = False

        # Test 4: Unattributed storage per cluster
        if abs(cluster_alpha_unattributed - expected_unattributed_per_cluster) <= tolerance:
            print(f"✅ Cluster Alpha unattributed: ${cluster_alpha_unattributed} (expected: ${expected_unattributed_per_cluster})")
        else:
            print(f"❌ Cluster Alpha unattributed: ${cluster_alpha_unattributed} (expected: ${expected_unattributed_per_cluster})")
            all_passed = False

        if abs(cluster_beta_unattributed - expected_unattributed_per_cluster) <= tolerance:
            print(f"✅ Cluster Beta unattributed: ${cluster_beta_unattributed} (expected: ${expected_unattributed_per_cluster})")
        else:
            print(f"❌ Cluster Beta unattributed: ${cluster_beta_unattributed} (expected: ${expected_unattributed_per_cluster})")
            all_passed = False

        # Test 5: No cost duplication (critical!)
        total_storage = cluster_alpha_attributed + cluster_alpha_unattributed + cluster_beta_attributed + cluster_beta_unattributed
        expected_total_storage = Decimal('10.00')

        if abs(total_storage - expected_total_storage) <= tolerance:
            print(f"✅ Total storage cost: ${total_storage} (expected: ${expected_total_storage}) - NO DUPLICATION")
        else:
            print(f"❌ Total storage cost: ${total_storage} (expected: ${expected_total_storage}) - DUPLICATION DETECTED!")
            all_passed = False

        print("=" * 80)

        if all_passed:
            print("✅ SCENARIO 15 PASSED")
            return True
        else:
            print("❌ SCENARIO 15 FAILED")
            print("\nDiagnosis:")
            print("If attributed costs are incorrect but total is correct:")
            print("→ POC is calculating attribution ratios per-cluster instead of cross-cluster")
            print("→ Need to aggregate PVC capacities across ALL clusters before attribution")
            return False

    conn.close()

if __name__ == '__main__':
    try:
        success = validate_scenario_15()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Validation error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

