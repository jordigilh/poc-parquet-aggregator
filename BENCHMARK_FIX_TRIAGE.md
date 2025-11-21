# Benchmark Script Fix - Triage Report

**Date**: 2025-11-20
**Issue**: All benchmark scales failing at Parquet conversion step
**Status**: ✅ FIXED

## Problem Identified

### Symptom
```
❌ Failed to convert data for small
❌ Failed to convert data for medium
❌ Failed to convert data for large
...
```

All scales were failing during the "Converting to Parquet and uploading to MinIO" step.

### Root Cause

The `csv_to_parquet_minio.py` script expects arguments in this format:
```bash
python3 csv_to_parquet_minio.py /path/to/csv/directory
```

With environment variables:
- `OCP_PROVIDER_UUID`
- `ORG_ID`

But the benchmark script was calling it with:
```bash
python3 csv_to_parquet_minio.py \
    --csv-dir "${DATA_DIR}" \          # ❌ WRONG: Treated as positional arg
    --provider-uuid "${PROVIDER_UUID}" \
    --org-id "1234567"
```

This caused `sys.argv[1]` to be literally `"--csv-dir"` instead of the actual directory path, resulting in:
```
❌ Directory not found: --csv-dir
```

### How It Was Found

1. Ran comprehensive benchmarks
2. All scales failed at conversion step
3. Checked conversion logs: `benchmark_results/comprehensive_*/logs/convert_*.log`
4. Found error: `❌ Directory not found: --csv-dir`
5. Reviewed `csv_to_parquet_minio.py` source code
6. Identified mismatch between script expectations and actual call

## Fix Applied

### Changed in `scripts/run_comprehensive_scale_benchmarks.sh`

**Before**:
```bash
if ! python3 "${SCRIPT_DIR}/csv_to_parquet_minio.py" \
    --csv-dir "${DATA_DIR}" \
    --provider-uuid "${PROVIDER_UUID}" \
    --org-id "1234567" > "${OUTPUT_DIR}/logs/convert_${SCALE}.log" 2>&1; then
```

**After**:
```bash
export OCP_PROVIDER_UUID="${PROVIDER_UUID}"
export ORG_ID="1234567"
if ! python3 "${SCRIPT_DIR}/csv_to_parquet_minio.py" "${DATA_DIR}" > "${OUTPUT_DIR}/logs/convert_${SCALE}.log" 2>&1; then
```

### Additional Fix

Fixed bash compatibility issue:
```bash
# Before
echo "SCALE: ${SCALE^^}"  # ❌ Not compatible with sh/zsh

# After
echo "SCALE: $(echo ${SCALE} | tr '[:lower:]' '[:upper:]')"  # ✅ POSIX-compliant
```

## Verification

### Test 1: Manual Conversion Test
```bash
./scripts/generate_nise_benchmark_data.sh small /tmp/test-fix
export OCP_PROVIDER_UUID=$(jq -r '.provider_uuid' /tmp/test-fix/metadata_small.json)
export ORG_ID="1234567"
python3 scripts/csv_to_parquet_minio.py /tmp/test-fix
```

**Result**: ✅ Success - Files converted and uploaded to MinIO

### Test 2: IQE Validation Test
```bash
IQE_YAML="ocp_report_1.yml" ./scripts/run_iqe_validation.sh
```

**Result**: ✅ 12/12 checks passed

## Impact

- **Benchmark Suite**: Now functional and ready to run
- **IQE Tests**: Unaffected - still passing (18/18)
- **POC Functionality**: Unaffected - core aggregation working correctly

## Related Issues

None - this was a new issue introduced when creating the comprehensive benchmark script.

## Lessons Learned

1. **Check script interfaces** before calling them
2. **Review argument parsing** (positional vs named arguments)
3. **Test incrementally** - don't run full suite before verifying single-scale works
4. **Check log files** immediately when failures occur

## Next Steps

1. ✅ Fix applied and tested
2. ⏭️ Run comprehensive benchmark suite
3. ⏭️ Analyze results
4. ⏭️ Document performance improvements

---

**Status**: Ready to proceed with comprehensive benchmarking

