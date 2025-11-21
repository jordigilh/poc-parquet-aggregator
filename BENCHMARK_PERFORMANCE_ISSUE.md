# Benchmark Performance Issue - Analysis

## Problem

The benchmark is **extremely slow** (appears to hang) at the "Pod usage aggregation" phase.

## Root Cause

**Location**: `src/aggregator_pod.py` lines 102-109

```python
pod_usage_df['merged_labels_dict'] = pod_usage_df.apply(
    lambda row: self._merge_all_labels(
        row.get('node_labels_dict'),
        row.get('namespace_labels_dict'),
        row.get('pod_labels_dict')
    ),
    axis=1
)
```

**The Issue**: 
- Using `.apply(axis=1)` processes **row-by-row** in Python
- This is the slowest possible way to process data in pandas
- For 7,440 rows (small dataset!), this takes **several minutes**
- For production datasets (millions of rows), this would be **completely unusable**

## Performance Impact

| Dataset Size | Estimated Time | Status |
|--------------|----------------|--------|
| Small (7K rows) | ~3-5 minutes | Very Slow |
| Medium (50K rows) | ~20-30 minutes | Unusable |
| Large (500K rows) | ~3-5 hours | Completely Unusable |
| Production (1M+ rows) | Many hours | Unacceptable |

##Options to Proceed

### Option A: Wait for Current Benchmark (Recommended)
The process is not hung - it's just very slow. It should complete in ~3-5 minutes for the small dataset.

**Action**: Let the current benchmark complete, then we'll have baseline numbers.

### Option B: Skip Non-Streaming and Test Streaming Only
Since streaming processes in chunks, it should be faster (processes 50K rows at a time instead of 7440 all at once).

**Action**: 
```bash
chmod +x scripts/run_benchmark_simple.sh
./scripts/run_benchmark_simple.sh streaming
```

### Option C: Document Issue and Move to Phase 2
Accept that this is a critical performance bottleneck that needs optimization in Phase 2.

**Phase 2 Optimization**: Vectorize the label merging logic to eliminate row-by-row processing.

## Immediate Fix for Testing

We can reduce the dataset size to make testing faster:

```bash
# Generate tiny dataset (100 rows)
./scripts/generate_nise_benchmark_data.sh tiny /tmp/nise_tiny
# Edit the script to use: PODS=1, NAMESPACES=1, NODES=1, DAYS=1
```

## Recommendation

**For now**: Let the small benchmark complete (~3-5 min) to get baseline metrics, then document this as a **critical Phase 2 optimization** priority.

The label merging logic needs to be **vectorized** to handle production workloads.

---

## Next Steps After Benchmark Completes

1. ✅ Capture baseline metrics (memory, time)
2. ✅ Document Phase 1 complete (streaming enabled, tested)
3. ➡️  Create Phase 2 plan with label processing optimization as #1 priority
4. ➡️  Consider alternative approaches:
   - Pre-compute merged labels in Parquet files
   - Use PyArrow compute functions instead of pandas
   - Implement label merging in C extension

