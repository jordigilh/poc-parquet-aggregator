# OCP-on-AWS Benchmark Manifests

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
