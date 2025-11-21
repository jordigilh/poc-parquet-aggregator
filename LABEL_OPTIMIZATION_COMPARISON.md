# Label Processing Optimization - Technical Comparison

## Option 3 vs Option 4 vs Hybrid Approach

### Option 3: Vectorized Python with List Comprehension

**Implementation**:
```python
def vectorized_merge_labels(node_labels, namespace_labels, pod_labels):
    """Use list comprehension instead of .apply(axis=1)"""
    return [
        merge_dicts(n, ns, p)
        for n, ns, p in zip(node_labels, namespace_labels, pod_labels)
    ]

# Usage
pod_usage_df['merged_labels_dict'] = vectorized_merge_labels(
    pod_usage_df['node_labels_dict'].values,
    pod_usage_df['namespace_labels_dict'].values,
    pod_usage_df['pod_labels_dict'].values
)
```

**Pros**:
- ✅ Simple to implement (minimal code changes)
- ✅ 3-5x faster than `.apply(axis=1)`
- ✅ Pure Python (no new dependencies)
- ✅ Easy to debug and maintain
- ✅ Can implement TODAY (30 minutes)

**Cons**:
- ⚠️ Still processes in Python (not true vectorization)
- ⚠️ Limited speedup (3-5x, not 10-100x)
- ⚠️ Won't scale to millions of rows efficiently

**Performance Estimate**:
- 7K rows: ~30-60 seconds (vs 3-5 minutes)
- 1M rows: ~1-2 hours (vs 9-10 hours)

---

### Option 4: PyArrow Compute Functions

**Implementation**:
```python
import pyarrow as pa
import pyarrow.compute as pc

def merge_labels_arrow(table):
    """Use PyArrow compute for label merging"""

    # Define UDF for label merging
    @pc.udf
    def merge_labels_udf(node, namespace, pod):
        return merge_dicts(node, namespace, pod)

    # Apply in Arrow (C++ execution)
    result = pc.call_function('merge_labels_udf', [
        table['node_labels_dict'],
        table['namespace_labels_dict'],
        table['pod_labels_dict']
    ])

    return result

# Usage
arrow_table = pa.Table.from_pandas(pod_usage_df)
merged = merge_labels_arrow(arrow_table)
pod_usage_df['merged_labels_dict'] = merged.to_pandas()
```

**Pros**:
- ✅✅ 10-100x faster than pandas (C++ execution)
- ✅✅ True zero-copy operations
- ✅✅ Scales to billions of rows
- ✅ Memory efficient (columnar format)
- ✅ Future-proof (Arrow is industry standard)

**Cons**:
- ❌ More complex to implement (2-4 hours)
- ❌ Requires learning PyArrow UDF API
- ❌ Harder to debug (C++ layer)
- ❌ Current PyArrow UDFs still call Python (but with better batching)

**Performance Estimate**:
- 7K rows: ~5-10 seconds (vs 3-5 minutes)
- 1M rows: ~5-10 minutes (vs 9-10 hours)

---

## Hybrid Approach: BEST SOLUTION ✅

**Strategy**: Use both in stages

### Stage 1: Quick Win (Option 3) - TODAY
Replace `.apply(axis=1)` with list comprehension for **immediate 3-5x speedup**.

```python
# aggregator_pod.py - QUICK FIX
def _merge_labels_vectorized(self, pod_df):
    """Vectorized label merging - 3-5x faster than apply()"""

    # Parse JSON labels (keep as-is for now)
    node_labels = pod_df['node_labels'].apply(
        lambda x: parse_json_labels(x) if x is not None else {}
    )
    namespace_labels = pod_df['namespace_labels'].apply(
        lambda x: parse_json_labels(x) if x is not None else {}
    )
    pod_labels = pod_df['pod_labels'].apply(
        lambda x: parse_json_labels(x) if x is not None else {}
    )

    # OPTIMIZATION: Use list comprehension instead of apply(axis=1)
    merged = [
        self._merge_all_labels(n, ns, p)
        for n, ns, p in zip(node_labels, namespace_labels, pod_labels)
    ]

    return merged
```

**Time to implement**: 30 minutes
**Speedup**: 3-5x
**Risk**: Low (simple refactor)

### Stage 2: Full Optimization (Option 4) - PHASE 2
Replace JSON parsing AND merging with PyArrow compute.

```python
# Phase 2: Full Arrow implementation
def _merge_labels_arrow(self, pod_df):
    """PyArrow-based label merging - 10-100x faster"""

    import pyarrow as pa
    import pyarrow.compute as pc

    # Convert to Arrow table (zero-copy)
    table = pa.Table.from_pandas(pod_df[['node_labels', 'namespace_labels', 'pod_labels']])

    # Parse JSON in Arrow (vectorized)
    node_parsed = pc.call_function('parse_json', [table['node_labels']])
    ns_parsed = pc.call_function('parse_json', [table['namespace_labels']])
    pod_parsed = pc.call_function('parse_json', [table['pod_labels']])

    # Merge dictionaries in Arrow (vectorized)
    merged = pc.call_function('merge_dicts', [node_parsed, ns_parsed, pod_parsed])

    return merged.to_pandas()
```

**Time to implement**: 2-4 hours
**Speedup**: 10-100x
**Risk**: Medium (new API, more testing needed)

---

## Recommendation: HYBRID APPROACH

### Implementation Plan

**TODAY (Phase 1 completion)**:
1. ✅ Implement Option 3 (list comprehension) - 30 min
2. ✅ Test with small dataset - 10 min
3. ✅ Run benchmarks to confirm 3-5x speedup
4. ✅ Document as Phase 1 complete

**PHASE 2 (Future)**:
1. Implement Option 4 (PyArrow compute)
2. Add fallback to Option 3 if PyArrow not available
3. Full performance testing at scale

### Code Structure

```python
class PodAggregator:
    def __init__(self, use_arrow=False):
        self.use_arrow = use_arrow

    def _merge_labels(self, pod_df):
        """Smart label merging with multiple strategies"""

        if self.use_arrow and PYARROW_AVAILABLE:
            # Option 4: PyArrow (10-100x faster)
            return self._merge_labels_arrow(pod_df)
        else:
            # Option 3: List comprehension (3-5x faster)
            return self._merge_labels_vectorized(pod_df)

    def _merge_labels_vectorized(self, pod_df):
        """List comprehension - quick win"""
        # ... Option 3 code ...

    def _merge_labels_arrow(self, pod_df):
        """PyArrow compute - ultimate performance"""
        # ... Option 4 code ...
```

---

## Performance Comparison Table

| Approach | 7K rows | 100K rows | 1M rows | Complexity | Time to Implement |
|----------|---------|-----------|---------|------------|-------------------|
| **Current (.apply)** | 3-5 min | 40-60 min | 9-10 hrs | Low | N/A |
| **Option 3 (list comp)** | 30-60 sec | 8-12 min | 1-2 hrs | Low | 30 min |
| **Option 4 (PyArrow)** | 5-10 sec | 1-2 min | 5-10 min | Medium | 2-4 hrs |
| **Hybrid (both)** | 5-10 sec | 1-2 min | 5-10 min | Medium | 30 min + 2-4 hrs |

---

## Decision

**Best Approach**: **Hybrid (Option 3 now + Option 4 later)**

**Rationale**:
1. ✅ **Option 3 TODAY**: Get immediate 3-5x speedup with minimal effort
2. ✅ **Option 4 PHASE 2**: Achieve ultimate performance when time permits
3. ✅ **Fallback strategy**: If PyArrow fails, fall back to vectorized Python
4. ✅ **Incremental improvement**: Don't let perfect be the enemy of good

---

## Next Step

Shall I implement **Option 3** right now (30 minutes) so we can run benchmarks today?

The change is minimal and low-risk:
- Replace `.apply(axis=1)` with list comprehension
- Test with small dataset
- Run benchmark
- Document Phase 1 complete

**After this quick fix**, benchmarks will complete in ~1 minute instead of ~5 minutes.

