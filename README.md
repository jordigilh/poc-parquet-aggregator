# POC: OCP Parquet Aggregator

## Overview

This POC validates the feasibility of replacing Trino + Hive with custom Python code that:
- Reads OCP Parquet files directly from S3/MinIO
- Performs daily aggregation logic (replicating Trino SQL)
- Writes summary results to PostgreSQL

**Goal**: Eliminate Trino + Hive dependencies for on-prem Cost Management deployments.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Current (Trino + Hive)                   │
│                                                             │
│  CSV → Parquet → Trino SQL (667 lines) → PostgreSQL        │
│                                                             │
│  Dependencies: Trino, Hive Metastore, S3 connector         │
│  Complexity: High (3 services, Java/JVM, schema management) │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   POC (Parquet + Code)                      │
│                                                             │
│  CSV → Parquet → Python Aggregator → PostgreSQL            │
│                                                             │
│  Dependencies: PyArrow, s3fs, psycopg2                     │
│  Complexity: Low (single Python module, no JVM)            │
└─────────────────────────────────────────────────────────────┘
```

## Success Criteria

### Performance (Target: 10 seconds for typical cluster)

| Metric | Target | Measured |
|--------|--------|----------|
| Processing time (1 month, 50 nodes) | < 60s | TBD |
| Peak memory usage | < 2 GB | TBD |
| Rows processed | ~1M | TBD |
| Summary rows generated | ~10K | TBD |

### Correctness (Must match Trino output within 0.01%)

| Test Case | Status | Notes |
|-----------|--------|-------|
| CPU aggregation (pod_usage_cpu_core_hours) | ⏳ | Sum must match Trino |
| Memory aggregation (pod_usage_memory_gigabyte_hours) | ⏳ | Sum must match Trino |
| Request metrics (pod_request_*) | ⏳ | Sum must match Trino |
| Effective usage (pod_effective_usage_*) | ⏳ | Sum must match Trino |
| Capacity calculations (node/cluster) | ⏳ | Max must match Trino |
| Label filtering (enabled tags only) | ⏳ | Must match PostgreSQL enabled keys |
| Label merging (node + namespace + pod) | ⏳ | Must match Trino map_concat logic |
| Date filtering (start_date to end_date) | ⏳ | Must match Trino date range |

### Code Quality

- ✅ Modular, testable design
- ✅ Comprehensive unit tests
- ✅ Clear error handling
- ✅ Performance instrumentation

## Project Structure

```
poc-parquet-aggregator/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── config/
│   └── config.yaml             # Configuration (S3, PostgreSQL, etc.)
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config_loader.py        # Configuration management
│   ├── parquet_reader.py       # S3/Parquet reading (PyArrow + s3fs)
│   ├── aggregator_pod.py       # Pod aggregation logic
│   ├── aggregator_storage.py  # Storage aggregation logic (Phase 2)
│   ├── aggregator_unallocated.py  # Unallocated capacity (Phase 2)
│   ├── db_writer.py            # PostgreSQL writer
│   ├── validator.py            # Correctness validation vs Trino
│   └── utils.py                # Helper functions
├── tests/
│   ├── __init__.py
│   ├── test_parquet_reader.py
│   ├── test_aggregator_pod.py
│   ├── test_db_writer.py
│   └── test_integration.py
└── docs/
    ├── TRINO_SQL_ANALYSIS.md   # Detailed SQL breakdown
    ├── AGGREGATION_LOGIC.md    # Aggregation algorithm explained
    └── PERFORMANCE_RESULTS.md  # Benchmark results
```

## POC Phases

### Phase 1: Core Pod Aggregation (Current - Week 1)

**Scope**: Replicate lines 260-316 of Trino SQL (Pod usage aggregation)

- [x] Set up POC structure
- [ ] Read `openshift_pod_usage_line_items_daily` Parquet from S3
- [ ] Filter enabled tags from PostgreSQL
- [ ] Aggregate pod CPU/memory usage by day + namespace + node
- [ ] Calculate node and cluster capacity
- [ ] Merge labels (node + namespace + pod)
- [ ] Write to PostgreSQL summary table
- [ ] Validate against Trino results

**Deliverable**: Working pod aggregation with performance benchmarks

### Phase 2: Storage Aggregation (Week 2)

**Scope**: Replicate lines 384-446 of Trino SQL (Storage usage aggregation)

- [ ] Read `openshift_storage_usage_line_items_daily` Parquet
- [ ] Join with pod data to determine node
- [ ] Calculate PVC capacity and usage
- [ ] Handle shared volumes (node count)
- [ ] Merge storage labels

**Deliverable**: Complete storage aggregation

### Phase 3: Unallocated Capacity (Week 2)

**Scope**: Replicate lines 491-581 of Trino SQL (Unallocated capacity calculation)

- [ ] Calculate unallocated CPU/memory per node
- [ ] Classify by node role (Platform vs Worker)
- [ ] Generate unallocated records

**Deliverable**: Full OCP aggregation parity with Trino

### Phase 4: Optimization & Production Readiness (Week 3)

- [ ] Parallel processing (multi-day, multi-file)
- [ ] Memory optimization (streaming aggregation)
- [ ] Error handling and retry logic
- [ ] Logging and monitoring
- [ ] Integration with MASU

**Deliverable**: Production-ready aggregator

## Installation

```bash
cd poc-parquet-aggregator
pip install -r requirements.txt
```

## Configuration

Copy and edit `config/config.yaml`:

```yaml
s3:
  endpoint: "https://s3-openshift-storage.apps.cluster.example.com"
  access_key: "..."
  secret_key: "..."
  bucket: "cost-management"

postgresql:
  host: "postgresql.cost-management.svc"
  database: "koku"
  schema: "org1234567"
  user: "koku"
  password: "..."

ocp:
  provider_uuid: "..."
  cluster_id: "..."
  year: "2025"
  month: "11"
```

## Usage

### Run POC Aggregation

```bash
python -m src.main
```

### Validate Against Trino

```bash
python -m src.main --validate
```

This will:
1. Run the Parquet aggregator
2. Run the equivalent Trino SQL query
3. Compare results row-by-row
4. Report discrepancies and statistics

### Run Tests

```bash
pytest tests/ -v
```

## Performance Benchmarks

### Test Environment

- **Cluster**: 50 nodes, 500 pods
- **Data**: 1 month (30 days)
- **Input**: ~1M Parquet rows
- **Output**: ~10K summary rows

### Results

| Phase | Time (s) | Memory (MB) | Status |
|-------|----------|-------------|--------|
| Read Parquet | TBD | TBD | ⏳ |
| Filter tags | TBD | TBD | ⏳ |
| Aggregate | TBD | TBD | ⏳ |
| Write PostgreSQL | TBD | TBD | ⏳ |
| **Total** | **TBD** | **TBD** | **⏳** |

## Validation Results

### Correctness

| Metric | Trino | Parquet Aggregator | Diff | Status |
|--------|-------|-------------------|------|--------|
| Total CPU hours | TBD | TBD | TBD | ⏳ |
| Total Memory GB-hours | TBD | TBD | TBD | ⏳ |
| Unique namespaces | TBD | TBD | TBD | ⏳ |
| Unique nodes | TBD | TBD | TBD | ⏳ |

### Row-by-Row Comparison

- **Matching rows**: TBD
- **Extra in Trino**: TBD
- **Extra in Parquet**: TBD
- **Value differences**: TBD

## Risks & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Performance slower than expected | Medium | High | Use PyArrow zero-copy, parallel processing |
| Complex SQL logic hard to replicate | Medium | High | Break into small, testable functions |
| Floating-point precision issues | Low | Medium | Use Decimal, allow 0.01% tolerance |
| Memory exhaustion on large clusters | Low | High | Stream processing, chunked reads |

## Decision Criteria

### Go Decision (Proceed to Full Implementation)

- ✅ Performance < 60s for typical cluster
- ✅ Correctness within 0.01% of Trino
- ✅ Memory < 2 GB peak usage
- ✅ Code is clear and maintainable

**Estimated Timeline**: 24-35 weeks for full implementation (all providers)

### No-Go Decision (Fall back to Option A: Intermediate PostgreSQL)

- ❌ Performance > 120s (2x target)
- ❌ Correctness issues (> 0.1% difference)
- ❌ Memory > 4 GB (unsustainable)
- ❌ Code complexity too high

## Next Steps

1. **Complete Phase 1** (Pod aggregation)
2. **Measure performance** on real OCP data
3. **Validate correctness** against Trino
4. **Assess maintainability** (code review with team)
5. **Decision Point**: Go / No-Go for full implementation

## Timeline

- **Week 1**: Phase 1 - Pod aggregation + validation
- **Week 2**: Phase 2-3 - Storage + unallocated capacity
- **Week 3**: Phase 4 - Optimization + production readiness
- **Week 4**: Final assessment + decision

## Contact / Questions

This POC is part of the Trino + Hive removal initiative for Cost Management on-prem deployments.

**Related Documents**:
- `docs/migration/TRINO-REPLACEMENT-OPTIONS.md` - Architecture options analysis
- `docs/migration/IMPLEMENTATION-PLAN.md` - Full migration plan
- `koku/masu/database/trino_sql/reporting_ocpusagelineitem_daily_summary.sql` - Original Trino SQL (667 lines)

