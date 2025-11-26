#!/usr/bin/env python3
"""
Generate nise manifests for OCP-on-AWS benchmarks.

Creates manifests for 6 scale points with calculated pod/node counts
to achieve target output row counts within ±1% tolerance.

Output Row Formula:
    output_rows = pods × hours × aws_resources_per_pod

For simplicity, we use 1 AWS resource per node, so:
    output_rows ≈ pods × hours × 1
    pods ≈ output_rows / hours
"""

import os
import yaml
from pathlib import Path

# Benchmark scale configurations
# Output Rows = Nodes × Pods_per_node × 24 hours
# Formula: nodes = target_rows / (pods_per_node × 24)
SCALES = {
    'scale-20k': {
        'target_rows': 20000,
        'nodes': 20,           # 20 × 42 × 24 = 20,160 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-50k': {
        'target_rows': 50000,
        'nodes': 50,           # 50 × 42 × 24 = 50,400 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-100k': {
        'target_rows': 100000,
        'nodes': 100,          # 100 × 42 × 24 = 100,800 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-250k': {
        'target_rows': 250000,
        'nodes': 248,          # 248 × 42 × 24 = 249,984 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-500k': {
        'target_rows': 500000,
        'nodes': 496,          # 496 × 42 × 24 = 499,968 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-1m': {
        'target_rows': 1000000,
        'nodes': 992,          # 992 × 42 × 24 = 999,936 rows
        'pods_per_node': 42,
        'namespaces': 3,
    },
    # Extended scales for production validation (1.5M and 2M output rows)
    # Based on observed ratio: ~336 output rows per node
    'scale-1.5m': {
        'target_rows': 1500000,
        'nodes': 1488,         # 1488 nodes → ~500K output rows (1.5x scale-1m)
        'pods_per_node': 42,
        'namespaces': 3,
    },
    'scale-2m': {
        'target_rows': 2000000,
        'nodes': 1984,         # 1984 nodes → ~667K output rows (2x scale-1m)
        'pods_per_node': 42,
        'namespaces': 3,
    },
}

def generate_manifest(scale_name: str, config: dict) -> dict:
    """Generate a nise manifest for a benchmark scale.

    Uses separate OCPGenerator entries per node because nise only processes
    the last node when multiple nodes are in a single generator.
    """

    nodes = config['nodes']
    pods_per_node = config['pods_per_node']
    namespaces = config['namespaces']
    pods_per_namespace = pods_per_node // namespaces

    total_pods = nodes * pods_per_node
    expected_ocp_rows = total_pods * 24  # 24 hours
    # Output rows = OCP pod-hours (each pod-hour matches one AWS node-hour)
    expected_output_rows = expected_ocp_rows  # 1:1 matching

    manifest = {
        '__comment__': f"""
Benchmark Scale: {scale_name}
Target: {config['target_rows']:,} output rows (±1%)
Configuration:
  - Nodes: {nodes}
  - Pods per node: {pods_per_node}
  - Total pods: {total_pods}
  - Namespaces: {namespaces}
  - Hours: 24
Expected:
  - OCP rows: ~{expected_ocp_rows:,}
  - Output rows (after matching): ~{expected_output_rows:,}
""",
        'start_date': '2025-10-01',
        'end_date': '2025-10-02',
        'ocp': {
            'generators': []  # One generator per node
        },
        'aws': {
            'generators': []
        }
    }

    # Generate nodes - each as a separate OCPGenerator
    for node_idx in range(1, nodes + 1):
        node_name = f'bench-node-{node_idx:03d}'
        resource_id = f'i-bench-node-{node_idx:03d}'

        node = {
            'node': None,  # Required by nise
            'node_name': node_name,
            'resource_id': resource_id,
            'cpu_cores': 16,
            'memory_gig': 64,
            'namespaces': {}
        }

        # Generate namespaces and pods
        for ns_idx in range(1, namespaces + 1):
            ns_name = f'bench-ns-{ns_idx:02d}'

            # Explicitly generate each pod
            pods = []
            for pod_idx in range(1, pods_per_namespace + 1):
                pods.append({
                    'pod': None,  # Required by nise
                    'pod_name': f'app-n{node_idx:03d}-{pod_idx:03d}',  # Unique pod names per node
                    'cpu_request': 1,
                    'mem_request_gig': 2,
                    'cpu_limit': 2,
                    'mem_limit_gig': 4,
                    'pod_seconds': 3600,
                    'cpu_usage': {'full_period': 0.8},
                    'mem_usage_gig': {'full_period': 1.5}
                })

            node['namespaces'][ns_name] = {'pods': pods}

        # Add as separate OCPGenerator entry
        ocp_generator = {
            'OCPGenerator': {
                'start_date': '2025-10-01',
                'end_date': '2025-10-02',
                'nodes': [node]  # Single node per generator
            }
        }
        manifest['ocp']['generators'].append(ocp_generator)

        # Generate matching EC2 instance
        ec2 = {
            'EC2Generator': {
                'start_date': '2025-10-01',
                'end_date': '2025-10-02',
                'resource_id': resource_id,
                'instance_type': {
                    'inst_type': 'm5.4xlarge',
                    'physical_cores': 8,
                    'vcpu': '16',
                    'memory': '64 GiB',
                    'cost': 0.768,
                    'rate': 0.768
                },
                'tags': {
                    'openshift_cluster': 'benchmark-cluster',
                    'openshift_node': node_name
                }
            }
        }
        manifest['aws']['generators'].append(ec2)

    return manifest


def main():
    """Generate all benchmark manifests."""
    output_dir = Path(__file__).parent.parent / 'test-manifests' / 'ocp-aws-benchmarks'
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating OCP-on-AWS benchmark manifests...")
    print("=" * 60)

    for scale_name, config in SCALES.items():
        manifest = generate_manifest(scale_name, config)

        # Write manifest
        output_file = output_dir / f'benchmark_{scale_name}.yml'

        # Custom YAML dump to preserve formatting
        with open(output_file, 'w') as f:
            # Write header comment
            f.write(f"# Benchmark Scale: {scale_name}\n")
            f.write(f"# Target: {config['target_rows']:,} output rows (±1%)\n")
            f.write(f"# Nodes: {config['nodes']}, Pods/node: {config['pods_per_node']}\n")
            f.write(f"# Total pods: {config['nodes'] * config['pods_per_node']}\n")
            f.write("#\n")

            # Remove comment key before dumping
            del manifest['__comment__']

            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        total_pods = config['nodes'] * config['pods_per_node']
        expected_rows = total_pods * 24 * 2

        print(f"✓ {scale_name}: {config['nodes']} nodes, {total_pods} pods → ~{expected_rows:,} rows")
        print(f"  Written to: {output_file}")

    print("=" * 60)
    print("All manifests generated!")
    print("\nNext steps:")
    print("1. Run nise to generate test data")
    print("2. Convert CSV to Parquet")
    print("3. Upload to MinIO")
    print("4. Run benchmarks")


if __name__ == '__main__':
    main()

