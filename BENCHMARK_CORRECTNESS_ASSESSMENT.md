# Benchmark Correctness Validation Assessment

**Date**: November 21, 2024
**Assessment Type**: Confidence in Data Correctness
**Confidence Level**: 🔴 **LOW** (Performance only, no correctness validation)

---

## 🎯 Executive Summary

**Current State**: The benchmark script validates PERFORMANCE but NOT CORRECTNESS.

| Aspect | Status | Confidence |
|--------|--------|------------|
| **POC runs successfully** | ✅ Checked | HIGH |
| **Performance metrics captured** | ✅ Checked | HIGH |
| **Row counts match** | ✅ Checked | MEDIUM |
| **Aggregation values are correct** | ❌ **NOT CHECKED** | 🔴 **NONE** |
| **Results match expectations** | ❌ **NOT CHECKED** | 🔴 **NONE** |

---

## 📊 What the Benchmark DOES Check

### ✅ Functional Validation (Exit Code)
```bash
if /usr/bin/time -l python3 -m src.main --truncate \
    > "${RESULTS_DIR}/${scale}_in-memory.log" 2>&1; then
    echo "   ✅ SUCCESS"
else
    echo "   ❌ FAILED"
    exit 1
fi
```

**What this validates**:
- POC runs without crashing
- No Python exceptions
- Database writes succeed
- S3 reads succeed

**What this DOESN'T validate**:
- ❌ Are the aggregated values correct?
- ❌ Do CPU/memory metrics match expected values?
- ❌ Are capacity calculations accurate?
- ❌ Is label merging working correctly?

---

### ✅ Performance Metrics
```bash
PEAK_MEM=$(grep "maximum resident set size" ... | awk '{print $1/1024/1024}')
INPUT_ROWS=$(grep "input_rows=" ...)
OUTPUT_ROWS=$(grep "output_rows=" ...)
DURATION=$((END_TIME - START_TIME))
```

**What this validates**:
- Time taken
- Memory used
- Row counts (input → output)

**What this DOESN'T validate**:
- ❌ Are those output rows correct?
- ❌ Do the values in PostgreSQL match expectations?
- ❌ Is the aggregation logic producing accurate results?

---

## ❌ What the Benchmark DOESN'T Check

### 1. Data Correctness
**Missing**: Comparison against expected values

The benchmark generates nise data but:
- ❌ Doesn't check if PostgreSQL values match nise expectations
- ❌ Doesn't validate CPU/memory aggregations
- ❌ Doesn't verify capacity calculations
- ❌ Doesn't check label merging accuracy

### 2. IQE Validation
**Missing**: Integration with IQE test suite

The IQE validation suite DOES check correctness:
```bash
# IQE validation (NOT in benchmark script)
python3 scripts/validate_against_iqe.py

# Checks:
- Reads YAML expectations
- Queries PostgreSQL results
- Compares values
- Reports differences
- Fails if mismatch
```

**But**: The benchmark script doesn't call this!

---

## 🔍 Gap Analysis

### Scenario: Broken Aggregation Logic

**Hypothetical Bug**: CPU usage calculation is off by 2x

**Current Benchmark Result**:
```
✅ SUCCESS (5.2s, 45.3 MB peak)
Input: 12,370 rows → Output: 2,046 rows
```

**What user sees**: ✅ All tests pass, great performance!

**Reality**: ❌ All CPU values in PostgreSQL are WRONG (2x too high)

**Why benchmark didn't catch it**: Only checks that POC runs, not that values are correct.

---

## 📈 Confidence Assessment by Metric

| Metric | Benchmark Validates | Confidence | Risk |
|--------|---------------------|------------|------|
| **Functional** | ✅ Exit code 0 | HIGH | LOW - we know it runs |
| **Performance** | ✅ Time, memory | HIGH | LOW - accurate metrics |
| **Row Counts** | ✅ Input/output | MEDIUM | MEDIUM - counts don't guarantee correctness |
| **CPU Aggregation** | ❌ Not validated | 🔴 **NONE** | 🔴 **HIGH - Could be wrong** |
| **Memory Aggregation** | ❌ Not validated | 🔴 **NONE** | 🔴 **HIGH - Could be wrong** |
| **Capacity Calculation** | ❌ Not validated | 🔴 **NONE** | 🔴 **HIGH - Could be wrong** |
| **Label Merging** | ❌ Not validated | 🔴 **NONE** | 🔴 **HIGH - Could be wrong** |
| **1:1 Trino Parity** | ❌ Not validated | 🔴 **NONE** | 🔴 **HIGH - Unknown if accurate** |

---

## ✅ What We DO Know is Correct

### From IQE Validation (Separate Test Suite)
The IQE validation suite (18 tests) DOES validate correctness:

```
✅ All 18 IQE scenarios passing (64/64 checks)
✅ PostgreSQL values match YAML expectations
✅ CPU aggregations correct
✅ Memory aggregations correct
✅ Capacity calculations correct
✅ Label merging correct
```

**Confidence**: 🟢 **HIGH** for correctness (based on IQE tests)

**But**: IQE tests use DIFFERENT data than benchmarks:
- IQE: Pre-defined test scenarios (27K rows)
- Benchmarks: Nise-generated data (1K-2M rows)

**Question**: Do benchmarks produce correct results at scale?
**Answer**: 🟡 **UNKNOWN** - not validated

---

## 🚨 Risk Assessment

### High Risk Scenarios

1. **Aggregation Bug at Scale**
   - IQE tests work (27K rows)
   - Benchmark tests "pass" (run successfully)
   - But: Aggregation wrong at 100K+ rows
   - **Detection**: ❌ Would NOT be caught

2. **Label Processing Error**
   - Works with IQE label patterns
   - Fails with nise-generated label patterns
   - Benchmark shows "success"
   - **Detection**: ❌ Would NOT be caught

3. **Capacity Calculation Drift**
   - Different node configurations in nise data
   - Capacity formula produces wrong values
   - Benchmark shows "success" (data written)
   - **Detection**: ❌ Would NOT be caught

4. **Performance Regression Masks Correctness**
   - Streaming mode is 10% slower (expected)
   - But: Also produces slightly different values (bug!)
   - Benchmark shows time difference only
   - **Detection**: ❌ Would NOT be caught

---

## 💡 Recommendations

### 1. Add IQE Validation to Benchmark (HIGH PRIORITY)

**Modify**: `run_streaming_comparison.sh`

**Add after each test**:
```bash
# Step 3: Test IN-MEMORY mode
if /usr/bin/time -l python3 -m src.main --truncate \
    > "${RESULTS_DIR}/${scale}_in-memory.log" 2>&1; then

    # ✅ NEW: Validate correctness
    echo "   Validating correctness..."
    if python3 scripts/validate_against_iqe.py --data-dir "/tmp/nise-${scale}-${TIMESTAMP}" \
        > "${RESULTS_DIR}/${scale}_in-memory_validation.log" 2>&1; then
        echo "   ✅ CORRECTNESS VALIDATED"
        VALIDATION_STATUS="PASS"
    else
        echo "   ❌ CORRECTNESS VALIDATION FAILED"
        tail -20 "${RESULTS_DIR}/${scale}_in-memory_validation.log"
        exit 1  # FAIL-FAST on incorrect results
    fi

    # Record success with validation
    echo "${scale},in-memory,SUCCESS,${DURATION},${PEAK_MEM},${INPUT_ROWS},${OUTPUT_ROWS},${VALIDATION_STATUS}" >> "${SUMMARY_FILE}"
else
    # Functional failure
    exit 1
fi
```

**Benefits**:
- ✅ Catches correctness bugs
- ✅ Validates at multiple scales
- ✅ Ensures streaming and in-memory produce same results
- ✅ Fail-fast on bad data

---

### 2. Create Scale-Specific Expected Values (MEDIUM PRIORITY)

**Problem**: IQE validation expects specific YAML files

**Solution**: Generate expected values from nise metadata

```python
# scripts/generate_expected_values_from_nise.py
def generate_expectations(nise_metadata, nise_csv_files):
    """
    Calculate expected aggregation values from nise raw data.
    Compare POC output against these expectations.
    """
    # Read nise CSV
    pod_usage = pd.read_csv(nise_csv_files['pod_usage'])

    # Calculate expected aggregates
    expected = pod_usage.groupby(['namespace', 'node']).agg({
        'pod_usage_cpu_core_hours': 'sum',
        'pod_request_cpu_core_hours': 'sum',
        # ... etc
    })

    # Compare against PostgreSQL
    actual = query_postgres("SELECT * FROM summary WHERE ...")

    # Validate
    assert_almost_equal(expected, actual, decimal=6)
```

---

### 3. Add Consistency Check Between Modes (LOW PRIORITY)

**Validate**: Streaming and in-memory produce IDENTICAL results

```bash
# After both modes complete
echo "   Comparing streaming vs in-memory results..."
python3 - <<EOF
import psycopg2
conn = psycopg2.connect(...)

# Query results from both runs
results_inmem = pd.read_sql("SELECT * FROM summary_inmem", conn)
results_stream = pd.read_sql("SELECT * FROM summary_stream", conn)

# Should be IDENTICAL (not just similar)
if results_inmem.equals(results_stream):
    print("✅ Results IDENTICAL")
else:
    print("❌ Results DIFFER!")
    diff = results_inmem.compare(results_stream)
    print(diff)
    sys.exit(1)
EOF
```

---

## 📝 Updated Confidence Assessment (After Fixes)

### With IQE Validation Integrated

| Metric | Validation | Confidence | Risk |
|--------|------------|------------|------|
| **Functional** | ✅ Exit code + IQE | HIGH | LOW |
| **Performance** | ✅ Time, memory | HIGH | LOW |
| **Row Counts** | ✅ Input/output + IQE | HIGH | LOW |
| **CPU Aggregation** | ✅ **IQE validation** | 🟢 **HIGH** | 🟢 **LOW** |
| **Memory Aggregation** | ✅ **IQE validation** | 🟢 **HIGH** | 🟢 **LOW** |
| **Capacity Calculation** | ✅ **IQE validation** | 🟢 **HIGH** | 🟢 **LOW** |
| **Label Merging** | ✅ **IQE validation** | 🟢 **HIGH** | 🟢 **LOW** |
| **1:1 Trino Parity** | ✅ **IQE validation** | 🟢 **HIGH** | 🟢 **LOW** |

---

## 🎯 Current vs Recommended

### Current Benchmark Script
```bash
✅ Generate data
✅ Upload to MinIO
✅ Run POC (check exit code)
✅ Capture metrics (time, memory, rows)
❌ Validate correctness  # MISSING
✅ Generate report
```

**Confidence**: 🔴 **LOW** for correctness

---

### Recommended Benchmark Script
```bash
✅ Generate data
✅ Upload to MinIO
✅ Run POC (check exit code)
✅ Capture metrics (time, memory, rows)
✅ Validate correctness (IQE checks)  # NEW
✅ Compare streaming vs in-memory     # NEW
✅ Generate report (with validation status)
```

**Confidence**: 🟢 **HIGH** for correctness

---

## 🚀 Implementation Plan

### Quick Win (30 minutes)
1. Modify `run_streaming_comparison.sh` to call IQE validation after each test
2. Add `VALIDATION_STATUS` column to summary CSV
3. Fail-fast if validation fails

### Medium Term (2-3 hours)
1. Create scale-specific expected value generator
2. Compare PostgreSQL results against nise metadata
3. Add streaming vs in-memory consistency check

### Long Term (Future)
1. Add Trino comparison (if Trino available)
2. Create regression test suite with known good results
3. Automate correctness validation in CI/CD

---

## 📊 Summary Table

| Question | Answer | Confidence |
|----------|--------|------------|
| Does benchmark validate POC runs? | ✅ Yes | HIGH |
| Does benchmark capture performance? | ✅ Yes | HIGH |
| Does benchmark validate correctness? | ❌ **No** | 🔴 **NONE** |
| Do we know results are correct? | ✅ Yes (from IQE tests) | HIGH |
| Do we know results are correct AT SCALE? | ❌ **No** | 🔴 **UNKNOWN** |
| Do streaming and in-memory match? | 🟡 Assumed, not validated | MEDIUM |
| **Should we trust benchmark results?** | 🟡 **For performance: Yes<br>For correctness: No** | **SPLIT** |

---

## ✅ Conclusion

**Current Confidence**: 🔴 **LOW** for correctness validation in benchmarks

**Why**:
- Benchmarks only check that POC runs
- No comparison against expected values
- No validation of aggregation accuracy
- Different data from IQE tests

**Recommendation**:
- ✅ **Add IQE validation to benchmark script** (HIGH PRIORITY)
- ✅ **Fail-fast on incorrect results**
- ✅ **Validate streaming = in-memory**

**With Fixes**: 🟢 **HIGH** confidence that benchmarks validate both performance AND correctness

---

*Assessment complete. Recommend adding correctness validation before relying on benchmark results.*

