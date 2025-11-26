#!/usr/bin/env python3
"""
Generate OCP-on-AWS benchmark manifests for different scales.

Creates nise manifests that will produce approximately the target number of
INPUT rows (combined OCP + AWS hourly data).

Usage:
    python scripts/generate_ocp_aws_benchmark_manifests.py
"""

import os
from pathlib import Path

# Output directory
MANIFESTS_DIR = Path(__file__).parent.parent / "test-manifests" / "ocp-aws-benchmarks"
MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

# Scale configurations
# Scale names refer to TARGET INPUT ROWS (combined OCP + AWS hourly data)
# Formula:
#   OCP input = pods × 24 hours
#   AWS input = resources × 24 hours
#   Total input ≈ OCP input (AWS is small relative to OCP)
#
# So pods needed ≈ target_input / 24
#
# | Scale | Target Input | Pods Needed | Nodes | AWS Resources |
# |-------|--------------|-------------|-------|---------------|
# | 20k   | 20,000       | 833         | 10    | 10            |
# | 50k   | 50,000       | 2,083       | 20    | 20            |
# | 100k  | 100,000      | 4,167       | 40    | 40            |
# | 250k  | 250,000      | 10,417      | 100   | 100           |
# | 500k  | 500,000      | 20,833      | 200   | 200           |
# | 1m    | 1,000,000    | 41,667      | 400   | 400           |
# | 1.5m  | 1,500,000    | 62,500      | 600   | 600           |
# | 2m    | 2,000,000    | 83,333      | 800   | 800           |

SCALES = {
    "scale-20k": {
        "nodes": 10,
        "pods_per_node": 83,   # 10 * 83 = 830 pods → 19,920 OCP input rows
        "aws_resources_per_node": 1,  # 10 AWS resources
        "expected_input": 20160,  # 19,920 OCP + 240 AWS
    },
    "scale-50k": {
        "nodes": 20,
        "pods_per_node": 104,  # 20 * 104 = 2,080 pods → 49,920 OCP input rows
        "aws_resources_per_node": 1,  # 20 AWS resources
        "expected_input": 50400,
    },
    "scale-100k": {
        "nodes": 40,
        "pods_per_node": 104,  # 40 * 104 = 4,160 pods → 99,840 OCP input rows
        "aws_resources_per_node": 1,  # 40 AWS resources
        "expected_input": 100800,
    },
    "scale-250k": {
        "nodes": 100,
        "pods_per_node": 104,  # 100 * 104 = 10,400 pods → 249,600 OCP input rows
        "aws_resources_per_node": 1,  # 100 AWS resources
        "expected_input": 252000,
    },
    "scale-500k": {
        "nodes": 200,
        "pods_per_node": 104,  # 200 * 104 = 20,800 pods → 499,200 OCP input rows
        "aws_resources_per_node": 1,  # 200 AWS resources
        "expected_input": 504000,
    },
    "scale-1m": {
        "nodes": 400,
        "pods_per_node": 104,  # 400 * 104 = 41,600 pods → 998,400 OCP input rows
        "aws_resources_per_node": 1,  # 400 AWS resources
        "expected_input": 1008000,
    },
    "scale-1.5m": {
        "nodes": 600,
        "pods_per_node": 104,  # 600 * 104 = 62,400 pods → 1,497,600 OCP input rows
        "aws_resources_per_node": 1,  # 600 AWS resources
        "expected_input": 1512000,
    },
    "scale-2m": {
        "nodes": 800,
        "pods_per_node": 104,  # 800 * 104 = 83,200 pods → 1,996,800 OCP input rows
        "aws_resources_per_node": 1,  # 800 AWS resources
        "expected_input": 2016000,
    },
}


def generate_manifest(scale_name: str, config: dict) -> str:
    """Generate a nise manifest for the given scale (OCP-on-AWS)."""
    nodes = config["nodes"]
    pods_per_node = config["pods_per_node"]
    aws_resources_per_node = config["aws_resources_per_node"]
    total_pods = nodes * pods_per_node
    total_aws = nodes * aws_resources_per_node

    # Build OCP nodes section
    ocp_nodes_yaml = []
    for node_idx in range(nodes):
        node_name = f"bench-node-{node_idx + 1:03d}"
        resource_id = f"i-bench-node-{node_idx + 1:03d}"

        # Build pods for this node
        pods_yaml = []
        for pod_idx in range(pods_per_node):
            pod_name = f"app-n{node_idx + 1:03d}-{pod_idx + 1:03d}"
            pods_yaml.append(f"""            - pod: null
              pod_name: {pod_name}
              cpu_request: 1
              mem_request_gig: 2
              cpu_limit: 2
              mem_limit_gig: 4
              pod_seconds: 3600
              cpu_usage:
                full_period: 0.8
              mem_usage_gig:
                full_period: 1.5""")

        pods_str = "\n".join(pods_yaml)
        namespace_name = f"bench-ns-{node_idx + 1:03d}"

        ocp_nodes_yaml.append(f"""      - node: null
        node_name: {node_name}
        resource_id: {resource_id}
        cpu_cores: 16
        memory_gig: 64
        namespaces:
          {namespace_name}:
            pods:
{pods_str}""")

    ocp_nodes_str = "\n".join(ocp_nodes_yaml)

    # Build AWS EC2 generators section
    aws_ec2_yaml = []
    for node_idx in range(nodes):
        resource_id = f"i-bench-node-{node_idx + 1:03d}"
        aws_ec2_yaml.append(f"""  - EC2Generator:
      start_date: '2025-10-01'
      end_date: '2025-10-02'
      resource_id: '{resource_id}'
      instance_type:
        inst_type: m5.xlarge
        vcpu: 4
        memory: '16'
        storage: gp2
        family: Compute optimized
        cost: 0.192
        rate: 0.192
      processor_arch: x86_64
      region: us-east-1
      tags:
        openshift_cluster: benchmark-cluster
        openshift_project: bench-ns-{node_idx + 1:03d}
        openshift_node: bench-node-{node_idx + 1:03d}""")

    aws_ec2_str = "\n".join(aws_ec2_yaml)

    manifest = f"""# OCP-on-AWS benchmark manifest: {scale_name}
# Expected INPUT rows: ~{config['expected_input']:,} (OCP + AWS hourly data)
# OCP: {nodes} nodes, {pods_per_node} pods/node = {total_pods} pods → {total_pods * 24:,} input rows
# AWS: {total_aws} EC2 instances → {total_aws * 24:,} input rows
#
start_date: '2025-10-01'
end_date: '2025-10-02'

ocp:
  generators:
  - OCPGenerator:
      start_date: '2025-10-01'
      end_date: '2025-10-02'
      nodes:
{ocp_nodes_str}

aws:
  generators:
{aws_ec2_str}
"""

    return manifest


def main():
    print(f"Generating OCP-on-AWS benchmark manifests in: {MANIFESTS_DIR}")
    print()

    for scale_name, config in SCALES.items():
        filename = f"benchmark_{scale_name}.yml"
        filepath = MANIFESTS_DIR / filename

        manifest = generate_manifest(scale_name, config)

        with open(filepath, "w") as f:
            f.write(manifest)

        nodes = config["nodes"]
        pods = config["pods_per_node"]
        total_pods = nodes * pods
        expected_input = config["expected_input"]
        aws_resources = nodes * config["aws_resources_per_node"]

        print(f"  ✓ {filename}")
        print(f"    OCP: {nodes} nodes × {pods} pods = {total_pods:,} pods")
        print(f"    AWS: {aws_resources} EC2 instances")
        print(f"    Expected INPUT: ~{expected_input:,} rows")
        print()

    # Create README
    readme = """# OCP-on-AWS Benchmark Manifests

These manifests generate synthetic OCP + AWS data for benchmarking.

## Scales

Scale names refer to **INPUT ROWS** (combined OCP + AWS hourly data).

| Scale | Nodes | Pods/Node | Total Pods | AWS Resources | Input Rows |
|-------|-------|-----------|------------|---------------|------------|
| 20k   | 10    | 83        | 830        | 10            | ~20,160    |
| 50k   | 20    | 104       | 2,080      | 20            | ~50,400    |
| 100k  | 40    | 104       | 4,160      | 40            | ~100,800   |
| 250k  | 100   | 104       | 10,400     | 100           | ~252,000   |
| 500k  | 200   | 104       | 20,800     | 200           | ~504,000   |
| 1m    | 400   | 104       | 41,600     | 400           | ~1,008,000 |
| 1.5m  | 600   | 104       | 62,400     | 600           | ~1,512,000 |
| 2m    | 800   | 104       | 83,200     | 800           | ~2,016,000 |

## Usage

```bash
# Run all benchmarks
./scripts/run_ocp_aws_benchmarks.sh

# Run single scale
./scripts/run_ocp_aws_benchmarks.sh scale-100k
```

## Formula

```
OCP input = total_pods × 24 hours
AWS input = aws_resources × 24 hours
Total input ≈ OCP input + AWS input
Output rows = daily aggregated matched summaries (smaller than input)
```
"""

    with open(MANIFESTS_DIR / "README.md", "w") as f:
        f.write(readme)

    print("✓ Generated README.md")
    print()
    print("Run benchmarks with: ./scripts/run_ocp_aws_benchmarks.sh")


if __name__ == "__main__":
    main()

