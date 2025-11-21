# Validation Date Mismatch - Root Cause Analysis

**Status**: 🔍 TRIAGED - Fix Identified
**Severity**: Medium (doesn't affect performance measurement, but validation fails)

---

## 🐛 The Problem

Validation is failing with date mismatches:

```
Expected rows: 2025-11-01 (November)
Actual rows:   2025-10-01 (October)
```

**Impact**:
- ✅ Performance benchmarks completing successfully
- ✅ Aggregation working correctly
- ❌ Correctness validation failing
- ❌ Can't confirm data accuracy

---

## 🔍 Root Cause

### Issue #1: Validation Query Doesn't Filter by Date

**File**: `scripts/validate_benchmark_correctness.py`

**Current Code** (line 117-133):
```python
def query_poc_results(cluster_id, year, month):
    query = f"""
        SELECT
            usage_start,
            namespace,
            node,
            SUM(pod_usage_cpu_core_hours) as cpu_usage_core_hours,
            ...
        FROM {schema}.reporting_ocpusagelineitem_daily_summary
        WHERE cluster_id = %s        <-- ❌ NO DATE FILTER!
        GROUP BY usage_start, namespace, node
        ORDER BY usage_start, namespace, node
    """

    actual = pd.read_sql(query, conn, params=[cluster_id])
```

**Problem**: The query receives `year` and `month` parameters but **doesn't use them**!

**Result**: Query returns ALL data for that cluster_id, including:
- Old data from previous runs (November)
- New data from current run (October)
- Data accumulates across runs

### Issue #2: Metadata Missing year/month Fields

**File**: `nise_benchmark_data/metadata_small.json`

**Current Structure**:
```json
{
  "scale": "small",
  "cluster_id": "benchmark-small-fab13fc0",
  "provider_uuid": "fab13fc0-942e-429f-9a9e-e4d4f0eed848",
  "pods": 10,
  ...
  // ❌ NO 'year' field
  // ❌ NO 'month' field
}
```

**Impact**: When validation script reads metadata, it defaults to:
```python
year = metadata.get('year', '2025')   # Defaults to '2025'
month = metadata.get('month', '10')   # Defaults to '10'
```

But these defaults aren't actually helping because the query doesn't use them anyway!

### Issue #3: --truncate Not Preventing Accumulation

**File**: `scripts/run_streaming_only_benchmark.sh` (line 169)

```bash
python3 -m src.main --truncate
```

**Expected**: Should clear the table before each run
**Reality**: Different cluster_ids for each scale/run means data accumulates

Example:
- Run 1: benchmark-small-9626013c → writes data → validation queries ALL data
- Run 2: benchmark-small-fab13fc0 → writes MORE data → validation queries ALL data (both runs!)

---

## 📊 Why Validation Shows November Data

Looking at the error output:
```
Expected (from CSV): 2025-10-01 (October - current nise data)
Actual (from PostgreSQL): 2025-11-01 (November - old data from previous runs)
```

**Explanation**:
1. Previous benchmark runs generated November data (using different cluster IDs)
2. That data is still in PostgreSQL
3. Current run generates October data (with --truncate clearing for current cluster only)
4. Validation query retrieves BOTH October and November data (no date filter)
5. Mismatch occurs

---

## ✅ The Fix

### Fix #1: Add Date Filter to Validation Query (REQUIRED)

**File**: `scripts/validate_benchmark_correctness.py`

**Change**:
```python
def query_poc_results(cluster_id, year, month):
    query = f"""
        SELECT
            usage_start,
            namespace,
            node,
            SUM(pod_usage_cpu_core_hours) as cpu_usage_core_hours,
            SUM(pod_request_cpu_core_hours) as cpu_request_core_hours,
            SUM(pod_limit_cpu_core_hours) as cpu_limit_core_hours,
            SUM(pod_usage_memory_gigabyte_hours) as memory_usage_gb_hours,
            SUM(pod_request_memory_gigabyte_hours) as memory_request_gb_hours,
            SUM(pod_limit_memory_gigabyte_hours) as memory_limit_gb_hours,
            COUNT(*) as row_count
        FROM {schema}.reporting_ocpusagelineitem_daily_summary
        WHERE cluster_id = %s
          AND EXTRACT(YEAR FROM usage_start) = %s    <-- ADD THIS
          AND EXTRACT(MONTH FROM usage_start) = %s   <-- ADD THIS
        GROUP BY usage_start, namespace, node
        ORDER BY usage_start, namespace, node
    """

    actual = pd.read_sql(query, conn, params=[cluster_id, int(year), int(month)])  # ADD year, month params
```

### Fix #2: Add year/month to Metadata (OPTIONAL)

**File**: `scripts/generate_nise_benchmark_data.sh`

**Add to metadata**:
```bash
cat > "$OUTPUT_DIR/metadata_${SCALE}.json" << EOF
{
  "scale": "$SCALE",
  "cluster_id": "$CLUSTER_ID",
  "provider_uuid": "$PROVIDER_UUID",
  "year": "2025",     <-- ADD THIS
  "month": "10",      <-- ADD THIS
  ...
}
EOF
```

### Fix #3: Pass year/month to Validation (REQUIRED)

**File**: `scripts/run_streaming_only_benchmark.sh`

**Change**:
```bash
# Current (WRONG):
python3 "$SCRIPT_DIR/validate_benchmark_correctness.py" "$NISE_DATA_DIR" "$OCP_CLUSTER_ID" "org1234567"

# Fixed (CORRECT):
python3 "$SCRIPT_DIR/validate_benchmark_correctness.py" "$NISE_DATA_DIR" "$OCP_CLUSTER_ID" "2025" "10"
```

---

## 🎯 Implementation Priority

### Critical (Must Fix)
1. ✅ **Add date filter to validation query** - Prevents comparing wrong months
2. ✅ **Pass year/month to validation script** - Ensures correct parameters

### Optional (Nice to Have)
3. ⏳ **Add year/month to metadata** - Makes it easier to track what data was generated
4. ⏳ **Clear PostgreSQL before benchmark suite** - Prevents data accumulation

---

## 📝 Expected Outcome After Fix

```
✅ VALIDATION PASSED
   Comparing: 2025-10 (both CSV and PostgreSQL)
   Matched rows: 100%
   All metrics within 1% tolerance
```

---

## 🚀 Action Plan

1. ✅ Fix validation query to filter by year/month
2. ✅ Fix benchmark script to pass year/month arguments
3. ✅ Test with one scale to confirm fix
4. ✅ Let current benchmark complete (performance data still valid)
5. ✅ Re-run validation separately after fixes

---

**Status**: Ready to implement fix. Current benchmark can continue (performance measurement unaffected).

