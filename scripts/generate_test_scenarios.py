#!/usr/bin/env python3
"""
Generate OCP-on-AWS test scenarios for validation.

This is a self-contained test data generator that does NOT depend on Core code.
All test scenarios are publicly safe and can be committed to github.com.

Inspired by real-world patterns but contains no proprietary information.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


class OCPAWSTestScenarios:
    """Generate test scenarios for OCP-on-AWS validation."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all_scenarios(self):
        """Generate all test scenarios."""
        scenarios = [
            self.scenario_1_basic_resource_matching(),
            self.scenario_2_tag_matching(),
            self.scenario_3_namespace_attribution(),
            self.scenario_4_multi_cluster(),
            self.scenario_5_network_costs(),
            self.scenario_6_storage_volumes(),
        ]

        print(f"✅ Generated {len(scenarios)} test scenarios in {self.output_dir}")
        return scenarios

    def scenario_1_basic_resource_matching(self):
        """Scenario 1: Basic EC2 resource ID matching."""
        print("→ Generating Scenario 1: Basic Resource Matching...")

        scenario = {
            "name": "basic_resource_matching",
            "description": "EC2 instances matched to OCP nodes by resource_id",
            "ocp": {
                "cluster_id": "test-cluster-001",
                "cluster_alias": "Test Cluster 001",
                "start_date": "2025-10-01",
                "end_date": "2025-10-03",
                "nodes": [
                    {
                        "node_name": "ip-10-0-1-100.ec2.internal",
                        "resource_id": "i-0abc123def456789a",
                        "cpu_cores": 4,
                        "memory_gb": 16,
                        "namespaces": [
                            {
                                "name": "backend",
                                "pods": [
                                    {
                                        "name": "api-server-1",
                                        "cpu_request": 2.0,
                                        "memory_request_gb": 4.0,
                                        "cpu_usage": 1.5,
                                        "memory_usage_gb": 6.0
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EC2",
                        "resource_id": "i-0abc123def456789a",
                        "instance_type": "m5.xlarge",
                        "region": "us-east-1",
                        "cost_per_hour": 0.192,
                        "hours": 72,
                        "tags": {}
                    }
                ]
            },
            "expected_outcome": {
                "resource_id_matched": True,
                "tag_matched": False,
                "attributed_cost": 13.824  # 0.192 * 72
            }
        }

        self._save_scenario(scenario)
        return scenario

    def scenario_2_tag_matching(self):
        """Scenario 2: Tag-based matching."""
        print("→ Generating Scenario 2: Tag Matching...")

        scenario = {
            "name": "tag_matching",
            "description": "AWS resources matched to OCP by OpenShift tags",
            "ocp": {
                "cluster_id": "test-cluster-002",
                "cluster_alias": "Test Cluster 002",
                "start_date": "2025-10-01",
                "end_date": "2025-10-03",
                "nodes": [
                    {
                        "node_name": "ip-10-0-2-100.ec2.internal",
                        "resource_id": None,  # No resource_id, should match by tag
                        "cpu_cores": 8,
                        "memory_gb": 32,
                        "namespaces": [
                            {
                                "name": "frontend",
                                "pods": [
                                    {
                                        "name": "web-1",
                                        "cpu_request": 4.0,
                                        "memory_request_gb": 8.0,
                                        "cpu_usage": 3.0,
                                        "memory_usage_gb": 12.0
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EC2",
                        "resource_id": "i-0def456abc789012b",
                        "instance_type": "m5.2xlarge",
                        "region": "us-east-1",
                        "cost_per_hour": 0.384,
                        "hours": 72,
                        "tags": {
                            "openshift_cluster": "test-cluster-002",
                            "openshift_node": "ip-10-0-2-100.ec2.internal"
                        }
                    }
                ]
            },
            "expected_outcome": {
                "resource_id_matched": False,
                "tag_matched": True,
                "matched_tag": "openshift_node=ip-10-0-2-100.ec2.internal",
                "attributed_cost": 27.648  # 0.384 * 72
            }
        }

        self._save_scenario(scenario)
        return scenario

    def scenario_3_namespace_attribution(self):
        """Scenario 3: Multiple namespaces, cost attribution."""
        print("→ Generating Scenario 3: Namespace Attribution...")

        scenario = {
            "name": "namespace_attribution",
            "description": "Multiple namespaces with different resource usage",
            "ocp": {
                "cluster_id": "test-cluster-003",
                "cluster_alias": "Test Cluster 003",
                "start_date": "2025-10-01",
                "end_date": "2025-10-03",
                "nodes": [
                    {
                        "node_name": "ip-10-0-3-100.ec2.internal",
                        "resource_id": "i-0ghi789jkl012345c",
                        "cpu_cores": 16,
                        "memory_gb": 64,
                        "namespaces": [
                            {
                                "name": "database",
                                "pods": [
                                    {
                                        "name": "postgres-0",
                                        "cpu_request": 8.0,
                                        "memory_request_gb": 32.0,
                                        "cpu_usage": 12.0,
                                        "memory_usage_gb": 48.0
                                    }
                                ]
                            },
                            {
                                "name": "cache",
                                "pods": [
                                    {
                                        "name": "redis-0",
                                        "cpu_request": 2.0,
                                        "memory_request_gb": 8.0,
                                        "cpu_usage": 3.0,
                                        "memory_usage_gb": 12.0
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EC2",
                        "resource_id": "i-0ghi789jkl012345c",
                        "instance_type": "m5.4xlarge",
                        "region": "us-east-1",
                        "cost_per_hour": 0.768,
                        "hours": 72,
                        "tags": {}
                    }
                ]
            },
            "expected_outcome": {
                "resource_id_matched": True,
                "namespaces": {
                    "database": {
                        "cpu_percentage": 0.75,  # 12 / 16
                        "memory_percentage": 0.75,  # 48 / 64
                        "attributed_cost": 41.472  # 0.768 * 72 * 0.75 (avg)
                    },
                    "cache": {
                        "cpu_percentage": 0.1875,  # 3 / 16
                        "memory_percentage": 0.1875,  # 12 / 64
                        "attributed_cost": 10.368  # 0.768 * 72 * 0.1875 (avg)
                    }
                }
            }
        }

        self._save_scenario(scenario)
        return scenario

    def scenario_4_multi_cluster(self):
        """Scenario 4: Multiple clusters in same AWS account."""
        print("→ Generating Scenario 4: Multi-Cluster...")

        scenario = {
            "name": "multi_cluster",
            "description": "Multiple OCP clusters in same AWS account",
            "ocp": {
                "clusters": [
                    {
                        "cluster_id": "prod-cluster",
                        "cluster_alias": "Production",
                        "nodes": [
                            {
                                "node_name": "ip-10-0-4-100.ec2.internal",
                                "resource_id": "i-0prod001",
                                "cpu_cores": 8,
                                "memory_gb": 32
                            }
                        ]
                    },
                    {
                        "cluster_id": "staging-cluster",
                        "cluster_alias": "Staging",
                        "nodes": [
                            {
                                "node_name": "ip-10-0-4-200.ec2.internal",
                                "resource_id": "i-0staging001",
                                "cpu_cores": 4,
                                "memory_gb": 16
                            }
                        ]
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EC2",
                        "resource_id": "i-0prod001",
                        "tags": {
                            "openshift_cluster": "prod-cluster"
                        }
                    },
                    {
                        "type": "EC2",
                        "resource_id": "i-0staging001",
                        "tags": {
                            "openshift_cluster": "staging-cluster"
                        }
                    }
                ]
            },
            "expected_outcome": {
                "clusters_isolated": True,
                "no_cross_contamination": True
            }
        }

        self._save_scenario(scenario)
        return scenario

    def scenario_5_network_costs(self):
        """Scenario 5: Network/Data Transfer costs."""
        print("→ Generating Scenario 5: Network Costs...")

        scenario = {
            "name": "network_costs",
            "description": "Handle network costs separately from compute",
            "ocp": {
                "cluster_id": "test-cluster-005",
                "nodes": [
                    {
                        "node_name": "ip-10-0-5-100.ec2.internal",
                        "resource_id": "i-0network001",
                        "cpu_cores": 4,
                        "memory_gb": 16
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EC2",
                        "resource_id": "i-0network001",
                        "operation": "RunInstances",
                        "cost": 13.824
                    },
                    {
                        "type": "EC2",
                        "resource_id": "i-0network001",
                        "operation": "InterZone-Out",
                        "cost": 2.5,
                        "data_transfer_direction": "OUT"
                    },
                    {
                        "type": "EC2",
                        "resource_id": "i-0network001",
                        "operation": "InterZone-In",
                        "cost": 1.5,
                        "data_transfer_direction": "IN"
                    }
                ]
            },
            "expected_outcome": {
                "compute_cost": 13.824,
                "network_cost": 4.0,  # 2.5 + 1.5
                "network_namespace": "Network unattributed"
            }
        }

        self._save_scenario(scenario)
        return scenario

    def scenario_6_storage_volumes(self):
        """Scenario 6: EBS volumes and PVs."""
        print("→ Generating Scenario 6: Storage/Volumes...")

        scenario = {
            "name": "storage_volumes",
            "description": "EBS volumes matched to OCP PVs",
            "ocp": {
                "cluster_id": "test-cluster-006",
                "volumes": [
                    {
                        "volume_name": "pvc-database-data",
                        "csi_volume_handle": "vol-0abc123def",
                        "capacity_gb": 100,
                        "storage_class": "gp3",
                        "namespace": "database"
                    }
                ]
            },
            "aws": {
                "account": "123456789012",
                "resources": [
                    {
                        "type": "EBS",
                        "resource_id": "vol-0abc123def",
                        "operation": "CreateVolume",
                        "volume_size_gb": 100,
                        "cost_per_gb_month": 0.08,
                        "days": 30
                    }
                ]
            },
            "expected_outcome": {
                "volume_matched": True,
                "disk_capacity_gb_month": 100,
                "storage_cost": 8.0  # 100 GB * $0.08
            }
        }

        self._save_scenario(scenario)
        return scenario

    def _save_scenario(self, scenario):
        """Save scenario to JSON file."""
        filename = self.output_dir / f"{scenario['name']}.json"
        with open(filename, 'w') as f:
            json.dump(scenario, f, indent=2)
        print(f"   Saved: {filename}")


def main():
    """Main entry point."""
    output_dir = "test-scenarios"
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]

    print("=" * 60)
    print("Public-Safe Test Scenario Generator")
    print("(No Core dependencies, safe for github.com)")
    print("=" * 60)
    print()

    generator = OCPAWSTestScenarios(output_dir)
    scenarios = generator.generate_all_scenarios()

    print()
    print("=" * 60)
    print(f"✅ Generated {len(scenarios)} scenarios")
    print(f"Output directory: {output_dir}")
    print()
    print("These scenarios are:")
    print("  ✅ Self-contained (no external dependencies)")
    print("  ✅ Publicly safe (no proprietary information)")
    print("  ✅ Ready for github.com")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())

