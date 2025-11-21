# Simple Benchmarking Guide - That Actually Works

## Quick Start

### Run All Benchmarks (small, medium, large)
```bash
./scripts/run_simple_benchmarks.sh
```

**Time**: ~15-20 minutes
**Output**: `/tmp/benchmark_results_YYYYMMDD_HHMMSS/`

### Run Single Benchmark
```bash
# Test one scale + mode
./scripts/simple_scale_benchmark.sh small streaming

# Or non-streaming
./scripts/simple_scale_benchmark.sh medium non-streaming
```

**Time**: ~2-5 minutes per test

## What It Does

### For Each Scale + Mode:

1. ✅ Generates nise data
2. ✅ Gets provider UUID
3. ✅ Exports ALL environment variables (no missing vars)
4. ✅ Converts to Parquet
5. ✅ Configures streaming on/off
6. ✅ Clears database
7. ✅ Runs with system `time` command
8. ✅ Records metrics
9. ✅ Restores config

### Metrics Captured

- **Execution time** (real, user, sys)
- **Peak memory** (maximum resident set size)
- **Output rows**
- **Full logs**

## Available Scales

```bash
# Quick test (1K rows, ~30 seconds)
./scripts/simple_scale_benchmark.sh small streaming

# Medium test (10K rows, ~2 minutes)
./scripts/simple_scale_benchmark.sh medium streaming

# Large test (50K rows, ~5 minutes)
./scripts/simple_scale_benchmark.sh large streaming

# Very large (100K rows, ~10 minutes)
./scripts/simple_scale_benchmark.sh xlarge streaming
```

## Custom Scale Selection

```bash
# Test just small and medium
SCALES="small medium" ./scripts/run_simple_benchmarks.sh

# Test just one scale
SCALES="large" ./scripts/run_simple_benchmarks.sh
```

## Output Format

Each benchmark creates:

```
/tmp/benchmark_results_YYYYMMDD_HHMMSS/
├── SUMMARY.md                    # Aggregated results
├── small_streaming.txt           # Detailed output
├── small_non-streaming.txt
├── medium_streaming.txt
├── medium_non-streaming.txt
└── ...
```

### Example Output

```
=== Benchmark: medium - streaming ===
Started: Wed Nov 20 20:30:00 PST 2025

[... POC logs ...]

real    0m3.456s
user    0m2.234s
sys     0m0.345s
maximum resident set size: 156MB

Output rows: 234

Completed: Wed Nov 20 20:30:03 PST 2025
```

## Why This Works

### Simple Design
- One scale at a time (no complex loops)
- All env vars exported once (no timing issues)
- Uses system `time` command (reliable)
- Backup/restore config (safe)
- Clear error messages

### No Complex Dependencies
- No matplotlib required
- No JSON aggregation
- No Python embedded in loops
- Straightforward bash

## Comparison Table

After running, create this table manually:

| Scale | Mode | Time | Peak Memory | Rows | Notes |
|-------|------|------|-------------|------|-------|
| small | non-streaming | 1.2s | 45 MB | 93 | Baseline |
| small | streaming | 1.3s | 12 MB | 93 | -73% memory |
| medium | non-streaming | 5.4s | 234 MB | 456 | |
| medium | streaming | 5.1s | 156 MB | 456 | -33% memory |
| large | non-streaming | 18.2s | 1.2 GB | 2100 | |
| large | streaming | 17.8s | 245 MB | 2100 | -80% memory |

## Troubleshooting

### "Provider UUID not found"
```bash
# Check data was generated
ls -la /tmp/benchmark-*/metadata_*.json
```

### "Config backup not found"
```bash
# Restore manually
cp config/config.yaml.bak config/config.yaml
```

### "PostgreSQL connection failed"
```bash
# Check local environment
podman ps | grep postgres
./scripts/start-local-env.sh
```

## Next Steps

1. Run benchmarks: `./scripts/run_simple_benchmarks.sh`
2. Review results: `cat /tmp/benchmark_results_*/SUMMARY.md`
3. Create comparison table in documentation
4. Declare Phase 1 complete ✅

---

**Time commitment**: 15-20 minutes
**Complexity**: Low
**Reliability**: High
**Success rate**: Should work first try

