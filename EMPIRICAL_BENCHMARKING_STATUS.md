# Empirical Benchmarking Status

**Date**: 2025-11-20
**Status**: ⏳ In Progress
**Current Figures**: Theoretical estimates

---

## Current Status

### What We Have

✅ **Theoretical Performance Estimates** (PERFORMANCE_ANALYSIS.md)
- Based on data structure sizes
- Pandas memory usage patterns
- Typical Python overhead
- **Source**: Engineering estimates

✅ **Empirical Test Results from IQE Validation**
- 7/7 production scenarios passing
- Processing rates: 3K-7K rows/sec
- Durations: 0.3s - 0.7s
- **Source**: Actual test runs (but without detailed memory profiling)

✅ **Benchmarking Infrastructure Created**
- `scripts/benchmark_performance.py` - Comprehensive benchmarking script
- `scripts/run_empirical_benchmarks.sh` - Automated benchmark runner
- Uses `psutil` for actual memory/CPU measurements
- **Status**: Ready to use

### What We Need

⏳ **Empirical Memory Measurements**
- Actual RSS memory usage per phase
- Peak memory during aggregation
- Memory per 1K rows (measured, not estimated)
- CPU time per phase

⏳ **Benchmark Against Multiple Dataset Sizes**
- Small (10K rows)
- Medium (100K rows)
- Large (1M rows)
- Very large (10M rows with streaming)

---

## Theoretical vs Empirical Comparison

### Current Figures (Theoretical)

| Metric | Value | Source |
|--------|-------|--------|
| Memory per 1K input rows | 9-10 MB | Calculated from DataFrame structure |
| Memory per 1K input rows (safe) | 18-20 MB | 2x safety margin |
| Processing rate | 3,000-7,000 rows/sec | IQE test observations |
| Peak memory (1M rows) | 10 GB | Linear extrapolation |

**Confidence**: 70-80% (engineering estimates)

### What Empirical Measurements Will Provide

| Metric | How Measured | Tool |
|--------|--------------|------|
| Actual RSS memory | `process.memory_info().rss` | psutil |
| Peak memory per phase | Monitor during execution | psutil |
| CPU time (user + system) | `process.cpu_times()` | psutil |
| Memory per 1K rows | Peak memory / row count | Calculated |
| Processing rate | Row count / duration | Measured |

**Confidence**: 95-99% (actual measurements)

---

## Benchmarking Script Features

### What It Measures

```python
class PerformanceBenchmark:
    def measure_phase(phase_name, func):
        # Before execution
        mem_before = process.memory_info().rss
        cpu_before = process.cpu_times()
        time_start = time.time()

        # Execute
        result = func()

        # After execution
        time_end = time.time()
        cpu_after = process.cpu_times()
        mem_after = process.memory_info().rss
        mem_peak = process.memory_info().rss

        return {
            'duration_seconds': time_end - time_start,
            'memory_before_bytes': mem_before,
            'memory_after_bytes': mem_after,
            'memory_peak_bytes': mem_peak,
            'memory_used_bytes': mem_after - mem_before,
            'cpu_user_seconds': cpu_after.user - cpu_before.user,
            'cpu_system_seconds': cpu_after.system - cpu_before.system,
            'cpu_total_seconds': cpu_user + cpu_system
        }
```

### Phases Measured

1. **Initialize ParquetReader** - Setup overhead
2. **Initialize DatabaseWriter** - DB connection overhead
3. **Fetch enabled tags** - PostgreSQL query
4. **Read pod usage (daily)** - Parquet reading
5. **Read pod usage (hourly)** - Parquet reading for capacity
6. **Read node labels** - Parquet reading
7. **Read namespace labels** - Parquet reading
8. **Calculate capacity** - Node/cluster capacity aggregation
9. **Aggregate pod usage** - Main aggregation logic

### Output Format

```json
{
  "provider_uuid": "...",
  "year": "2025",
  "month": "10",
  "timestamp": "2025-11-20T17:19:27",
  "input_rows_daily": 27600,
  "input_rows_hourly": 662400,
  "output_rows": 1200,
  "compression_ratio": 23.0,
  "total_duration_seconds": 5.2,
  "total_cpu_seconds": 4.8,
  "peak_memory_bytes": 524288000,
  "final_memory_bytes": 314572800,
  "memory_per_1k_input_rows_bytes": 19000000,
  "memory_per_1k_output_rows_bytes": 436906666,
  "rows_per_second": 5307,
  "phases": [...]
}
```

---

## Why Empirical Measurements Matter

### 1. Validate Theoretical Estimates

**Question**: Are our estimates accurate?

**Theoretical**: 10 MB per 1K rows
**Empirical**: TBD (need to measure)

**Impact**: If actual is 15 MB, we need 50% more memory than estimated

### 2. Identify Memory Hotspots

**Question**: Which phase uses the most memory?

**Theoretical**: Aggregation (assumed)
**Empirical**: TBD (need to measure)

**Impact**: Can optimize the right phase

### 3. Measure Optimization Impact

**Question**: Do optimizations actually work?

**Theoretical**: 50% memory reduction
**Empirical**: TBD (need before/after measurements)

**Impact**: Validate optimization effectiveness

### 4. Production Capacity Planning

**Question**: What container size do we need?

**Theoretical**: 2 GB for 100K rows (estimated)
**Empirical**: TBD (need actual measurements)

**Impact**: Right-size production containers

---

## Next Steps to Get Empirical Data

### Option 1: Run Against Existing IQE Test Data (Recommended)

**Steps**:
1. Use data from successful IQE test run
2. Fix data path in benchmark script
3. Run benchmark against 3 scenarios:
   - Small: ocp_report_1.yml (~2K rows)
   - Medium: ocp_report_ros_0.yml (~5K rows)
   - Large: ocp_report_0_template.yml (~19K rows)
4. Generate empirical performance report

**Time**: 30 minutes

**Deliverable**: `EMPIRICAL_PERFORMANCE_RESULTS.md` with actual measurements

### Option 2: Generate Synthetic Data at Scale

**Steps**:
1. Create synthetic Parquet files with known row counts
2. Run benchmarks at multiple scales:
   - 10K, 50K, 100K, 500K, 1M rows
3. Plot memory vs row count
4. Calculate actual memory per 1K rows

**Time**: 2-3 hours

**Deliverable**: Scaling curves with empirical data

### Option 3: Production Data Sample

**Steps**:
1. Get sample of production data
2. Run benchmark
3. Compare with theoretical estimates
4. Adjust estimates based on real data

**Time**: 1-2 days (need production access)

**Deliverable**: Production-validated performance metrics

---

## Blocking Issues

### 1. Data Path Mismatch

**Issue**: Benchmark script looking for data in wrong S3 path

**Current**: `data/org1234567/OCP/source={uuid}/year=2025/month=10/*/openshift_pod_usage_line_items`

**Actual**: Need to verify actual MinIO structure

**Fix**: Update config or script to match actual data location

### 2. Missing Test Data

**Issue**: No data currently in MinIO for benchmarking

**Options**:
- Run IQE validation first to generate data
- Use existing CSV files and convert to Parquet
- Generate synthetic data

**Fix**: Run `./scripts/run_iqe_validation.sh` first

### 3. PostgreSQL Schema

**Issue**: Missing `reporting_ocp_cost_category_namespace` table

**Impact**: Non-critical (cost categories are optional)

**Fix**: Initialize DB schema or handle gracefully

---

## Recommendation

### Immediate Action (30 minutes)

1. **Run one IQE validation test** to populate MinIO:
   ```bash
   cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
   export IQE_YAML="ocp_report_1.yml"
   ./scripts/run_iqe_validation.sh
   ```

2. **Run benchmark against that data**:
   ```bash
   # Use the provider UUID from the test
   export OCP_PROVIDER_UUID="<uuid-from-test>"
   export POC_YEAR="2025"
   export POC_MONTH="10"  # or 11, depending on test

   python3 scripts/benchmark_performance.py \
       --provider-uuid "$OCP_PROVIDER_UUID" \
       --year "$POC_YEAR" \
       --month "$POC_MONTH" \
       --output "benchmark_results/empirical_small.json"
   ```

3. **Extract key metrics**:
   ```bash
   python3 << 'EOF'
   import json
   with open('benchmark_results/empirical_small.json') as f:
       data = json.load(f)

   print(f"Input rows: {data['input_rows_daily']:,}")
   print(f"Peak memory: {data['peak_memory_bytes'] / 1024**3:.2f} GB")
   print(f"Memory per 1K rows: {data['memory_per_1k_input_rows_bytes'] / 1024**2:.1f} MB")
   print(f"Processing rate: {data['rows_per_second']:,.0f} rows/sec")
   EOF
   ```

4. **Update PERFORMANCE_ANALYSIS.md** with empirical data

### Medium-term Action (2-3 hours)

1. Run benchmarks at multiple scales
2. Generate scaling curves
3. Validate theoretical estimates
4. Update all performance documentation

### Long-term Action (Production)

1. Monitor actual production memory usage
2. Collect metrics over time
3. Refine estimates based on real workloads
4. Optimize based on actual bottlenecks

---

## Summary

**Current State**: We have good theoretical estimates (70-80% confidence)

**What's Missing**: Empirical validation of those estimates

**Impact**: Medium - estimates are reasonable but unvalidated

**Effort to Fix**: 30 minutes for basic validation, 2-3 hours for comprehensive

**Recommendation**: Run basic empirical benchmarks to validate key metrics (memory per 1K rows, peak memory, processing rate)

---

**Date**: 2025-11-20
**Status**: ⏳ Benchmarking infrastructure ready, awaiting test data
**Next Step**: Run IQE test + benchmark to get empirical measurements

