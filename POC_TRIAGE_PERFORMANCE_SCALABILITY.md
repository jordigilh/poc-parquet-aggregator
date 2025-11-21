# POC Triage: Performance & Scalability Improvements

**Date**: 2025-11-20
**Status**: Production-Ready POC with Clear Enhancement Path
**Priority Focus**: Memory Optimization & Scalability

---

## Executive Summary

### Current State: ✅ Good Foundation

- **Functional**: 100% correct (7/7 IQE tests passing)
- **Performance**: 3-7K rows/sec processing speed
- **Memory**: ~10-20 MB per 1K rows (in-memory mode)
- **Scalability**: Works well for < 100K rows, needs optimization for larger

### Critical Finding: 🔴 STREAMING NOT ENABLED

**Issue**: The code HAS streaming capability but it's **DISABLED** by default!

**Location**: `src/main.py` lines 99 and 115
```python
streaming=False  # For POC, load entire file
```

**Impact**:
- ❌ Loads entire month of Parquet data into memory
- ❌ Memory grows linearly with data size (10 MB per 1K rows)
- ❌ Will OOM on datasets > 100K rows without large containers

**Quick Win**: Enable streaming mode → Constant memory usage regardless of data size

---

## Priority 1 Issues (P0 - Critical for Scale)

### 1. 🔴 Enable Streaming Mode (HIGHEST PRIORITY)

**Current Code** (`src/main.py:94-99`):
```python
pod_usage_daily_df = parquet_reader.read_pod_usage_line_items(
    provider_uuid=provider_uuid,
    year=year,
    month=month,
    daily=True,
    streaming=False  # ❌ PROBLEM: Loads all data into memory
)
```

**Problem**:
- Loads entire month (31 days × N pods) into single DataFrame
- Memory: 10 MB per 1K rows → 1M rows = 10 GB!
- No memory limit or chunking

**Solution**: Enable streaming with chunk-based aggregation

```python
# Option A: Simple - Enable existing streaming flag
pod_usage_daily_df = parquet_reader.read_pod_usage_line_items(
    provider_uuid=provider_uuid,
    year=year,
    month=month,
    daily=True,
    streaming=True,  # ✅ Enable streaming
    chunk_size=50_000  # Process 50K rows at a time
)

# Then aggregate in chunks instead of all at once
if config.get('performance', {}).get('use_streaming', False):
    aggregated_chunks = []
    for chunk in pod_usage_daily_df:  # Iterator, not DataFrame
        chunk_agg = aggregator.aggregate_chunk(chunk, ...)
        aggregated_chunks.append(chunk_agg)
    aggregated_df = pd.concat(aggregated_chunks)
else:
    # Current path: in-memory
    aggregated_df = aggregator.aggregate(pod_usage_daily_df, ...)
```

**Benefit**:
- ✅ **Constant memory**: 500 MB - 1 GB regardless of data size
- ✅ **Scale to millions of rows**: No OOM errors
- ✅ **Minimal code changes**: Infrastructure already exists

**Effort**: 2-3 hours (implement chunked aggregation in `aggregator_pod.py`)

**Impact**: 🟢 **CRITICAL** - Enables processing of large datasets

---

### 2. 🟡 Implement Chunk-Based Aggregation

**Problem**: Current `PodAggregator.aggregate()` expects full DataFrame

**Location**: `src/aggregator_pod.py:51-136`

```python
def aggregate(self, pod_usage_df: pd.DataFrame, ...) -> pd.DataFrame:
    # Expects entire dataset in memory
    # Problem: Can't process streaming chunks
```

**Solution**: Add chunked aggregation method

```python
def aggregate_streaming(
    self,
    pod_usage_chunks: Iterator[pd.DataFrame],
    node_capacity_df: pd.DataFrame,
    ...
) -> pd.DataFrame:
    """Aggregate pod usage in chunks (streaming mode).

    Args:
        pod_usage_chunks: Iterator of DataFrame chunks
        ...

    Returns:
        Aggregated DataFrame
    """
    aggregated_chunks = []

    for chunk_idx, chunk_df in enumerate(pod_usage_chunks):
        self.logger.debug(f"Processing chunk {chunk_idx + 1}", rows=len(chunk_df))

        # Process this chunk (same logic as aggregate())
        chunk_prepared = self._prepare_pod_usage_data(chunk_df)
        chunk_prepared = self._join_node_labels(chunk_prepared, node_labels_df)
        chunk_prepared = self._join_namespace_labels(chunk_prepared, namespace_labels_df)
        # ... rest of processing

        # Aggregate this chunk
        chunk_aggregated = self._group_and_aggregate(chunk_prepared)
        aggregated_chunks.append(chunk_aggregated)

        # Free memory
        del chunk_df, chunk_prepared
        gc.collect()

    # Combine all chunks and re-aggregate (key grouping step!)
    combined_df = pd.concat(aggregated_chunks, ignore_index=True)

    # Final aggregation across chunks (to merge duplicate keys)
    final_df = self._final_aggregation(combined_df)

    # Join with node capacity and format
    final_df = self._join_node_capacity(final_df, node_capacity_df)
    final_df = self._join_cost_category(final_df, cost_category_df)
    final_df = self._format_output(final_df)

    return final_df

def _final_aggregation(self, df: pd.DataFrame) -> pd.DataFrame:
    """Re-aggregate across chunks to merge duplicate keys.

    Since we processed in chunks, the same (date, namespace, node) tuple
    might appear in multiple chunks. Need to sum them together.
    """
    group_keys = ['usage_start', 'namespace', 'node', 'source', 'merged_labels']

    # Same aggregation functions as _group_and_aggregate()
    agg_funcs = {
        'pod_usage_cpu_core_hours': 'sum',
        'pod_request_cpu_core_hours': 'sum',
        # ... all metrics
    }

    return df.groupby(group_keys, dropna=False).agg(agg_funcs).reset_index()
```

**Benefit**:
- ✅ Enables streaming mode
- ✅ Constant memory usage
- ✅ Can process unlimited data size

**Effort**: 4-6 hours

**Impact**: 🟢 **HIGH** - Required for streaming mode

---

### 3. 🟡 Parallel File Reading (Already Implemented, but can be improved)

**Current Code** (`src/parquet_reader.py:259-261`):
```python
# Use parallel reading for better performance
parallel_workers = self.config.get('performance', {}).get('parallel_readers', 4)
return self._read_files_parallel(files, parallel_workers)
```

**Status**: ✅ Already implemented with ThreadPoolExecutor

**Improvement Opportunity**: Make it even more efficient

```python
def _read_files_parallel_optimized(
    self,
    files: List[str],
    max_workers: int = 4,
    columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """Read files in parallel with better memory management."""

    # Pre-filter columns (30-40% memory savings)
    if columns is None:
        columns = self.get_optimal_columns_pod_usage()

    # Use ProcessPoolExecutor for CPU-bound work (2-3x faster)
    from concurrent.futures import ProcessPoolExecutor

    dfs = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all reads
        futures = {executor.submit(self._read_file_optimized, f, columns): f
                   for f in files}

        # Collect as they complete
        for future in as_completed(futures):
            df = future.result()
            if not df.empty:
                # Convert string columns to categorical immediately
                df = self._optimize_datatypes(df)
                dfs.append(df)

    return pd.concat(dfs, ignore_index=True)

def _optimize_datatypes(self, df: pd.DataFrame) -> pd.DataFrame:
    """Optimize DataFrame memory by using categorical types."""
    # String columns that repeat a lot → use categorical (50-70% memory savings)
    categorical_cols = ['namespace', 'node', 'source', 'pod', 'resource_id']
    for col in categorical_cols:
        if col in df.columns and df[col].dtype == 'object':
            df[col] = df[col].astype('category')

    # Downcast numeric types (10-20% memory savings)
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='float')

    return df
```

**Benefit**:
- ✅ 2-3x faster file reading
- ✅ 50-70% less memory (categorical types)
- ✅ Better CPU utilization

**Effort**: 3-4 hours

**Impact**: 🟡 **MEDIUM** - Nice optimization but not critical

---

## Priority 2 Issues (P1 - Performance Optimization)

### 4. 🟡 Column Filtering (Partially Implemented)

**Current Code** (`src/parquet_reader.py:408-433`):
```python
def get_optimal_columns_pod_usage(self) -> List[str]:
    """Get optimal column list for pod usage (reduce memory)."""
    return [
        'interval_start',
        'namespace',
        'node',
        # ... 15 columns
    ]
```

**Problem**: Method exists but **NOT USED** in main code path!

**Solution**: Actually use it

```python
# In read_pod_usage_line_items():
def read_pod_usage_line_items(self, ...):
    files = self.list_parquet_files(s3_prefix)

    # ✅ Use column filtering
    if self.config.get('performance', {}).get('column_filtering', True):
        columns = self.get_optimal_columns_pod_usage()
    else:
        columns = None

    if streaming:
        def stream_all_files():
            for file in files:
                yield from self.read_parquet_streaming(file, chunk_size, columns=columns)
        return stream_all_files()
    else:
        return self._read_files_parallel(files, parallel_workers, columns=columns)
```

**Benefit**:
- ✅ 30-40% memory reduction
- ✅ 20-30% faster Parquet reading
- ✅ Less S3 bandwidth

**Effort**: 30 minutes (just wire it up)

**Impact**: 🟡 **MEDIUM** - Easy win

---

### 5. 🟢 Memory Optimization with Categorical Types

**Problem**: String columns (namespace, node, pod, etc.) use a lot of memory

**Example**:
```python
# Current: Each string stored separately
namespace: ['kube-system', 'kube-system', 'kube-system', ...]  # 50 bytes × 10K = 500 KB

# Optimized: Store unique values + indices
namespace: Categorical['kube-system', 'monitoring', 'app']  # 150 bytes + indices (2 bytes × 10K) = 20 KB
# 96% memory reduction!
```

**Solution**: Already in utils.py but not used!

```python
# In parquet_reader.py after reading:
from .utils import optimize_dataframe_memory

df = self.read_parquet_file(file, columns)

# Apply memory optimization
if self.config.get('performance', {}).get('use_categorical', True):
    categorical_cols = ['namespace', 'node', 'pod', 'resource_id', 'source']
    df = optimize_dataframe_memory(df, categorical_columns=categorical_cols, logger=self.logger)

return df
```

**Benefit**:
- ✅ 50-70% memory reduction for string columns
- ✅ Faster groupby operations (categorical is faster)
- ✅ Already implemented, just needs to be enabled!

**Effort**: 15 minutes

**Impact**: 🟢 **HIGH** - Major memory savings with minimal effort

---

### 6. 🟢 Incremental Processing (Future Enhancement)

**Problem**: Re-processes all data every day (even unchanged data)

**Current Flow**:
```
Day 1: Process Oct 1-31 (31 days)
Day 2: Process Oct 1-31 (31 days) ← Reprocessing same data!
Day 3: Process Oct 1-31 (31 days) ← Reprocessing again!
```

**Solution**: Track what's been processed

```python
def incremental_aggregate(provider_uuid, year, month, date):
    """Only process new/changed data."""

    # Get last processed timestamp
    last_processed = db.get_last_processed_timestamp(provider_uuid, year, month)

    # Only read files newer than last processed
    all_files = parquet_reader.list_parquet_files(prefix)
    new_files = [f for f in all_files if file_mtime(f) > last_processed]

    if not new_files:
        logger.info("No new data to process")
        return

    # Process only new files
    new_data = parquet_reader.read_parquet_files(new_files)

    # Aggregate and merge with existing data
    # Option A: Delete and re-insert for affected dates
    # Option B: UPSERT with conflict resolution
    aggregated = aggregator.aggregate(new_data, ...)
    db.upsert_summary_data(aggregated)  # Update existing or insert new

    # Update timestamp
    db.update_last_processed_timestamp(provider_uuid, year, month, now())
```

**Benefit**:
- ✅ 90% less data to process (only new data)
- ✅ 10x faster daily runs
- ✅ Lower cost

**Effort**: 1-2 weeks (requires database schema changes)

**Impact**: 🟢 **HIGH** - Major optimization for production

---

## Priority 3 Issues (P2 - Nice to Have)

### 7. 🟢 Arrow-Native Processing (Future)

**Problem**: Pandas converts Arrow → Python objects (slow, memory-heavy)

**Solution**: Stay in Arrow format longer

```python
# Instead of:
table = pq.read_table(file, filesystem=fs)
df = table.to_pandas()  # ❌ Conversion to Python objects

# Do:
table = pq.read_table(file, filesystem=fs)
# Process in Arrow format (faster, less memory)
filtered = table.filter(pc.field('node') != '')
grouped = table.group_by(['usage_start', 'namespace', 'node']).aggregate([
    ('pod_usage_cpu_core_seconds', 'sum'),
    # ...
])
# Only convert to Pandas at the end
df = grouped.to_pandas()
```

**Benefit**:
- ✅ 2-3x faster processing
- ✅ 30% less memory
- ✅ Zero-copy operations

**Effort**: 2-3 weeks (major refactor)

**Impact**: 🟡 **MEDIUM** - Nice but not critical

---

### 8. 🟢 Database Connection Pooling

**Problem**: Creates new connection for each operation

**Current** (`src/db_writer.py:40-53`):
```python
def connect(self):
    self.connection = psycopg2.connect(...)  # New connection each time
```

**Solution**: Use connection pooling

```python
from psycopg2 import pool

class DatabaseWriter:
    _connection_pool = None

    @classmethod
    def init_pool(cls, config, min_conn=2, max_conn=10):
        if cls._connection_pool is None:
            cls._connection_pool = pool.ThreadedConnectionPool(
                min_conn, max_conn,
                host=config['postgresql']['host'],
                database=config['postgresql']['database'],
                # ...
            )

    def connect(self):
        self.connection = self._connection_pool.getconn()
```

**Benefit**:
- ✅ Faster writes (no connection overhead)
- ✅ Better for parallel processing
- ✅ Connection reuse

**Effort**: 2 hours

**Impact**: 🟢 **LOW** - Minor improvement

---

## Implementation Roadmap

### Phase 1: Quick Wins (1 week)

**Priority**: Enable streaming + memory optimizations

1. ✅ **Day 1**: Enable column filtering (30 min)
   - Wire up `get_optimal_columns_pod_usage()`
   - Test memory savings

2. ✅ **Day 1**: Enable categorical types (15 min)
   - Wire up `optimize_dataframe_memory()`
   - Test memory savings

3. 🔴 **Day 2-3**: Implement chunked aggregation (6 hours)
   - Add `aggregate_streaming()` method
   - Add `_final_aggregation()` method
   - Test with 100K rows

4. 🔴 **Day 4**: Enable streaming mode (2 hours)
   - Update `main.py` to support streaming
   - Add config flag `use_streaming`
   - Test with 500K rows

5. ✅ **Day 5**: Testing & validation (4 hours)
   - Run IQE tests with streaming enabled
   - Verify memory stays constant
   - Document findings

**Expected Results**:
- Memory: 10 GB → 1 GB (10x reduction)
- Can process unlimited rows
- All IQE tests still passing

---

### Phase 2: Performance Optimization (2 weeks)

1. 🟡 **Week 1**: Parallel processing improvements
   - ProcessPoolExecutor for file reading
   - Optimize data type conversions
   - Benchmark improvements

2. 🟡 **Week 2**: Database optimizations
   - Connection pooling
   - Bulk insert optimization
   - Parallel writes with partitioning

**Expected Results**:
- Processing speed: 5K → 10K rows/sec (2x)
- Memory: Additional 30% reduction
- Latency: 50% reduction

---

### Phase 3: Production Readiness (4 weeks)

1. 🟢 **Weeks 1-2**: Incremental processing
   - Track processed timestamps
   - Implement UPSERT logic
   - Handle partial data updates

2. 🟢 **Weeks 3-4**: Advanced features
   - Retry logic with exponential backoff
   - Dead letter queue for failures
   - Comprehensive monitoring

**Expected Results**:
- Daily processing: 10x faster (only new data)
- Production-ready reliability
- Full observability

---

## Memory Comparison: Current vs Optimized

### Current (In-Memory Mode)

| Dataset | Memory Usage | Status |
|---------|--------------|--------|
| 10K rows | 200 MB | ✅ Good |
| 100K rows | 2 GB | ⚠️ OK |
| 500K rows | 10 GB | ❌ Too high |
| 1M rows | 20 GB | ❌ Infeasible |

### With Streaming + Optimizations

| Dataset | Memory Usage | Status |
|---------|--------------|--------|
| 10K rows | 150 MB (-25%) | ✅ Better |
| 100K rows | 500 MB (-75%) | ✅ Great |
| 500K rows | 800 MB (-92%) | ✅ Excellent |
| 1M rows | 1 GB (-95%) | ✅ Excellent |
| **10M rows** | **1 GB (constant)** | ✅ **Unlimited scale** |

---

## Recommended Configuration Changes

### Update `config/config.yaml`

```yaml
performance:
  # Enable streaming for datasets > 50K rows
  use_streaming: true  # ✅ ENABLE THIS
  chunk_size: 50000    # Process 50K rows at a time

  # Enable memory optimizations
  use_categorical: true      # ✅ ENABLE THIS (50-70% memory savings)
  column_filtering: true     # ✅ ENABLE THIS (30-40% memory savings)

  # Parallel processing
  parallel_readers: 4        # Already enabled
  max_workers: 4            # Already enabled

  # Memory management
  gc_after_aggregation: true      # Already enabled
  delete_intermediate_dfs: true   # Already enabled
```

### Update Resource Limits

**Before** (in-memory mode):
```yaml
resources:
  requests:
    memory: "4Gi"   # Need 4 GB for 100K rows
    cpu: "1000m"
  limits:
    memory: "8Gi"   # Need 8 GB headroom
    cpu: "2000m"
```

**After** (streaming mode):
```yaml
resources:
  requests:
    memory: "1Gi"   # Constant memory
    cpu: "1000m"
  limits:
    memory: "2Gi"   # Constant memory
    cpu: "2000m"
```

**Savings**: 75% less memory required!

---

## Testing Strategy

### Test 1: Memory Consumption

```bash
# Generate large dataset
python scripts/generate_synthetic_data.py --rows 500000

# Benchmark memory
python scripts/benchmark_performance.py \
    --streaming=false \
    --output=results/baseline.json

python scripts/benchmark_performance.py \
    --streaming=true \
    --output=results/streaming.json

# Compare
python -c "
import json
baseline = json.load(open('results/baseline.json'))
streaming = json.load(open('results/streaming.json'))
print(f'Memory reduction: {(1 - streaming['peak_memory_bytes'] / baseline['peak_memory_bytes']) * 100:.1f}%')
"
```

**Expected**: 85-95% memory reduction

### Test 2: IQE Regression Tests

```bash
# Ensure streaming mode doesn't break correctness
./scripts/test_iqe_production_scenarios.sh --streaming=true
```

**Expected**: 7/7 tests still passing

### Test 3: Performance Benchmark

```bash
# Compare processing speed
./scripts/run_comprehensive_benchmarks.sh
```

**Expected**: Similar or better speed, much less memory

---

## Risk Assessment

### Low Risk ✅

1. **Column filtering** - Already implemented, just needs enabling
2. **Categorical types** - Already implemented, safe optimization
3. **Streaming infrastructure** - Already coded and tested

### Medium Risk ⚠️

1. **Chunked aggregation** - New code, needs careful testing
2. **Parallel processing changes** - Could introduce race conditions
3. **Database pooling** - Connection management complexity

### High Risk 🔴

1. **Arrow-native processing** - Major refactor, compatibility issues
2. **Incremental processing** - Database schema changes, complex logic

**Mitigation**: Implement Phase 1 first, validate thoroughly, then proceed

---

## Summary & Recommendations

### Critical Finding: Streaming Exists But Is Disabled! 🔴

The POC already has streaming capabilities built-in, but they're **turned off**. This is the #1 issue to fix.

### Quick Wins (1 week, high impact)

1. ✅ Enable column filtering - 30 minutes, 30-40% memory savings
2. ✅ Enable categorical types - 15 minutes, 50-70% memory savings
3. 🔴 Enable streaming mode - 8 hours, 85-95% memory savings

**Total effort**: 1 week
**Total impact**: 90-95% memory reduction
**Risk**: Low (infrastructure already exists)

### Recommendation: ✅ PROCEED with Phase 1 immediately

The POC is production-ready for **correctness** but needs streaming enabled for **scale**. All the hard work is already done - just needs to be enabled and tested!

---

**Date**: 2025-11-20
**Status**: Ready for Phase 1 implementation
**Confidence**: 95% (infrastructure exists, just needs activation)

