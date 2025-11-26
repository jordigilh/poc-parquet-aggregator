# OCP-Only Benchmark Manifests

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
