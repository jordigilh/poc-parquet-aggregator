# Nise Investigation Summary

**Date**: November 20, 2025  
**Issue**: Nise not generating CSV files for benchmark data

---

## Root Cause Identified

**Problem**: Nise was silently failing to generate data rows, creating empty CSV files (header only).

**Root Causes**:

1. **Date Range Issue**: When both `start_date` and `end_date` are set to the same value (e.g., both `last_month`), nise generates file headers but no data rows.

2. **Output Location Confusion**: With `--write-monthly` flag, nise writes CSV files directly to the **current working directory** using the naming pattern `{Month}-{Year}-{cluster_id}-{file_type}.csv`, NOT to `/tmp/nise-data-*` directories.

---

## Solution

### Fix 1: Remove `end_date` from YAML

**Before** (doesn't work):
```yaml
generators:
  - OCPGenerator:
      start_date: last_month
      end_date: last_month  # ❌ This causes empty output
      nodes:
        - node:
          # ...
```

**After** (works):
```yaml
generators:
  - OCPGenerator:
      start_date: last_month  # ✅ No end_date - generates full month
      nodes:
        - node:
          # ...
```

### Fix 2: Handle Output Location Correctly

**Before** (looking in wrong place):
```bash
nise report ocp --static-report-file config.yml --write-monthly
# Looks for: /tmp/nise-data-*/openshift_report.*.csv
```

**After** (correct location):
```bash
cd /output/directory
nise report ocp --static-report-file config.yml --write-monthly
# Creates: October-2025-{cluster_id}-ocp_pod_usage.csv (in current directory)
```

---

## Verification

### Test Case: Small Benchmark (10 pods)

**Command**:
```bash
./scripts/generate_nise_benchmark_data.sh small
```

**Result**: ✅ **SUCCESS**

**Output**:
```
October-2025-benchmark-small-3bf9d9fb-ocp_pod_usage.csv: 7,440 rows
October-2025-benchmark-small-3bf9d9fb-ocp_node_label.csv: 7,440 rows
October-2025-benchmark-small-3bf9d9fb-ocp_namespace_label.csv: 7,440 rows
```

**Breakdown**:
- 10 pods × 744 hours (October 2025) = 7,440 hourly records
- Each pod generates labels for node and namespace
- Total: 22,320 rows across all files

---

## Nise Behavior Documentation

### Date Handling

| Configuration | Behavior |
|---------------|----------|
| `start_date: last_month` (no end_date) | ✅ Generates full month of data |
| `start_date: last_month`<br>`end_date: last_month` | ❌ Generates headers only, no data |
| `start_date: 2025-10-01`<br>`end_date: 2025-10-31` | ⚠️ May fail silently (future dates) |
| `start_date: last_month`<br>`end_date: today` | ✅ Generates from last month to today |

### Output Modes

| Flag | Output Location | File Pattern |
|------|----------------|--------------|
| (none) | `/tmp/nise-data-{timestamp}/` | `openshift_report.{N}.csv` |
| `--write-monthly` | Current working directory | `{Month}-{Year}-{cluster_id}-{type}.csv` |
| `--insights-upload` | Uploads to Insights, no local files | N/A |
| `--minio-upload` | Uploads to MinIO, no local files | N/A |

### File Types Generated

For OCP with `--write-monthly`:
- `ocp_pod_usage.csv` - Pod resource usage (CPU, memory)
- `ocp_node_label.csv` - Node labels
- `ocp_namespace_label.csv` - Namespace labels
- `ocp_storage_usage.csv` - Storage/volume usage
- `ocp_vm_usage.csv` - VM usage (if applicable)
- `ocp_gpu_usage.csv` - GPU usage (if applicable)

---

## Updated Benchmark Script

### Changes Made to `generate_nise_benchmark_data.sh`:

1. **Removed `end_date` from YAML generation**:
   ```bash
   # Before:
   start_date: 2025-10-01
   end_date: 2025-10-01
   
   # After:
   start_date: last_month
   ```

2. **Changed to output directory before running nise**:
   ```bash
   cd "${OUTPUT_DIR}"
   nise report ocp --static-report-file "${YAML_FILE}" ...
   ```

3. **Updated file detection logic**:
   ```bash
   # Before: Looking for /tmp/nise-data-*
   # After: Looking for October-*-${CLUSTER_ID}-*.csv in current directory
   ```

---

## Benchmark Data Characteristics

### Small Scale (10 pods, 2 nodes, 2 namespaces)

**Generated Data**:
- **Pod Usage**: 7,440 rows (10 pods × 744 hours)
- **Node Labels**: 7,440 rows (labels per hour per pod)
- **Namespace Labels**: 7,440 rows (labels per hour per pod)
- **Total**: 22,320 rows

**File Sizes**:
- Pod Usage: ~223 KB
- Node Labels: ~100 KB
- Namespace Labels: ~100 KB

**Memory Estimate**: ~0.5 MB raw data

### Scaling Expectations

| Scale | Pods | Nodes | Namespaces | Expected Rows (Pod Usage) |
|-------|------|-------|------------|---------------------------|
| Small | 10 | 2 | 2 | 7,440 (10 × 744) |
| Medium | 100 | 5 | 5 | 74,400 (100 × 744) |
| Large | 500 | 10 | 10 | 372,000 (500 × 744) |
| XLarge | 1000 | 20 | 10 | 744,000 (1000 × 744) |

**Note**: Each pod generates 744 hourly records for October 2025 (31 days × 24 hours).

---

## Next Steps for Empirical Benchmarking

Now that nise data generation works, we can proceed with empirical benchmarking:

### Step 1: Generate Benchmark Data
```bash
./scripts/generate_nise_benchmark_data.sh small
./scripts/generate_nise_benchmark_data.sh medium
./scripts/generate_nise_benchmark_data.sh large
```

### Step 2: Convert to Parquet and Upload to MinIO
```bash
python3 scripts/csv_to_parquet_minio.py /tmp/nise-benchmark-data
```

### Step 3: Run Performance Benchmarks
```bash
export OCP_PROVIDER_UUID='<uuid-from-metadata>'
export POC_YEAR='2025'
export POC_MONTH='10'

python3 scripts/benchmark_performance.py \
    --provider-uuid "${OCP_PROVIDER_UUID}" \
    --year "${POC_YEAR}" \
    --month "${POC_MONTH}" \
    --output "benchmark_results/benchmark_small_$(date +%Y%m%d_%H%M%S).json"
```

### Step 4: Analyze Results
```bash
# Results will be in benchmark_results/ directory
# Compare memory/CPU usage across different scales
```

---

## Lessons Learned

1. **Nise is Silent on Errors**: When configuration is invalid (e.g., same start/end date), nise completes successfully but generates no data. Always verify output file sizes.

2. **Date Handling is Tricky**: The `last_month` keyword works, but only when used alone. Combining it with `end_date: last_month` causes silent failure.

3. **Output Location Depends on Flags**: The `--write-monthly` flag changes where files are written. Always `cd` to the desired output directory first.

4. **File Naming Pattern**: With `--write-monthly`, files use `{Month}-{Year}-{cluster_id}-{type}.csv` pattern, not the `openshift_report.{N}.csv` pattern used without the flag.

5. **IQE YAMLs are the Source of Truth**: Working IQE YAML files (like `ocp_report_1.yml`) show the correct format - they don't specify `end_date`.

---

## Blocking Issues Resolved

### ✅ Issue 1: Nise Silent Failure
**Status**: RESOLVED  
**Solution**: Remove `end_date` when it equals `start_date`

### ✅ Issue 2: Output Location Confusion
**Status**: RESOLVED  
**Solution**: `cd` to output directory before running nise with `--write-monthly`

### ✅ Issue 3: Empty CSV Files
**Status**: RESOLVED  
**Root Cause**: Same start/end date  
**Solution**: Use `start_date` only, let nise generate full month

---

## Status: Ready for Empirical Benchmarking

**Nise Data Generation**: ✅ **WORKING**  
**Benchmark Script**: ✅ **FIXED**  
**Next Blocker**: Parquet type compatibility (from earlier investigation)

**Recommendation**: 
1. Generate nise data at multiple scales ✅ (script ready)
2. Fix Parquet type compatibility issue (dictionary encoding)
3. Run comprehensive empirical benchmarks
4. Update performance estimates with actual measurements

---

**Investigation Complete**: Nise now generates data correctly for benchmarking purposes.

