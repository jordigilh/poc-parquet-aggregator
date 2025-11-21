# Comprehensive Benchmarking Guide

## Overview

This guide explains how to run comprehensive benchmarks testing streaming vs non-streaming performance across multiple data scales.

## Quick Start

```bash
# Run all benchmarks (small through production-medium)
./scripts/run_comprehensive_scale_benchmarks.sh
```

**Time estimate**: 30-60 minutes depending on your hardware

## What Gets Tested

### Data Scales

| Scale | Pods | Namespaces | Nodes | Est. Rows | Use Case |
|-------|------|------------|-------|-----------|----------|
| **small** | 10 | 2 | 2 | ~1K | Development/Testing |
| **medium** | 100 | 5 | 5 | ~10K | Small deployments |
| **large** | 500 | 10 | 10 | ~50K | Medium deployments |
| **xlarge** | 1,000 | 10 | 20 | ~100K | Large deployments |
| **xxlarge** | 2,500 | 20 | 30 | ~250K | Very large deployments |
| **production-small** | 5,000 | 25 | 40 | ~500K | Production (small) |
| **production-medium** | 10,000 | 30 | 50 | ~1M | Production (medium) |
| **production-large** | 20,000 | 40 | 100 | ~2M | Production (large) |

### Test Modes

For each scale, the benchmark runs in **two modes**:

1. **Non-Streaming** - Loads entire dataset into memory (baseline)
2. **Streaming** - Processes data in 50K row chunks (constant memory)

### Metrics Collected

For each test:
- **Input rows**: Number of raw data rows
- **Output rows**: Number of aggregated rows
- **Duration**: Total processing time (seconds)
- **Peak memory**: Maximum memory usage (MB)
- **Memory per 1K rows**: Memory efficiency metric
- **Processing rate**: Throughput (rows/second)
- **CPU time**: Total CPU seconds used
- **Compression ratio**: Input rows / output rows

## Running Individual Scales

### Test a Single Scale

```bash
# Just test large scale
SCALES=("large") ./scripts/run_comprehensive_scale_benchmarks.sh
```

### Test Subset of Scales

Edit the script and modify the `SCALES` array:

```bash
# Edit the script
vi ./scripts/run_comprehensive_scale_benchmarks.sh

# Change this line (around line 14):
SCALES=(
    "small"
    "medium"
    "large"
    # "xlarge"            # Comment out scales you don't want
    # "xxlarge"
    # "production-small"
    # "production-medium"
)
```

### Manual Scale Generation and Testing

#### Step 1: Generate Data for a Specific Scale

```bash
# Generate production-medium scale (1M rows)
./scripts/generate_nise_benchmark_data.sh production-medium /tmp/benchmark-data
```

#### Step 2: Review the Generated Data

```bash
# Check metadata
cat /tmp/benchmark-data/metadata_production-medium.json

# Check CSV files
ls -lh /tmp/benchmark-data/*.csv
```

#### Step 3: Convert to Parquet and Upload

```bash
# Get the provider UUID from metadata
PROVIDER_UUID=$(jq -r '.provider_uuid' /tmp/benchmark-data/metadata_production-medium.json)

# Convert and upload
python3 scripts/csv_to_parquet_minio.py \
    --csv-dir /tmp/benchmark-data \
    --provider-uuid "${PROVIDER_UUID}" \
    --org-id 1234567
```

#### Step 4: Run Benchmark

```bash
# Export environment variables
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export POSTGRES_HOST="localhost"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"

# Run with streaming
python3 scripts/benchmark_performance.py \
    --provider-uuid "${PROVIDER_UUID}" \
    --year 2025 \
    --month 10 \
    --output results/streaming_1m_rows.json \
    --truncate

# Run without streaming (modify config first)
# Set use_streaming: false in config/config.yaml
python3 scripts/benchmark_performance.py \
    --provider-uuid "${PROVIDER_UUID}" \
    --year 2025 \
    --month 10 \
    --output results/non_streaming_1m_rows.json \
    --truncate
```

## Output Files

After running, you'll find results in `benchmark_results/comprehensive_YYYYMMDD_HHMMSS/`:

```
benchmark_results/comprehensive_20251120_150000/
├── BENCHMARK_SUMMARY.md          # Human-readable report
├── benchmark_results.csv         # Raw data (for analysis)
├── performance_comparison.png     # Visual charts
├── data/                          # Generated test data
│   ├── small/
│   ├── medium/
│   └── ...
├── logs/                          # Detailed logs
│   ├── generate_small.log
│   ├── small_streaming.log
│   ├── small_non-streaming.log
│   └── ...
├── small_streaming.json          # Detailed JSON results
├── small_non-streaming.json
└── ...
```

## Interpreting Results

### Memory Usage

**Look for**:
- Streaming mode should have **constant** peak memory regardless of scale
- Non-streaming memory should **grow linearly** with data size
- **Savings %**: (non_streaming_memory - streaming_memory) / non_streaming_memory * 100

**Expected**:
- Small scales: 20-40% savings
- Large scales: 80-95% savings
- Production scales: 95%+ savings

### Processing Time

**Look for**:
- Streaming might be slightly slower on small datasets (overhead)
- Should be comparable or faster on large datasets
- Linear growth with data size for both modes

### Memory per 1K Rows

**Look for**:
- Streaming: Should be **constant** across all scales
- Non-streaming: May increase with scale due to memory pressure
- Lower is better (more efficient)

### Example Good Results

```markdown
### Production-Medium (1M rows)

| Metric | Non-Streaming | Streaming | Improvement |
|--------|---------------|-----------|-------------|
| Duration | 45.2s | 42.8s | +5.3% faster |
| Peak Memory | 2,400 MB | 250 MB | **-89.6% memory** |
| Memory/1K rows | 2.4 MB | 0.25 MB | -89.6% |
| Processing Rate | 22,124 rows/s | 23,364 rows/s | +5.6% |
```

## Troubleshooting

### Out of Memory

If non-streaming tests fail with OOM:
1. Skip those scales for non-streaming
2. Only test streaming mode for large scales
3. Increase system swap space

### Slow Performance

If benchmarks are too slow:
1. Test fewer scales
2. Use smaller scales
3. Check system resources (CPU, disk I/O)

### PostgreSQL Connection Issues

```bash
# Restart local environment
./scripts/stop-local-env.sh
./scripts/start-local-env.sh
```

### MinIO Connection Issues

```bash
# Check MinIO is running
podman ps | grep minio

# Restart if needed
podman restart minio-poc
```

## Advanced: Custom Scale Configuration

Create your own scale in `generate_nise_benchmark_data.sh`:

```bash
custom-scale)
    PODS=15000
    NAMESPACES=35
    NODES=75
    DAYS=1
    DESCRIPTION="Custom Scale (1.5M rows)"
    ;;
```

Then add it to the `SCALES` array in `run_comprehensive_scale_benchmarks.sh`.

## Performance Optimization Tips

### For Faster Benchmarks

1. **Use SSD storage** for MinIO and PostgreSQL
2. **Increase CPU cores** allocated to podman containers
3. **Add more RAM** to system
4. **Parallel testing**: Run multiple isolated environments

### For More Accurate Results

1. **Close other applications** during benchmarking
2. **Run multiple iterations** and average results
3. **Warm up** the system with a small test first
4. **Monitor system resources** with `htop` or similar

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Performance Benchmarks

on:
  pull_request:
    branches: [main]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run benchmarks
        run: |
          ./scripts/start-local-env.sh
          SCALES=("small" "medium" "large") ./scripts/run_comprehensive_scale_benchmarks.sh
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: benchmark-results
          path: benchmark_results/
```

## Next Steps

After running benchmarks:

1. **Review BENCHMARK_SUMMARY.md** for insights
2. **Analyze CSV data** for trends
3. **Share charts** with stakeholders
4. **Document findings** in project documentation
5. **Compare against targets** (e.g., "must handle 1M rows in < 60s")

---

**For questions or issues**: See main README.md or create an issue.

