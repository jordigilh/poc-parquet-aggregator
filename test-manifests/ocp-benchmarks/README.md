# OCP-Only Benchmark Manifests

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
