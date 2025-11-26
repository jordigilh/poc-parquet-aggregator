#!/usr/bin/env python3
"""
Generate OCP-only benchmark manifests for different scales.

Creates nise manifests that will produce approximately the target number of
output rows after aggregation.

Usage:
    python scripts/generate_ocp_benchmark_manifests.py
"""

import os
from pathlib import Path

# Output directory
MANIFESTS_DIR = Path(__file__).parent.parent / "test-manifests" / "ocp-benchmarks"
MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

# Scale configurations
# For OCP-only: output_rows ≈ pods * hours * 2 (pod + storage data sources)
# With 24 hours per day, we can estimate:
#   - 20k output: ~420 pods (420 * 24 * 2 = 20,160)
#   - 50k output: ~1042 pods
#   - 100k output: ~2083 pods
#   - 250k output: ~5208 pods
#   - 500k output: ~10417 pods
#   - 1m output: ~20833 pods

SCALES = {
    "20k": {
        "nodes": 5,
        "pods_per_node": 84,  # 5 * 84 = 420 pods
        "expected_output": 20160,
    },
    "50k": {
        "nodes": 10,
        "pods_per_node": 105,  # 10 * 105 = 1050 pods
        "expected_output": 50400,
    },
    "100k": {
        "nodes": 15,
        "pods_per_node": 139,  # 15 * 139 = 2085 pods
        "expected_output": 100080,
    },
    "250k": {
        "nodes": 25,
        "pods_per_node": 209,  # 25 * 209 = 5225 pods
        "expected_output": 250800,
    },
    "500k": {
        "nodes": 35,
        "pods_per_node": 298,  # 35 * 298 = 10430 pods
        "expected_output": 500640,
    },
    "1m": {
        "nodes": 50,
        "pods_per_node": 417,  # 50 * 417 = 20850 pods
        "expected_output": 1000800,
    },
    "1.5m": {
        "nodes": 60,
        "pods_per_node": 521,  # 60 * 521 = 31260 pods
        "expected_output": 1500480,
    },
    "2m": {
        "nodes": 70,
        "pods_per_node": 595,  # 70 * 595 = 41650 pods
        "expected_output": 1999200,
    },
}


def generate_manifest(scale_name: str, config: dict) -> str:
    """Generate a nise manifest for the given scale."""
    nodes = config["nodes"]
    pods_per_node = config["pods_per_node"]

    # Build nodes section
    nodes_yaml = []
    for node_idx in range(nodes):
        node_name = f"node-{node_idx + 1:03d}"
        resource_id = f"i-benchmark{node_idx + 1:05d}"

        # Build pods for this node
        pods_yaml = []
        for pod_idx in range(pods_per_node):
            pod_name = f"app-{node_idx + 1:03d}-{pod_idx + 1:04d}"
            pods_yaml.append(f"""            - pod: null
              pod_name: {pod_name}
              cpu_request: 0.5
              mem_request_gig: 1
              cpu_limit: 1
              mem_limit_gig: 2
              pod_seconds: 3600
              cpu_usage:
                full_period: 0.3
              mem_usage_gig:
                full_period: 0.5
              labels: app:benchmark|tier:web|node:{node_name}|pod:{pod_name}""")

        pods_str = "\n".join(pods_yaml)
        namespace_name = f"benchmark-{node_idx + 1:03d}"  # Unique namespace per node

        nodes_yaml.append(f"""      - node: null
        node_name: {node_name}
        resource_id: {resource_id}
        cpu_cores: 8
        memory_gig: 32
        namespaces:
          {namespace_name}:
            pods:
{pods_str}""")

    nodes_str = "\n".join(nodes_yaml)

    manifest = f"""# OCP-only benchmark manifest: {scale_name}
# Expected output rows: ~{config['expected_output']:,}
# Nodes: {nodes}, Pods per node: {pods_per_node}, Total pods: {nodes * pods_per_node}
#
# Formula: output_rows ≈ pods * hours * data_sources
#          where data_sources = 2 (Pod + Storage)
#          and hours = 24 (full day)

start_date: 2025-10-01
end_date: 2025-10-02

generators:
  - OCPGenerator:
      start_date: 2025-10-01
      end_date: 2025-10-02
      nodes:
{nodes_str}
"""

    return manifest


def main():
    print(f"Generating OCP benchmark manifests in: {MANIFESTS_DIR}")
    print()

    for scale_name, config in SCALES.items():
        filename = f"benchmark_ocp_{scale_name}.yml"
        filepath = MANIFESTS_DIR / filename

        manifest = generate_manifest(scale_name, config)

        with open(filepath, "w") as f:
            f.write(manifest)

        nodes = config["nodes"]
        pods = config["pods_per_node"]
        total_pods = nodes * pods
        expected = config["expected_output"]

        print(f"  ✓ {filename}")
        print(f"    Nodes: {nodes}, Pods/node: {pods}, Total: {total_pods}")
        print(f"    Expected output: ~{expected:,} rows")
        print()

    # Create README
    readme = """# OCP-Only Benchmark Manifests

These manifests generate synthetic OCP data for benchmarking.

## Scales

| Scale | Nodes | Pods/Node | Total Pods | Expected Output |
|-------|-------|-----------|------------|-----------------|
| 20k   | 5     | 84        | 420        | ~20,160         |
| 50k   | 10    | 105       | 1,050      | ~50,400         |
| 100k  | 15    | 139       | 2,085      | ~100,080        |
| 250k  | 25    | 209       | 5,225      | ~250,800        |
| 500k  | 35    | 298       | 10,430     | ~500,640        |
| 1m    | 50    | 417       | 20,850     | ~1,000,800      |

## Usage

```bash
# Run all benchmarks
./scripts/run_ocp_full_benchmarks.sh

# Run single scale
./scripts/run_ocp_full_benchmarks.sh 100k
```

## Formula

```
output_rows ≈ total_pods × hours × data_sources
            = total_pods × 24 × 2
            = total_pods × 48
```

Where:
- hours = 24 (full day of data)
- data_sources = 2 (Pod usage + Storage usage)
"""

    with open(MANIFESTS_DIR / "README.md", "w") as f:
        f.write(readme)

    print("✓ Generated README.md")
    print()
    print("Run benchmarks with: ./scripts/run_ocp_full_benchmarks.sh")


if __name__ == "__main__":
    main()


