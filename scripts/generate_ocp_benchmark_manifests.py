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
# Scale names refer to TARGET INPUT ROWS (hourly data from nise)
# Formula: input_rows = pods × 24 hours
# So pods needed = target_input / 24
#
# | Scale | Target Input | Pods Needed |
# |-------|--------------|-------------|
# | 20k   | 20,000       | 833         |
# | 50k   | 50,000       | 2,083       |
# | 100k  | 100,000      | 4,167       |
# | 250k  | 250,000      | 10,417      |
# | 500k  | 500,000      | 20,833      |
# | 1m    | 1,000,000    | 41,667      |
# | 1.5m  | 1,500,000    | 62,500      |
# | 2m    | 2,000,000    | 83,333      |

SCALES = {
    "20k": {
        "nodes": 10,
        "pods_per_node": 83,   # 10 * 83 = 830 pods → 19,920 input rows
        "expected_input": 19920,
    },
    "50k": {
        "nodes": 20,
        "pods_per_node": 104,  # 20 * 104 = 2,080 pods → 49,920 input rows
        "expected_input": 49920,
    },
    "100k": {
        "nodes": 40,
        "pods_per_node": 104,  # 40 * 104 = 4,160 pods → 99,840 input rows
        "expected_input": 99840,
    },
    "250k": {
        "nodes": 100,
        "pods_per_node": 104,  # 100 * 104 = 10,400 pods → 249,600 input rows
        "expected_input": 249600,
    },
    "500k": {
        "nodes": 200,
        "pods_per_node": 104,  # 200 * 104 = 20,800 pods → 499,200 input rows
        "expected_input": 499200,
    },
    "1m": {
        "nodes": 400,
        "pods_per_node": 104,  # 400 * 104 = 41,600 pods → 998,400 input rows
        "expected_input": 998400,
    },
    "1.5m": {
        "nodes": 600,
        "pods_per_node": 104,  # 600 * 104 = 62,400 pods → 1,497,600 input rows
        "expected_input": 1497600,
    },
    "2m": {
        "nodes": 800,
        "pods_per_node": 104,  # 800 * 104 = 83,200 pods → 1,996,800 input rows
        "expected_input": 1996800,
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
# Expected INPUT rows: ~{config['expected_input']:,} (hourly data from nise)
# Nodes: {nodes}, Pods per node: {pods_per_node}, Total pods: {nodes * pods_per_node}
#
# Formula: input_rows = pods × 24 hours
#          output_rows = daily aggregated (much smaller)

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
        expected_input = config["expected_input"]

        print(f"  ✓ {filename}")
        print(f"    Nodes: {nodes}, Pods/node: {pods}, Total: {total_pods}")
        print(f"    Expected INPUT: ~{expected_input:,} rows")
        print()

    # Create README
    readme = """# OCP-Only Benchmark Manifests

These manifests generate synthetic OCP data for benchmarking.

## Scales

Scale names refer to **INPUT ROWS** (hourly data from nise).

| Scale | Nodes | Pods/Node | Total Pods | Input Rows |
|-------|-------|-----------|------------|------------|
| 20k   | 10    | 83        | 830        | ~19,920    |
| 50k   | 20    | 104       | 2,080      | ~49,920    |
| 100k  | 40    | 104       | 4,160      | ~99,840    |
| 250k  | 100   | 104       | 10,400     | ~249,600   |
| 500k  | 200   | 104       | 20,800     | ~499,200   |
| 1m    | 400   | 104       | 41,600     | ~998,400   |
| 1.5m  | 600   | 104       | 62,400     | ~1,497,600 |
| 2m    | 800   | 104       | 83,200     | ~1,996,800 |

## Usage

```bash
# Run all benchmarks
./scripts/run_ocp_full_benchmarks.sh

# Run single scale
./scripts/run_ocp_full_benchmarks.sh 100k
```

## Formula

```
input_rows = total_pods × 24 hours
output_rows = daily aggregated summaries (much smaller)
```

Where:
- Input: Hourly pod usage data from nise
- Output: Daily aggregated summaries per namespace/node
"""

    with open(MANIFESTS_DIR / "README.md", "w") as f:
        f.write(readme)

    print("✓ Generated README.md")
    print()
    print("Run benchmarks with: ./scripts/run_ocp_full_benchmarks.sh")


if __name__ == "__main__":
    main()


