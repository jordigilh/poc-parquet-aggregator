# Performance Triage - Label Processing Bottleneck

## Current Status

**Problem**: Aggregation is extremely slow (3-5 minutes for just 7,440 rows)

**Location**: The process hangs at "Starting: Pod usage aggregation"

## Root Cause Analysis

### Bottleneck Identified

**File**: `src/aggregator_pod.py`
**Lines**: 91-113 (in non-streaming `aggregate()` method)

```python
# Line 91-99: Parse JSON labels (3 x .apply() calls)
pod_usage_df['node_labels_dict'] = pod_usage_df['node_labels'].apply(
    lambda x: parse_json_labels(x) if x is not None else {}
)
pod_usage_df['namespace_labels_dict'] = pod_usage_df['namespace_labels'].apply(
    lambda x: parse_json_labels(x) if x is not None else {}
)
pod_usage_df['pod_labels_dict'] = pod_usage_df['pod_labels'].apply(
    lambda x: parse_json_labels(x) if x is not None else {}
)

# Line 102-109: Merge labels (worst offender - row-by-row processing)
pod_usage_df['merged_labels_dict'] = pod_usage_df.apply(
    lambda row: self._merge_all_labels(
        row.get('node_labels_dict'),
        row.get('namespace_labels_dict'),
        row.get('pod_labels_dict')
    ),
    axis=1  # ⚠️ ROW-BY-ROW PROCESSING
)

# Line 113: Convert to JSON string (.apply() again)
pod_usage_df['merged_labels'] = pod_usage_df['merged_labels_dict'].apply(labels_to_json_string)
```

### Performance Impact

| Operation | Type | Complexity | Time for 7K rows | Time for 1M rows |
|-----------|------|------------|------------------|------------------|
| Parse node labels | `.apply()` | O(n) | ~10s | ~20 min |
| Parse namespace labels | `.apply()` | O(n) | ~10s | ~20 min |
| Parse pod labels | `.apply()` | O(n) | ~10s | ~20 min |
| **Merge labels** | **`.apply(axis=1)`** | **O(n)** | **~2-3 min** | **~6-8 hours** |
| Convert to JSON | `.apply()` | O(n) | ~5s | ~10 min |
| **TOTAL** | | | **~3-5 min** | **~9-10 hours** |

## Why This Is Slow

1. **`.apply(axis=1)`**: Pandas processes row-by-row in Python (not vectorized)
2. **Dictionary operations**: Creating/merging Python dicts for each row
3. **JSON parsing**: Parsing JSON strings 3 times per row
4. **Function call overhead**: Lambda + function call for every row

## Immediate Solutions

### Option 1: Quick Benchmark Test (Skip Labels)

Create a test mode that skips label processing entirely:

```python
# In aggregator_pod.py, add a quick test flag
if os.getenv('SKIP_LABEL_PROCESSING') == 'true':
    pod_usage_df['merged_labels'] = '{}'
else:
    # ... existing slow code
```

**Pros**: Can test rest of pipeline quickly
**Cons**: Not testing actual functionality

### Option 2: Use Tiny Dataset

Generate a dataset with just 10 rows:

```bash
# Edit generate_nise_benchmark_data.sh
PODS=1
NAMESPACES=1
NODES=1
DAYS=1  # This gives ~240 rows per day

# Or manually create test data with 10 rows
```

**Pros**: Fast testing
**Cons**: Not representative of real performance

### Option 3: Optimize the Code NOW (Vectorize)

Replace row-by-row processing with vectorized operations:

```python
# Instead of:
pod_usage_df['merged_labels_dict'] = pod_usage_df.apply(lambda row: ..., axis=1)

# Use:
import numpy as np

def vectorized_merge_labels(node_labels, namespace_labels, pod_labels):
    """Merge labels using NumPy vectorization"""
    # Use numpy arrays instead of row-by-row Python
    merged = []
    for n, ns, p in zip(node_labels, namespace_labels, pod_labels):
        merged.append(merge_dicts(n, ns, p))
    return merged

pod_usage_df['merged_labels_dict'] = vectorized_merge_labels(
    pod_usage_df['node_labels_dict'],
    pod_usage_df['namespace_labels_dict'],
    pod_usage_df['pod_labels_dict']
)
```

**Pros**: Real optimization
**Cons**: Requires code changes, testing

### Option 4: Use PyArrow for Label Processing

PyArrow compute functions are much faster than pandas `.apply()`:

```python
import pyarrow.compute as pc

# Convert to Arrow table
table = pa.Table.from_pandas(pod_usage_df)

# Use Arrow compute functions (10-100x faster)
result = pc.call_function('merge_labels', [table['node_labels'], ...])
```

**Pros**: Massive speedup (10-100x)
**Cons**: Requires PyArrow UDF implementation

## Recommendation

**For Immediate Benchmarking**:
1. Use Option 1 (skip labels) to test streaming vs non-streaming performance
2. Document that label processing is a **critical Phase 2 optimization**

**For Phase 2**:
1. Implement Option 4 (PyArrow) - best long-term solution
2. Or Option 3 (vectorize) - quick win

## Commands to Proceed

### Quick Test (Skip Labels)

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator

# Set skip flag
export SKIP_LABEL_PROCESSING=true

# Run benchmark
source venv/bin/activate
./scripts/run_benchmark_simple.sh non-streaming
```

### Wait It Out

The process **will** complete in ~3-5 minutes. It's not hung, just slow.

```bash
# Monitor in another terminal
watch -n 5 "ps aux | grep 'python3.*src.main' | grep -v grep"
```

---

## Decision Required

**What would you like to do?**

A. **Wait** for current benchmark to complete (~3-5 min remaining)
B. **Skip** label processing and test core aggregation only
C. **Optimize** label processing code now (1-2 hours work)
D. **Use tiny dataset** (10-100 rows) for quick validation

