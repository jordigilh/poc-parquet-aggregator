# Benchmarking Quick Start

## 🚀 Run All Benchmarks (Recommended)

```bash
# Test all scales with streaming vs non-streaming comparison
./scripts/run_comprehensive_scale_benchmarks.sh
```

**What it does**:
- ✅ Tests 7 different scales (1K to 1M rows)
- ✅ Compares streaming vs non-streaming for each
- ✅ Generates detailed report with charts
- ✅ Collects performance metrics

**Time**: ~30-60 minutes

**Output**: `benchmark_results/comprehensive_YYYYMMDD_HHMMSS/`

---

## 📊 What You Get

### 1. Summary Report (`BENCHMARK_SUMMARY.md`)

```markdown
### Production-Medium (1M rows)

| Metric | Non-Streaming | Streaming | Improvement |
|--------|---------------|-----------|-------------|
| Duration | 45.2s | 42.8s | +5.3% faster |
| Peak Memory | 2,400 MB | 250 MB | -89.6% memory ✨ |
| Memory/1K rows | 2.4 MB | 0.25 MB | -89.6% |
| Processing Rate | 22,124 rows/s | 23,364 rows/s | +5.6% |
```

### 2. Raw Data (`benchmark_results.csv`)

```csv
scale,mode,input_rows,output_rows,duration_seconds,peak_memory_mb,...
small,non-streaming,1024,93,1.2,45.3,...
small,streaming,1024,93,1.3,12.1,...
...
```

### 3. Visual Charts (`performance_comparison.png`)

- Memory usage by scale
- Processing time comparison
- Memory efficiency trends
- Throughput analysis

---

## 🎯 Individual Scale Tests

### Quick Tests (Development)

```bash
# Small dataset (~1K rows) - 30 seconds
./scripts/generate_nise_benchmark_data.sh small
```

### Medium Tests (Validation)

```bash
# Medium dataset (~10K rows) - 2 minutes
./scripts/generate_nise_benchmark_data.sh medium

# Large dataset (~50K rows) - 5 minutes
./scripts/generate_nise_benchmark_data.sh large
```

### Production Tests (Performance Validation)

```bash
# 500K rows - 15 minutes
./scripts/generate_nise_benchmark_data.sh production-small

# 1M rows - 30 minutes
./scripts/generate_nise_benchmark_data.sh production-medium

# 2M rows - 60 minutes (uncomment in script first)
./scripts/generate_nise_benchmark_data.sh production-large
```

---

## 📈 Available Scales

| Scale | Pods | Nodes | Rows | Time | Memory (Streaming) | Memory (Non-Streaming) |
|-------|------|-------|------|------|-------------------|----------------------|
| small | 10 | 2 | ~1K | 30s | ~10 MB | ~50 MB |
| medium | 100 | 5 | ~10K | 2m | ~15 MB | ~150 MB |
| large | 500 | 10 | ~50K | 5m | ~25 MB | ~500 MB |
| xlarge | 1,000 | 20 | ~100K | 10m | ~50 MB | ~1 GB |
| xxlarge | 2,500 | 30 | ~250K | 20m | ~100 MB | ~2.5 GB |
| production-small | 5,000 | 40 | ~500K | 30m | ~200 MB | ~5 GB |
| production-medium | 10,000 | 50 | ~1M | 60m | ~250 MB | ~10 GB |
| production-large | 20,000 | 100 | ~2M | 120m | ~300 MB | ~20 GB* |

*May require 32GB+ RAM for non-streaming mode

---

## 🔍 Key Metrics Explained

### Peak Memory
- **Streaming**: Should be constant (~100-300 MB)
- **Non-Streaming**: Grows with data size
- **Goal**: Streaming uses < 500 MB even for 1M+ rows

### Processing Rate (rows/second)
- **Typical**: 10,000 - 50,000 rows/sec
- **Factors**: CPU speed, disk I/O, complexity of aggregations
- **Goal**: Linear scaling (2x data = 2x time, not 4x time)

### Memory per 1K Rows
- **Streaming**: Constant (0.1 - 0.3 MB)
- **Non-Streaming**: May increase with scale
- **Goal**: < 0.5 MB per 1K rows for streaming

### Compression Ratio
- **Typical**: 10x - 50x (10K rows → 200-1000 aggregated rows)
- **Higher is better**: More aggregation efficiency
- **Depends on**: Number of unique namespaces/nodes/dates

---

## ⚡ Quick Commands

### Test Just Streaming (Skip Non-Streaming)

```bash
# Manually test with streaming enabled
export OCP_PROVIDER_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Generate data
./scripts/generate_nise_benchmark_data.sh production-medium /tmp/test-data

# Get UUID from metadata
PROVIDER_UUID=$(jq -r '.provider_uuid' /tmp/test-data/metadata_production-medium.json)

# Convert to Parquet
python3 scripts/csv_to_parquet_minio.py --csv-dir /tmp/test-data --provider-uuid "${PROVIDER_UUID}"

# Benchmark (streaming enabled in config)
python3 scripts/benchmark_performance.py \
    --provider-uuid "${PROVIDER_UUID}" \
    --year 2025 \
    --month 10 \
    --output results_streaming.json
```

### Compare Two Runs

```bash
# Run 1: Non-streaming
# (Set use_streaming: false in config.yaml)
python3 scripts/benchmark_performance.py ... --output run1.json

# Run 2: Streaming
# (Set use_streaming: true in config.yaml)
python3 scripts/benchmark_performance.py ... --output run2.json

# Compare
python3 << 'EOF'
import json

with open('run1.json') as f:
    non_streaming = json.load(f)
with open('run2.json') as f:
    streaming = json.load(f)

print(f"Memory savings: {(1 - streaming['peak_memory_bytes']/non_streaming['peak_memory_bytes'])*100:.1f}%")
print(f"Time difference: {(streaming['total_duration_seconds']-non_streaming['total_duration_seconds']):.1f}s")
EOF
```

---

## 🛠 Prerequisites

Make sure you have:
- ✅ Local environment running (`./scripts/start-local-env.sh`)
- ✅ Python virtual environment activated (`source venv/bin/activate`)
- ✅ Required packages installed (`pip install -r requirements.txt`)
- ✅ nise installed (`pip install koku-nise`)

---

## 📝 Recommended Test Sequence

### Day 1: Initial Validation
```bash
# Quick smoke test
SCALES=("small" "medium") ./scripts/run_comprehensive_scale_benchmarks.sh
```

### Day 2: Extended Testing
```bash
# Add larger scales
SCALES=("small" "medium" "large" "xlarge") ./scripts/run_comprehensive_scale_benchmarks.sh
```

### Day 3: Production Validation
```bash
# Full production test
./scripts/run_comprehensive_scale_benchmarks.sh  # All scales
```

---

## 🎯 Success Criteria

Your Phase 1 implementation is successful if:

✅ **Memory**: Streaming uses < 500 MB for 1M rows (target: < 300 MB)
✅ **Savings**: > 80% memory reduction vs non-streaming
✅ **Speed**: Processing rate > 10K rows/sec
✅ **Scalability**: Linear time growth (O(n))
✅ **Stability**: No crashes or OOM errors
✅ **Correctness**: All IQE tests pass (18/18)

---

## 📚 See Also

- **Full Guide**: `COMPREHENSIVE_BENCHMARK_GUIDE.md`
- **Test Results**: `IQE_TEST_RESULTS.md`
- **Phase 1 Summary**: `PHASE1_IMPLEMENTATION_COMPLETE.md`
- **Validation Process**: `VALIDATION_PROCESS_EXPLAINED.md`

---

**Ready to benchmark? Run this:**

```bash
./scripts/run_comprehensive_scale_benchmarks.sh
```

Then check `benchmark_results/comprehensive_*/BENCHMARK_SUMMARY.md` for results! 🎉

