# Comprehensive Benchmark Script - Issues Summary

**Status**: ⚠️ **Multiple issues identified - Not production ready**

## Issues Found

### 1. ✅ FIXED: Incorrect CSV-to-Parquet Arguments
**Problem**: Script called with named arguments instead of positional
```bash
# Wrong
python3 csv_to_parquet_minio.py --csv-dir /path --provider-uuid UUID

# Correct
export OCP_PROVIDER_UUID=UUID
python3 csv_to_parquet_minio.py /path
```

### 2. ✅ FIXED: Bash Compatibility
**Problem**: `${VAR^^}` not compatible with sh/zsh
```bash
# Wrong
echo "SCALE: ${SCALE^^}"

# Correct
echo "SCALE: $(echo ${SCALE} | tr '[:lower:]' '[:upper:]')"
```

### 3. ✅ FIXED: Python Boolean Values
**Problem**: bash `false` not Python `False`
```bash
# Wrong
USE_STREAMING="false"
python3 << EOF
config['use_streaming'] = ${USE_STREAMING}  # NameError: name 'false' is not defined
EOF

# Correct
USE_STREAMING="False"  # Python boolean
```

### 4. ✅ FIXED: Missing --truncate Argument
**Problem**: `benchmark_performance.py` doesn't accept `--truncate`
```bash
# Wrong
python3 benchmark_performance.py --truncate

# Correct
psql -c "TRUNCATE TABLE ..." # Do it manually before
python3 benchmark_performance.py
```

### 5. ⚠️ ONGOING: Missing Environment Variables
**Problem**: Config requires many environment variables

**Required variables**:
- S3_ENDPOINT
- S3_ACCESS_KEY
- S3_SECRET_KEY
- S3_BUCKET
- POSTGRES_HOST
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- POSTGRES_SCHEMA
- OCP_PROVIDER_UUID
- OCP_CLUSTER_ID
- OCP_CLUSTER_ALIAS
- OCP_YEAR
- OCP_MONTH
- ORG_ID

**Issue**: Complex interdependencies and timing issues

## Root Cause Analysis

The comprehensive benchmark script is **too complex** and tries to do too much:
1. Generate data with nise
2. Convert to Parquet
3. Upload to MinIO
4. Modify config files dynamically
5. Run benchmarks in two modes
6. Collect and aggregate results
7. Generate reports

This introduces many failure points and requires perfect environment setup.

## Recommended Approach

### Option 1: Use Existing IQE Tests (RECOMMENDED)

The IQE validation suite **already works perfectly**:
- ✅ 18/18 tests passing
- ✅ Validates streaming mode
- ✅ Checks correctness
- ✅ Tests different data sizes

**What's missing**: Memory/performance metrics

**Solution**: Enhance IQE validation to capture metrics

```bash
# This already works
./scripts/test_extended_iqe_scenarios.sh  # 18/18 passing

# Add memory tracking wrapper
./scripts/run_iqe_with_metrics.sh  # NEW: Wraps IQE tests with metrics
```

### Option 2: Simplified Manual Benchmarking

Instead of one complex script, use simple manual steps:

```bash
# 1. Generate data
./scripts/generate_nise_benchmark_data.sh medium /tmp/bench

# 2. Get UUID
UUID=$(jq -r '.provider_uuid' /tmp/bench/metadata_medium.json)

# 3. Convert and upload
export OCP_PROVIDER_UUID=$UUID ORG_ID=1234567
python3 scripts/csv_to_parquet_minio.py /tmp/bench

# 4. Set all env vars
export S3_ENDPOINT=http://localhost:9000
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
# ... (all required vars)

# 5. Run with metrics
/usr/bin/time -v python3 -m src.main --truncate

# 6. Compare with streaming off
# Edit config.yaml: use_streaming: false
/usr/bin/time -v python3 -m src.main --truncate
```

### Option 3: Fix Comprehensive Script (High Effort)

**Time required**: 2-4 hours
**Complexity**: High
**Risk**: Medium (many moving parts)

**Remaining issues to fix**:
1. Ensure all env vars exported in correct order
2. Handle config.yaml backup/restore properly
3. Add error recovery
4. Test each scale independently
5. Handle timeout scenarios
6. Fix matplotlib dependencies for charts

## What Actually Works Now

### ✅ Working Components

1. **IQE Validation Suite**
   - 18/18 scenarios passing
   - Tests streaming mode
   - Validates correctness
   ```bash
   ./scripts/test_extended_iqe_scenarios.sh
   ```

2. **Single-Scale Data Generation**
   - All scales generate correctly
   ```bash
   ./scripts/generate_nise_benchmark_data.sh {scale} /tmp/output
   ```

3. **CSV-to-Parquet Conversion**
   - Works when called correctly
   ```bash
   export OCP_PROVIDER_UUID=... ORG_ID=...
   python3 scripts/csv_to_parquet_minio.py /path/to/csv
   ```

4. **POC Aggregation**
   - Streaming and non-streaming both work
   ```bash
   python3 -m src.main --truncate
   ```

### ⚠️ Not Working

1. **Comprehensive Benchmark Script**
   - Too many interdependent issues
   - Needs significant refactoring

2. **Automated Metrics Collection**
   - `benchmark_performance.py` needs environment debugging
   - Complex config dependencies

## Immediate Action Items

### For Quick Benchmarking

Use the **manual approach** documented in `BENCHMARK_QUICKSTART.md`:

1. Generate one scale at a time
2. Manually export environment variables
3. Run with system monitoring tools:
   ```bash
   /usr/bin/time -l python3 -m src.main  # macOS
   /usr/bin/time -v python3 -m src.main  # Linux
   ```

### For Production Benchmarking

1. **Validate current state**
   ```bash
   # Confirm streaming still works
   ./scripts/test_extended_iqe_scenarios.sh
   ```

2. **Manual performance test**
   ```bash
   # Generate medium dataset
   ./scripts/generate_nise_benchmark_data.sh medium /tmp/bench

   # Time the aggregation
   time python3 -m src.main --truncate
   ```

3. **Document results** manually in a spreadsheet or markdown

## Recommendation

**Don't spend more time debugging the comprehensive benchmark script.**

Instead:

1. ✅ **Confirm Phase 1 works** - IQE tests (DONE - 18/18 passing)
2. ✅ **Confirm streaming works** - IQE tests use streaming (DONE)
3. ⏭️ **Manual benchmark** - Test 2-3 scales manually with `time` command
4. ⏭️ **Document findings** - Create simple comparison table
5. ⏭️ **Move to Phase 2** - Parallel processing, not complex automation

## Simple Benchmark Plan

```bash
# Scale 1: Small (~1K rows)
./scripts/generate_nise_benchmark_data.sh small /tmp/bench-small
# ... convert, time aggregation, record results

# Scale 2: Large (~50K rows)
./scripts/generate_nise_benchmark_data.sh large /tmp/bench-large
# ... convert, time aggregation, record results

# Scale 3: XLarge (~100K rows)
./scripts/generate_nise_benchmark_data.sh xlarge /tmp/bench-xlarge
# ... convert, time aggregation, record results

# Record in spreadsheet:
# Scale | Rows | Time | Peak Memory | Notes
# small | 1K   | 2s   | 45 MB      | Fast
# large | 50K  | 8s   | 120 MB     | Good
# xlarge| 100K | 15s  | 180 MB     | Excellent
```

---

**Bottom Line**: The comprehensive benchmark script has too many issues. Use manual benchmarking or enhance the existing IQE tests instead.

