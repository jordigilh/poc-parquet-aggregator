#!/usr/bin/env python3
"""
Validate OCP-AWS aggregation results against expected values from test manifests.

Similar to Core validation approach but implemented independently for this POC.
Compares actual PostgreSQL results with expected outcomes defined in YAML manifests.
"""

import sys
import yaml
import psycopg2
import psycopg2.extras
from pathlib import Path
from typing import Dict, Any, List
from decimal import Decimal


class OCPAWSResultValidator:
    """Validates OCP-AWS aggregation results against expected values."""

    def __init__(self, manifest_path: str, db_config: Dict[str, str]):
        """
        Initialize validator.

        Args:
            manifest_path: Path to test scenario YAML manifest
            db_config: Database connection configuration
        """
        self.manifest_path = Path(manifest_path)
        self.db_config = db_config
        self.manifest_data = None
        self.validation_errors = []

    def load_manifest(self) -> Dict[str, Any]:
        """Load and parse test manifest."""
        with open(self.manifest_path, 'r') as f:
            self.manifest_data = yaml.safe_load(f)
        return self.manifest_data

    def get_expected_outcomes(self) -> Dict[str, Any]:
        """Extract expected outcomes from manifest."""
        if not self.manifest_data:
            self.load_manifest()

        return self.manifest_data.get('expected_outcome', {})

    def connect_db(self):
        """Create database connection."""
        return psycopg2.connect(
            host=self.db_config['host'],
            port=self.db_config['port'],
            database=self.db_config['database'],
            user=self.db_config['user'],
            password=self.db_config['password']
        )

    def query_aggregated_results(self, conn) -> List[Dict]:
        """Query actual aggregated results from PostgreSQL."""
        schema = self.db_config.get('schema', 'org1234567')

        query = f"""
        SELECT
            usage_start,
            cluster_id,
            namespace,
            node,
            resource_id,
            data_transfer_direction,
            ROUND(unblended_cost::numeric, 2) as unblended_cost,
            ROUND(blended_cost::numeric, 2) as blended_cost,
            ROUND(savingsplan_effective_cost::numeric, 2) as savingsplan_cost,
            ROUND(calculated_amortized_cost::numeric, 2) as amortized_cost,
            ROUND(pod_usage_cpu_core_hours::numeric, 4) as cpu_hours,
            ROUND(pod_usage_memory_gigabyte_hours::numeric, 4) as memory_gb_hours,
            ROUND(persistentvolumeclaim_capacity_gigabyte::numeric, 2) as pvc_capacity_gb,
            ROUND(persistentvolumeclaim_capacity_gigabyte_months::numeric, 2) as pvc_capacity_gb_months,
            ROUND(volume_request_storage_gigabyte_months::numeric, 2) as volume_request_gb_months,
            ROUND(persistentvolumeclaim_usage_gigabyte_months::numeric, 2) as pvc_usage_gb_months
        FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
        ORDER BY usage_start, namespace, node
        """

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(query)
            return cursor.fetchall()

    def validate_row_count(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate total row count."""
        expected_output = expected.get('output', {})

        # If specific row count expected
        if 'total_rows' in expected_output:
            expected_count = expected_output['total_rows']
            actual_count = len(actual_rows)

            if actual_count != expected_count:
                self.validation_errors.append(
                    f"Row count mismatch: expected {expected_count}, got {actual_count}"
                )
                return False

        # Check minimum rows
        if len(actual_rows) == 0:
            self.validation_errors.append("No rows returned from aggregation")
            return False

        return True

    def validate_namespaces(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate namespace-level costs."""
        expected_output = expected.get('output', {})

        # Group actual results by namespace
        namespace_costs = {}
        for row in actual_rows:
            ns = row['namespace']
            if ns not in namespace_costs:
                namespace_costs[ns] = {
                    'unblended_cost': Decimal('0'),
                    'row_count': 0,
                    'resource_matched': 0,
                    'tag_matched': 0
                }

            namespace_costs[ns]['unblended_cost'] += Decimal(str(row.get('unblended_cost') or 0))
            namespace_costs[ns]['row_count'] += 1

            if row.get('resource_id_matched'):
                namespace_costs[ns]['resource_matched'] += 1
            if row.get('tag_matched'):
                namespace_costs[ns]['tag_matched'] += 1

        # Validate each expected namespace
        all_valid = True
        for ns_name, ns_expected in expected_output.items():
            if ns_name in ['total_rows', 'processing', 'validation', 'data_quality']:
                continue  # Skip non-namespace keys

            if ns_name not in namespace_costs:
                self.validation_errors.append(
                    f"Expected namespace '{ns_name}' not found in results"
                )
                all_valid = False
                continue

            actual_ns = namespace_costs[ns_name]

            # Validate cost (with tolerance for floating point)
            if 'cost' in ns_expected:
                expected_cost = Decimal(str(ns_expected['cost']))
                actual_cost = actual_ns['unblended_cost']
                tolerance = Decimal('0.10')  # 10 cent tolerance

                if abs(actual_cost - expected_cost) > tolerance:
                    self.validation_errors.append(
                        f"Namespace '{ns_name}': cost mismatch - "
                        f"expected {expected_cost}, got {actual_cost}"
                    )
                    all_valid = False

            # Validate matching flags
            if 'resource_matched' in ns_expected:
                if ns_expected['resource_matched'] and actual_ns['resource_matched'] == 0:
                    self.validation_errors.append(
                        f"Namespace '{ns_name}': expected resource_id matching but found none"
                    )
                    all_valid = False

            if 'tag_matched' in ns_expected:
                if ns_expected['tag_matched'] and actual_ns['tag_matched'] == 0:
                    self.validation_errors.append(
                        f"Namespace '{ns_name}': expected tag matching but found none"
                    )
                    all_valid = False

        return all_valid

    def validate_matching_behavior(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate resource ID and tag matching behavior."""
        validation_rules = expected.get('validation', {})

        # Count matching types
        resource_matched_count = sum(1 for r in actual_rows if r.get('resource_id_matched'))
        tag_matched_count = sum(1 for r in actual_rows if r.get('tag_matched'))
        unmatched_count = sum(1 for r in actual_rows
                             if not r.get('resource_id_matched') and not r.get('tag_matched'))

        all_valid = True

        # Validate resource matching expectation
        if 'resource_matching' in validation_rules:
            expected_resource_match = validation_rules['resource_matching']
            if expected_resource_match == 'required' and resource_matched_count == 0:
                self.validation_errors.append(
                    "Expected resource_id matching but found none"
                )
                all_valid = False
            elif expected_resource_match == 'none' and resource_matched_count > 0:
                self.validation_errors.append(
                    f"Expected no resource_id matching but found {resource_matched_count}"
                )
                all_valid = False

        # Validate tag matching expectation
        if 'tag_matching' in validation_rules:
            expected_tag_match = validation_rules['tag_matching']
            if expected_tag_match == 'required' and tag_matched_count == 0:
                self.validation_errors.append(
                    "Expected tag matching but found none"
                )
                all_valid = False
            elif expected_tag_match == 'none' and tag_matched_count > 0:
                self.validation_errors.append(
                    f"Expected no tag matching but found {tag_matched_count}"
                )
                all_valid = False

        # Validate unmatched handling
        if 'unmatched_tracked' in validation_rules:
            if validation_rules['unmatched_tracked'] and unmatched_count == 0:
                # This might be OK if everything matched
                pass
            elif not validation_rules['unmatched_tracked'] and unmatched_count > 0:
                self.validation_errors.append(
                    f"Found {unmatched_count} unmatched rows but expected none"
                )
                all_valid = False

        return all_valid

    def validate_network_costs(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate network cost handling."""
        # Check for network-specific namespace
        network_rows = [r for r in actual_rows if r.get('data_transfer_direction')]

        validation_rules = expected.get('validation', {})

        if 'network_costs_separated' in validation_rules:
            if validation_rules['network_costs_separated']:
                if len(network_rows) == 0:
                    self.validation_errors.append(
                        "Expected network costs to be separated but found none"
                    )
                    return False

                # Validate network namespace exists
                network_namespaces = set(r['namespace'] for r in network_rows)
                if 'Network unattributed' not in network_namespaces:
                    self.validation_errors.append(
                        "Expected 'Network unattributed' namespace for network costs"
                    )
                    return False

        return True

    def validate_storage_attribution(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate storage/EBS attribution."""
        storage_rows = [r for r in actual_rows
                       if r.get('pvc_capacity_gb') or r.get('volume_request_gb_months')]

        validation_rules = expected.get('validation', {})

        if 'storage_attributed' in validation_rules:
            if validation_rules['storage_attributed']:
                if len(storage_rows) == 0:
                    self.validation_errors.append(
                        "Expected storage attribution but found no storage data"
                    )
                    return False

        return True

    def validate_cost_types(self, actual_rows: List[Dict], expected: Dict) -> bool:
        """Validate all cost types are preserved."""
        validation_rules = expected.get('validation', {})

        if 'all_cost_types_present' in validation_rules:
            if validation_rules['all_cost_types_present']:
                # Check if we have variety in cost types
                has_unblended = any(r.get('unblended_cost') for r in actual_rows)
                has_blended = any(r.get('blended_cost') for r in actual_rows)

                if not has_unblended and not has_blended:
                    self.validation_errors.append(
                        "Expected cost data but found no costs"
                    )
                    return False

        return True

    def validate(self) -> bool:
        """
        Run complete validation.

        Returns:
            True if all validations pass, False otherwise
        """
        print(f"🔍 Validating results for: {self.manifest_path.name}")
        print("=" * 80)

        # Load expected outcomes
        expected = self.get_expected_outcomes()
        if not expected:
            print("⚠️  No expected_outcome defined in manifest - skipping validation")
            return True

        # Query actual results
        try:
            conn = self.connect_db()
            actual_rows = self.query_aggregated_results(conn)
            conn.close()
        except Exception as e:
            print(f"❌ Database query failed: {e}")
            return False

        print(f"📊 Found {len(actual_rows)} aggregated rows")

        # Run validations
        validations = [
            ("Row count", self.validate_row_count(actual_rows, expected)),
            ("Namespaces", self.validate_namespaces(actual_rows, expected)),
            ("Matching behavior", self.validate_matching_behavior(actual_rows, expected)),
            ("Network costs", self.validate_network_costs(actual_rows, expected)),
            ("Storage attribution", self.validate_storage_attribution(actual_rows, expected)),
            ("Cost types", self.validate_cost_types(actual_rows, expected)),
        ]

        # Print results
        print("\nValidation Results:")
        print("-" * 80)
        all_passed = True
        for name, passed in validations:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status} - {name}")
            if not passed:
                all_passed = False

        # Print errors
        if self.validation_errors:
            print("\n❌ Validation Errors:")
            print("-" * 80)
            for error in self.validation_errors:
                print(f"  • {error}")

        print("=" * 80)
        if all_passed:
            print("✅ All validations passed!")
        else:
            print(f"❌ {len(self.validation_errors)} validation(s) failed")

        return all_passed


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_ocp_aws_results.py <manifest_path>")
        print("\nExample:")
        print("  python validate_ocp_aws_results.py test-manifests/ocp-on-aws/01-resource-matching/manifest.yml")
        sys.exit(1)

    manifest_path = sys.argv[1]

    # Database configuration from environment
    import os
    db_config = {
        'host': os.getenv('POSTGRES_HOST', '127.0.0.1'),
        'port': os.getenv('POSTGRES_PORT', '15432'),
        'database': os.getenv('POSTGRES_DB', 'koku'),
        'user': os.getenv('POSTGRES_USER', 'koku'),
        'password': os.getenv('POSTGRES_PASSWORD', 'koku123'),
        'schema': os.getenv('ORG_ID', 'org1234567')
    }

    # Run validation
    validator = OCPAWSResultValidator(manifest_path, db_config)
    success = validator.validate()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

