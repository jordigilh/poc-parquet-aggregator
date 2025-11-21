# Streaming Benchmark Plan

**Objective**: Compare streaming vs in-memory performance across multiple data scales
**Purpose**: Determine optimal threshold for enabling streaming mode
**Next**: Implement storage/PV aggregation after benchmarks complete

---

## Benchmark Scenarios Available

From `scripts/generate_nise_benchmark_data.sh`:

| Scale | Pods | Namespaces | Nodes | Est. Rows | Est. Memory |
|-------|------|------------|-------|-----------|-------------|
| small | 10 | 2 | 2 | ~1K | ~10 MB |
| medium | 100 | 5 | 5 | ~10K | ~100 MB |
| large | 500 | 10 | 10 | ~50K | ~500 MB |
| xlarge | 1,000 | 10 | 20 | ~100K | ~1 GB |
| xxlarge | 2,500 | 20 | 30 | ~250K | ~2.5 GB |
| production-small | 5,000 | 25 | 40 | ~500K | ~5 GB |
| production-medium | 10,000 | 30 | 50 | ~1M | ~10 GB |
| production-large | 20,000 | 40 | 100 | ~2M | ~20 GB |

---

## Benchmark Matrix

We'll run both modes for each scale:

| Scale | In-Memory Expected | Streaming Expected | Key Metric |
|-------|-------------------|-------------------|------------|
| small | ✅ Fast (~1s) | ⚠️ Overhead | Baseline |
| medium | ✅ Fast (~5s) | ⚠️ Overhead | Still optimal in-memory |
| large | ✅ Good (~25s) | ✅ Good (~30s) | **Crossover point?** |
| xlarge | ⚠️ Slow (~50s) | ✅ Better (~60s) | Streaming competitive |
| xxlarge | ❌ High memory | ✅ Constant mem | **Streaming wins** |
| production-small | ❌ Very high mem | ✅ Constant mem | Streaming required |
| production-medium | ❌ Won't fit | ✅ Works | Only option |
| production-large | ❌ Won't fit | ✅ Works | Only option |

**Expected Crossover**: Between `large` (50K rows) and `xlarge` (100K rows)

---

## Test Plan

### Phase 1: Small-Scale Validation (Quick)
**Purpose**: Verify both modes work, establish baseline

**Scales to test**: small, medium, large
**Expected duration**: ~10 minutes
**Memory**: All fit in memory

```bash
# Run quick validation
./scripts/run_streaming_comparison.sh small medium large
```

**Expected Results**:
- ✅ Both modes complete successfully
- ✅ In-memory faster at all scales
- ✅ Streaming uses less memory
- ✅ IQE tests pass in both modes

### Phase 2: Crossover Detection (Medium)
**Purpose**: Find the inflection point where streaming becomes competitive

**Scales to test**: large, xlarge, xxlarge
**Expected duration**: ~30-60 minutes
**Memory**: May exceed available memory at xxlarge

```bash
# Find crossover point
./scripts/run_streaming_comparison.sh large xlarge xxlarge
```

**Expected Results**:
- ✅ Identify optimal threshold (likely ~100K-250K rows)
- ✅ Document memory vs speed trade-off
- ⚠️ In-memory may fail at xxlarge (out of memory)

### Phase 3: Production Scale (Long)
**Purpose**: Validate streaming at production scales

**Scales to test**: production-small, production-medium
**Expected duration**: 2-4 hours
**Memory**: Will exceed available memory in in-memory mode

```bash
# Production scale (streaming only)
./scripts/run_streaming_benchmarks.sh production-small production-medium
```

**Expected Results**:
- ✅ Streaming completes successfully
- ❌ In-memory fails (out of memory)
- ✅ Constant memory usage confirmed
- ✅ Processing time scales linearly

---

## Metrics to Capture

For each test:
1. **Processing Time**: Total end-to-end
2. **Memory Peak**: Maximum resident set size
3. **Memory Average**: Throughout processing
4. **CPU Usage**: Average percentage
5. **Database Write Time**: Bulk COPY duration
6. **Row Counts**: Input → Output
7. **Test Status**: Pass/Fail

---

## Implementation: Streaming Comparison Script

I'll create `scripts/run_streaming_comparison.sh`:

```bash
#!/bin/bash
# Compare streaming vs in-memory performance

SCALES=("$@")
if [ ${#SCALES[@]} -eq 0 ]; then
    SCALES=("small" "medium" "large")
fi

RESULTS_DIR="benchmark_results/streaming_comparison_$(date +%Y%m%d_%H%M%S)"
mkdir -p "${RESULTS_DIR}"

echo "=================================================================="
echo "STREAMING VS IN-MEMORY COMPARISON"
echo "=================================================================="
echo "Scales: ${SCALES[*]}"
echo "Results: ${RESULTS_DIR}"
echo ""

for scale in "${SCALES[@]}"; do
    echo "=================================================================="
    echo "Testing Scale: ${scale}"
    echo "=================================================================="

    # Generate test data
    echo "1. Generating test data..."
    ./scripts/generate_nise_benchmark_data.sh "${scale}" "/tmp/nise-${scale}"

    # Upload to MinIO
    echo "2. Uploading to MinIO..."
    python3 scripts/csv_to_parquet_minio.py "/tmp/nise-${scale}"

    # Test 1: In-Memory Mode
    echo ""
    echo "3. Testing IN-MEMORY mode..."
    ./scripts/run_benchmark_simple.sh non-streaming > "${RESULTS_DIR}/${scale}_in-memory.log" 2>&1

    # Test 2: Streaming Mode
    echo ""
    echo "4. Testing STREAMING mode..."
    ./scripts/run_benchmark_simple.sh streaming > "${RESULTS_DIR}/${scale}_streaming.log" 2>&1

    # Extract metrics
    echo ""
    echo "5. Extracting metrics..."
    python3 scripts/analyze_benchmark_results.py "${RESULTS_DIR}" "${scale}"

    echo "✅ Completed: ${scale}"
    echo ""
done

# Generate comparison report
echo "=================================================================="
echo "Generating Comparison Report..."
echo "=================================================================="
python3 scripts/generate_comparison_report.py "${RESULTS_DIR}"

echo ""
echo "✅ ALL BENCHMARKS COMPLETE"
echo "Results: ${RESULTS_DIR}/COMPARISON_REPORT.md"
```

---

## Expected Outcomes

### Success Criteria
1. ✅ Both modes work correctly at all tested scales
2. ✅ Identify optimal `streaming_threshold_rows` value
3. ✅ Document memory vs speed trade-off
4. ✅ Provide clear guidance for production use
5. ✅ IQE tests pass in both modes

### Deliverables
1. **Benchmark Results**: Detailed metrics for each scale + mode
2. **Comparison Report**: Side-by-side analysis
3. **Configuration Recommendation**: When to enable streaming
4. **Updated Documentation**: Add streaming guidance to README

---

## Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| **Setup** | 30 min | Create comparison script, analysis tools |
| **Phase 1** | 10-15 min | Small-scale validation (small, medium, large) |
| **Phase 2** | 30-60 min | Crossover detection (large, xlarge, xxlarge) |
| **Phase 3** | 2-4 hours | Production scale (production-small, production-medium) |
| **Analysis** | 30 min | Generate comparison report |
| **Total** | **4-6 hours** | Complete streaming benchmark |

---

## After Benchmarks: Storage Implementation

Once streaming benchmarks complete, proceed with:

### 1. Storage Aggregator Implementation (4-6 hours)
- Create `src/aggregator_storage.py`
- Implement PVC/PV aggregation logic
- Add storage Parquet reader
- Integrate with main.py

### 2. Storage Testing (2-3 hours)
- Check if nise generates storage data
- Create storage test scenarios
- Validate against Trino (if available)

### 3. Final Benchmarks (1-2 hours)
- Run pod + storage combined
- Test streaming + storage
- Validate correctness

### Total Timeline: **~12-15 hours** for complete implementation

---

## Quick Start (Run Now)

### Option A: Quick Validation (Recommended First)
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
source venv/bin/activate

# Generate and test small scale only
./scripts/generate_nise_benchmark_data.sh small /tmp/nise-small
python3 scripts/csv_to_parquet_minio.py /tmp/nise-small

# Test in-memory
sed -i '' 's/use_streaming: true/use_streaming: false/' config/config.yaml
timeout 300 python3 -m src.main --truncate

# Test streaming
sed -i '' 's/use_streaming: false/use_streaming: true/' config/config.yaml
timeout 300 python3 -m src.main --truncate
```

### Option B: Full Comparison (Longer)
```bash
# I'll create the comparison script
# Then run: ./scripts/run_streaming_comparison.sh small medium large xlarge
```

---

## Ready to Proceed?

**Current Status**:
- ✅ Benchmark infrastructure exists
- ✅ 8 scales available (1K → 2M rows)
- ✅ Both streaming and in-memory modes working
- ✅ IQE validation passing

**Next Steps**:
1. ✅ Create streaming comparison script (I'll do this now)
2. ✅ Run Phase 1 benchmarks (small, medium, large) - ~15 min
3. ⏳ Run Phase 2 benchmarks (crossover detection) - ~1 hour
4. ⏳ Analyze results and document findings
5. ⏳ Implement storage aggregation
6. ⏳ Final validation with storage + streaming

**Shall I proceed with creating the comparison script and running Phase 1?**

