# Benchmark Script Fixes Applied

**Date**: November 21, 2024
**Status**: ✅ **FIXED** - Ready for re-run

---

## Issues Fixed

### ✅ Fix #1: Metadata Extraction
**Problem**: Script looked for non-existent `ocp-static-data.yml` file
**Solution**: Read from `metadata_${scale}.json` instead

**Before**:
```bash
export OCP_CLUSTER_ID=$(grep "cluster_id:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
export OCP_PROVIDER_UUID=$(grep "ocp_source_uuid:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
```

**After**:
```bash
METADATA_FILE="${DATA_DIR}/metadata_${scale}.json"
export OCP_CLUSTER_ID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['cluster_id'])")
export OCP_PROVIDER_UUID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['provider_uuid'])")
```

---

### ✅ Fix #2: Error Checking Added
**Problem**: Script continued silently when metadata extraction failed
**Solution**: Added validation checks

**Added**:
```bash
if [ ! -f "${METADATA_FILE}" ]; then
    echo "❌ ERROR: Metadata file not found"
    exit 1
fi

if [ -z "${OCP_CLUSTER_ID}" ] || [ -z "${OCP_PROVIDER_UUID}" ]; then
    echo "❌ ERROR: Failed to extract cluster ID or provider UUID"
    exit 1
fi
```

---

### ✅ Fix #3: Python Heredoc Arguments
**Problem**: Heredoc with `'EOF'` (quotes) + arguments caused syntax error
**Solution**: Use `python3 -` with proper argument passing

**Before**:
```bash
python3 << 'EOF'
...
f.write(f'**Generated**: {sys.argv[2]}\n\n')
...
EOF "${SUMMARY_FILE}" "$(date)"  # This doesn't work!
```

**After**:
```bash
python3 - "${SUMMARY_FILE}" "$(date)" << 'EOFPYTHON'
...
summary_file = sys.argv[1]
timestamp = sys.argv[2]
f.write(f'**Generated**: {timestamp}\n\n')
...
EOFPYTHON
```

---

## Changes Made

**File**: `scripts/run_streaming_comparison.sh`

1. Lines 82-105: Metadata extraction from JSON with error checking
2. Lines 198-220: Python heredoc with proper argument passing
3. Line 308: Updated EOF marker to EOFPYTHON

---

## Testing

### Manual Test (Quick)
```bash
# Test metadata extraction
./scripts/generate_nise_benchmark_data.sh small /tmp/test-fix
METADATA_FILE="/tmp/test-fix/metadata_small.json"
python3 -c "import json; print(json.load(open('${METADATA_FILE}')))"

# Should output JSON with cluster_id and provider_uuid
```

### Full Re-run
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
source venv/bin/activate

# Re-run Phase 1 benchmarks
./scripts/run_streaming_comparison.sh small medium large
```

---

## Expected Outcome

With fixes applied, benchmarks should:
- ✅ Extract metadata correctly
- ✅ Set environment variables properly
- ✅ Run POC aggregator successfully
- ✅ Capture timing and memory metrics
- ✅ Generate comparison report

---

## Ready to Re-run

**Status**: ✅ All fixes applied
**Next**: Re-run benchmarks
**ETA**: ~15 minutes for Phase 1 (small, medium, large)

---

*Fixes complete. Ready for benchmark re-run!*

