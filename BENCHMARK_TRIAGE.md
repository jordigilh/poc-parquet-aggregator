# Benchmark Script Triage - Errors Found

**Date**: November 21, 2024
**Script**: `scripts/run_streaming_comparison.sh`
**Status**: 🔴 **FAILED** - Multiple issues found

---

## Errors Identified

### Error #1: Missing Metadata File ❌
**Location**: Line 83-84
**Issue**:
```bash
export OCP_CLUSTER_ID=$(grep "cluster_id:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
export OCP_PROVIDER_UUID=$(grep "ocp_source_uuid:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
```

**Problem**:
- Script looks for `ocp-static-data.yml`
- But `generate_nise_benchmark_data.sh` creates `benchmark_${SCALE}.yml` (not `ocp-static-data.yml`)
- This is a **nise generator config**, not a metadata file with cluster_id/provider_uuid

**Result**:
```
grep: /tmp/nise-small-20251121_084159/ocp-static-data.yml: No such file or directory
   Cluster ID:
   Provider UUID:
```

**Impact**: Empty environment variables → POC can't find data in MinIO → All tests fail

---

### Error #2: Python Syntax Error ❌
**Location**: Line 213
**Issue**:
```bash
./scripts/run_streaming_comparison.sh: line 213: syntax error near unexpected token `'status','
```

**Problem**: Python heredoc has incorrect quotes in CSV header line

**Impact**: Report generation fails at the end

---

### Error #3: All Tests Failed ❌
**Consequence of Error #1**

**Log Output**:
```
3️⃣  Testing IN-MEMORY mode...
   Configuring...
✓ In-memory mode configured
   Running benchmark...
   ❌ FAILED (timeout or error)

4️⃣  Testing STREAMING mode...
   Configuring...
✓ Streaming mode configured
   Running benchmark...
   ❌ FAILED (timeout or error)
```

**Root Cause**: Empty `OCP_CLUSTER_ID` and `OCP_PROVIDER_UUID` environment variables

---

## Root Cause Analysis

### The Metadata Problem

**What Happens**:
1. ✅ `generate_nise_benchmark_data.sh` runs successfully
2. ✅ Creates CSV files and uploads to MinIO
3. ✅ Prints metadata to console:
   ```
   Provider UUID: 9c0e4340-e356-40b1-a009-60b75b604082
   Cluster ID: benchmark-small-9c0e4340
   ```
4. ❌ But saves to `metadata_${SCALE}.json` (JSON format)
5. ❌ Script looks for `ocp-static-data.yml` (YAML format, doesn't exist)
6. ❌ grep fails silently, exports empty variables
7. ❌ POC tries to read from MinIO with empty provider_uuid → fails

**The Mismatch**:
- `generate_nise_benchmark_data.sh` outputs: `metadata_small.json`
- `run_streaming_comparison.sh` expects: `ocp-static-data.yml`

---

## Fixes Required

### Fix #1: Extract Metadata from JSON ✅
**Replace** lines 83-87:
```bash
# BROKEN:
export OCP_CLUSTER_ID=$(grep "cluster_id:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
export OCP_PROVIDER_UUID=$(grep "ocp_source_uuid:" "${DATA_DIR}/ocp-static-data.yml" | awk '{print $2}')
```

**With**:
```bash
# FIXED:
METADATA_FILE="${DATA_DIR}/metadata_${scale}.json"
export OCP_CLUSTER_ID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['cluster_id'])")
export OCP_PROVIDER_UUID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['provider_uuid'])")
```

---

### Fix #2: Fix Python Syntax Error ✅
**Problem**: Line 213 has mismatched quotes

**Find** the line with:
```python
echo "scale,mode,status,duration_seconds,peak_memory_mb,input_rows,output_rows" > "${SUMMARY_FILE}"
```

**Replace** the Python heredoc section (lines ~168-213) to properly escape quotes

---

### Fix #3: Add Error Checking ✅
**Add** after metadata extraction:
```bash
if [ -z "${OCP_CLUSTER_ID}" ] || [ -z "${OCP_PROVIDER_UUID}" ]; then
    echo "❌ ERROR: Failed to extract cluster ID or provider UUID"
    echo "   Metadata file: ${METADATA_FILE}"
    echo "   Cluster ID: ${OCP_CLUSTER_ID}"
    echo "   Provider UUID: ${OCP_PROVIDER_UUID}"
    exit 1
fi
```

---

## Quick Manual Test

To verify the fix works:

```bash
# Generate test data
./scripts/generate_nise_benchmark_data.sh small /tmp/test-metadata

# Check what files were created
ls -la /tmp/test-metadata/

# Extract metadata
METADATA_FILE="/tmp/test-metadata/metadata_small.json"
OCP_CLUSTER_ID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['cluster_id'])")
OCP_PROVIDER_UUID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['provider_uuid'])")

echo "Cluster ID: ${OCP_CLUSTER_ID}"
echo "Provider UUID: ${OCP_PROVIDER_UUID}"

# Should print actual values, not empty
```

---

## Impact Assessment

### What Failed
- ❌ All 6 benchmark runs (3 scales × 2 modes)
- ❌ No performance data collected
- ❌ No comparison report generated

### What Still Works
- ✅ Nise data generation
- ✅ CSV to Parquet conversion
- ✅ MinIO upload
- ✅ Pod aggregation itself (when env vars are correct)

### Time Lost
- ~10-15 minutes for failed benchmark run
- Need to re-run after fixes

---

## Next Steps

1. ✅ Fix the script (I'll do this now)
2. ✅ Test metadata extraction manually
3. ✅ Re-run Phase 1 benchmarks
4. ✅ Monitor for success

---

*Triage complete. Fixes in progress...*

