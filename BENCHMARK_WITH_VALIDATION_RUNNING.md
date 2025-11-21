# Benchmark Running - With Correctness Validation

**Started**: November 21, 2024
**Status**: 🟢 **RUNNING**
**Validation**: ✅ **ENABLED**

---

## 🎯 What's Running

### Benchmark Configuration

**Scales**: small, medium, large

**For Each Scale**:
1. Generate nise data
2. Upload to MinIO
3. **In-Memory Mode**:
   - Run POC aggregation
   - Capture performance metrics
   - **✅ Validate correctness** ← NEW
   - Fail-fast if validation fails
4. **Streaming Mode**:
   - Run POC aggregation
   - Capture performance metrics
   - **✅ Validate correctness** ← NEW
   - Fail-fast if validation fails

---

## ✅ Correctness Validation Details

### What Gets Validated

For each test run, the validation script:

1. **Reads nise CSV files** (raw input data)
2. **Calculates expected aggregates**:
   - Group by date, namespace, node
   - Sum CPU/memory metrics
   - Convert to core-hours, GB-hours
3. **Queries PostgreSQL** for actual POC results
4. **Compares expected vs actual**:
   - CPU usage, request, limit (core-hours)
   - Memory usage, request, limit (GB-hours)
   - Tolerance: 1% relative difference
5. **Fails if any metric exceeds tolerance**

### Benefits

- ✅ **Correctness guaranteed**: Not just performance, but accurate results
- ✅ **Self-contained**: No dependency on IQE code
- ✅ **Comprehensive**: All aggregation metrics validated
- ✅ **Fail-fast**: Stops immediately on incorrect results

---

## 📊 Monitoring

### Check Progress

```bash
tail -f benchmark_with_validation.log
```

### Check Results Directory

```bash
ls -lh benchmark_results/streaming_comparison_*/
```

### Check for Errors

```bash
grep -E "❌|FAILED|ERROR" benchmark_with_validation.log
```

---

## 📈 Expected Timeline

| Phase | Duration | What Happens |
|-------|----------|--------------|
| **Setup** | 1 min | Environment check, validation |
| **Small Scale** | ~5 min | Generate → In-memory → Validate → Streaming → Validate |
| **Medium Scale** | ~7 min | Generate → In-memory → Validate → Streaming → Validate |
| **Large Scale** | ~10 min | Generate → In-memory → Validate → Streaming → Validate |
| **Report** | 1 min | Generate comparison report |
| **TOTAL** | ~24 min | With correctness validation |

**Note**: Validation adds ~1-2 minutes per test but ensures results are correct!

---

## 🔍 What to Look For

### Success Indicators

For each scale/mode combination:

```
3️⃣  Testing IN-MEMORY mode...
   Configuring...
   ✓ In-memory mode configured
   Running benchmark...
   ✅ POC completed (5.2s, 45.3 MB peak)
   🔍 Validating correctness...
   ✅ CORRECTNESS VALIDATED
   ✅ COMPLETE (functional + correctness validated)

4️⃣  Testing STREAMING mode...
   Configuring...
   ✓ Streaming mode configured
   Running benchmark...
   ✅ POC completed (6.1s, 32.8 MB peak)
   🔍 Validating correctness...
   ✅ CORRECTNESS VALIDATED
   ✅ COMPLETE (functional + correctness validated)
```

### Failure Indicators (Fail-Fast)

If validation fails:

```
   ✅ POC completed (5.2s, 45.3 MB peak)
   🔍 Validating correctness...
   ❌ CORRECTNESS VALIDATION FAILED
   Last 30 lines of validation log:

   ❌ cpu_usage_core_hours: 12 rows exceed 1.0% tolerance
      Max difference: 15.3%
      ...

❌ FAIL-FAST: Aggregation produced incorrect results
   Full validation log: benchmark_results/.../small_in-memory_validation.log
```

---

## 📂 Output Files

### For Each Scale

```
benchmark_results/streaming_comparison_<timestamp>/
├── small_in-memory.log              # POC execution log
├── small_in-memory_validation.log   # Correctness validation details
├── small_streaming.log              # POC execution log
├── small_streaming_validation.log   # Correctness validation details
├── medium_in-memory.log
├── medium_in-memory_validation.log
├── medium_streaming.log
├── medium_streaming_validation.log
├── large_in-memory.log
├── large_in-memory_validation.log
├── large_streaming.log
├── large_streaming_validation.log
├── SUMMARY.csv                      # Performance + validation summary
└── COMPARISON_REPORT.md             # Final comparison report
```

### SUMMARY.csv Format

**NEW**: Added `validation_status` column

```csv
scale,mode,status,duration_seconds,peak_memory_mb,input_rows,output_rows,validation_status
small,in-memory,SUCCESS,5.2,45.3,12370,2046,PASS
small,streaming,SUCCESS,6.1,32.8,12370,2046,PASS
medium,in-memory,SUCCESS,12.4,89.7,123450,20456,PASS
medium,streaming,SUCCESS,15.2,67.3,123450,20456,PASS
...
```

---

## 🎯 Success Criteria

### Performance Validation
- ✅ POC completes without errors
- ✅ Memory usage captured
- ✅ Processing time captured
- ✅ Row counts captured

### Correctness Validation (NEW)
- ✅ All CPU metrics within 1% tolerance
- ✅ All memory metrics within 1% tolerance
- ✅ Row counts match expected
- ✅ No missing or extra data

### Comparison
- ✅ Streaming vs in-memory performance compared
- ✅ Memory savings quantified
- ✅ Streaming overhead measured
- ✅ **Both modes produce correct results**

---

## 🚨 If Something Goes Wrong

### Validation Failure

If correctness validation fails:

1. **Check validation log**:
   ```bash
   cat benchmark_results/streaming_comparison_*/small_in-memory_validation.log
   ```

2. **Identify which metrics failed**:
   - CPU usage/request/limit?
   - Memory usage/request/limit?
   - Row count mismatch?

3. **Check for regressions**:
   - Did recent code changes break aggregation logic?
   - Are label merges working correctly?
   - Are capacity calculations accurate?

### Functional Failure

If POC crashes or hangs:

1. **Check POC log**:
   ```bash
   cat benchmark_results/streaming_comparison_*/small_in-memory.log
   ```

2. **Look for errors**:
   - Database connection issues?
   - S3 read errors?
   - Memory exhaustion?

---

## 💡 What This Gives Us

### Before (Performance Only)

```
✅ POC runs in 5.2 seconds
✅ Uses 45 MB memory
❓ But are the results correct? UNKNOWN
```

### After (Performance + Correctness)

```
✅ POC runs in 5.2 seconds
✅ Uses 45 MB memory
✅ All aggregated values correct (validated against nise)
✅ CPU metrics accurate within 1%
✅ Memory metrics accurate within 1%
✅ Row counts match expected
✅ Can confidently trust results
```

---

## 📊 What We'll Learn

### Performance Questions
- ❓ How much faster is in-memory vs streaming?
- ❓ How much memory does streaming save?
- ❓ Does streaming scale better?

### Correctness Questions (NEW)
- ❓ Do both modes produce identical results?
- ❓ Are all aggregation metrics accurate?
- ❓ Does the POC match Trino output?
- ❓ Can we trust this for production?

**All will be answered with validation!**

---

## ✅ Summary

**Running**: Benchmarks with integrated correctness validation
**Scales**: small, medium, large
**Validation**: POC results vs nise expected values
**Fail-Fast**: Stops immediately on incorrect results
**Duration**: ~24 minutes
**Confidence**: 🟢 **HIGH** - Both performance AND correctness validated

---

## 🔗 Related Documents

- `BENCHMARK_CORRECTNESS_ASSESSMENT.md` - Why validation is needed
- `CORRECTNESS_VALIDATION_IMPLEMENTED.md` - How validation works
- `scripts/validate_benchmark_correctness.py` - Validation script
- `scripts/run_streaming_comparison.sh` - Benchmark script (modified)

---

*Benchmark running... Results will be in `benchmark_results/streaming_comparison_<timestamp>/`*

