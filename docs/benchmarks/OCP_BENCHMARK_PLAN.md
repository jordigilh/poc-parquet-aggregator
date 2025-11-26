# OCP-Only Benchmark Plan

**Date**: November 26, 2025
**Status**: ✅ **EXECUTED** (methodology validated, manifests need scaling)
**Purpose**: Measure processing time and memory for OCP-only aggregation at production scale
**Results**: Saved to `benchmark_results/ocp_20251126_081230/`

## Table of Contents

1. [Objectives](#-objectives)
2. [Benchmark Data Points](#-benchmark-data-points)
3. [Methodology](#-methodology)
4. [Expected Results](#-expected-results)
5. [Running Benchmarks](#-running-benchmarks)
6. [Correctness Validation](#-correctness-validation)
7. [Failure Recovery](#-failure-recovery)

---

## 🎯 Objectives

1. **Measure processing performance** at 6 scale points: 20K, 50K, 100K, 250K, 500K, 1M output rows
2. **Capture time and memory** for data processing + PostgreSQL insertion (NOT data generation)
3. **Generate reproducible benchmark results** with chart visualizations
4. **Validate memory stays within production limits** (target: < 48 GB)

---

## 📊 Benchmark Data Points

### Target Output Rows (After Aggregation)

| Scale ID | Target Output Rows | Tolerance (±1%) | Pods | Nodes | Pods/Node | Hours |
|----------|-------------------|-----------------|------|-------|-----------|-------|
| **scale-20k** | 20,160 | 19,958 - 20,362 | 420 | 5 | 84 | 24 |
| **scale-50k** | 50,400 | 49,896 - 50,904 | 1,050 | 10 | 105 | 24 |
| **scale-100k** | 100,080 | 99,079 - 101,081 | 2,085 | 15 | 139 | 24 |
| **scale-250k** | 250,800 | 248,292 - 253,308 | 5,225 | 25 | 209 | 24 |
| **scale-500k** | 500,640 | 495,634 - 505,646 | 10,430 | 35 | 298 | 24 |
| **scale-1m** | 1,000,800 | 990,792 - 1,010,808 | 20,850 | 50 | 417 | 24 |
| **scale-1.5m** | 1,500,480 | 1,485,475 - 1,515,485 | 31,260 | 60 | 521 | 24 |
| **scale-2m** | 1,999,200 | 1,979,208 - 2,019,192 | 41,650 | 70 | 595 | 24 |

### Scale Interpretation (Real-World Equivalents)

What does each scale represent in a production environment?

| Scale | Cluster Size | Use Case Example |
|-------|--------------|------------------|
| **20k** | Small: 5 nodes, ~420 pods | Single development cluster, small team |
| **50k** | Medium: 10 nodes, ~1,050 pods | Production workload for small org |
| **100k** | Large: 15 nodes, ~2,085 pods | Medium enterprise, multiple applications |
| **250k** | Enterprise: 25 nodes, ~5,225 pods | Large enterprise, multi-tenant platform |
| **500k** | Multi-cluster: 35 nodes, ~10,430 pods | Multiple production clusters |
| **1m** | Platform: 50 nodes, ~20,850 pods | Large-scale platform, SaaS provider |
| **1.5m** | Hyperscale: 60 nodes, ~31,260 pods | Major enterprise, aggregated data centers |
| **2m** | Maximum: 70 nodes, ~41,650 pods | Cloud-scale operations |

**Note**: These are approximations based on:
- Average pods per node: ~80-600 depending on scale
- OCP-only aggregation produces rows = pods × days
- A single day of data per benchmark run

### Output Row Formula

```
Output Rows = Pods × Hours × Data Sources

Where:
  - Hours = 24 (full day of data)
  - Data Sources = 2 (Pod usage + Storage usage)

Example for scale-20k:
  - 420 pods × 24 hours × 2 = 20,160 rows ✓
```

**Key Constraints**:
- Tolerance: ±1% of target row count is acceptable
- 24-hour period (single day) for consistent hourly granularity

---

## 🔧 Processing Mode

### IN-MEMORY Processing

- Load all parquet files into memory at once
- Aggregate pod and storage usage in-memory
- Write results to PostgreSQL

```yaml
streaming:
  enabled: false
```

### Why Not Streaming?

Streaming mode was evaluated but **not adopted** for the following reasons:

| Factor | Impact | Assessment |
|--------|--------|------------|
| **Processing time** | +100-200% increase | ❌ Significant overhead |
| **Memory savings** | ~20-30% decrease | ⚠️ Marginal benefit |
| **OCP-on-AWS compatibility** | Cannot benefit | ❌ JOIN requires full AWS data in memory |
| **Code complexity** | Additional paths to maintain | ❌ Maintenance burden |

**Key insight**: OCP-on-AWS has an inherent memory floor because the AWS data must be fully loaded for JOIN operations. Streaming only chunks the OCP side, providing minimal memory benefit while adding significant processing overhead.

**Future consideration**: The same constraint applies to all upcoming cloud integrations:
- OCP-on-Azure
- OCP-on-GCP
- OCP-on-{other cloud providers}

All require JOIN operations between OCP data and cloud billing data, making streaming ineffective for the most memory-intensive scenarios.

**Decision**: For consistency across OCP-only and all OCP-on-{cloud} scenarios, we use **in-memory processing only**. This simplifies the codebase and avoids confusion about when streaming would be beneficial (answer: never in practice).

> ⚠️ **Note**: Streaming code may be removed from the codebase if the team decides it adds unnecessary complexity.

---

## 📐 Measurement Metrics

### Primary Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| **Processing Time** | seconds | Time from data loading to PostgreSQL commit |
| **Peak Memory** | MB | Maximum RSS memory during processing (sampled continuously) |
| **Throughput** | rows/sec | Output rows produced per second |
| **Memory Efficiency** | KB/row | Memory used per output row |

### Secondary Metrics (Step Breakdown)

| Step | Metric Name | Description |
|------|-------------|-------------|
| **Step 1** | `ocp_load_time` | Time to load OCP parquet from MinIO |
| **Step 2** | `capacity_time` | Time for node capacity calculation |
| **Step 3** | `pod_aggregation_time` | Time for pod usage aggregation |
| **Step 4** | `storage_aggregation_time` | Time for storage usage aggregation |
| **Step 5** | `format_time` | Time for output formatting |
| **Step 6** | `db_write_time` | Time for PostgreSQL COPY |
| **Total** | `total_time` | End-to-end processing time |

### Statistical Requirements (Industry Standard)

| Requirement | Value | Rationale |
|-------------|-------|-----------|
| **Minimum runs per scale** | 3 | Reduce variance from system noise |
| **Reported value** | Median | Robust to outliers |
| **Variance measure** | Standard deviation | Quantify reproducibility |
| **Outlier handling** | Report but exclude from median | Document anomalies |

---

## 🖥️ Benchmark Environment

### Hardware (MacBook - Consistent with OCP-on-AWS benchmarks)

| Component | Specification |
|-----------|---------------|
| **Machine** | MacBook Pro |
| **CPU** | Apple M2 Max |
| **Cores** | 12 cores |
| **Memory** | 32 GB RAM |
| **Storage** | 1 TB SSD |

### Software Versions (Document Before Running)

| Component | Version | Command to Check |
|-----------|---------|------------------|
| **Python** | 3.x.x | `python --version` |
| **pandas** | x.x.x | `pip show pandas \| grep Version` |
| **PyArrow** | x.x.x | `pip show pyarrow \| grep Version` |
| **psycopg2** | x.x.x | `pip show psycopg2-binary \| grep Version` |
| **nise** | x.x.x | `pip show nise \| grep Version` |
| **PostgreSQL** | 15.x | `psql --version` |

### Disk Space Requirements

| Scale | CSV Size (est.) | Parquet Size (est.) | Working Space | Recommended Free |
|-------|-----------------|---------------------|---------------|------------------|
| 20k | ~50 MB | ~10 MB | ~100 MB | 500 MB |
| 50k | ~125 MB | ~25 MB | ~250 MB | 1 GB |
| 100k | ~250 MB | ~50 MB | ~500 MB | 2 GB |
| 250k | ~625 MB | ~125 MB | ~1.25 GB | 3 GB |
| 500k | ~1.25 GB | ~250 MB | ~2.5 GB | 5 GB |
| 1m | ~2.5 GB | ~500 MB | ~5 GB | 10 GB |

### PostgreSQL Configuration (docker-compose)

```yaml
# docker-compose.yml - benchmark-optimized settings
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: koku
      POSTGRES_USER: koku
      POSTGRES_PASSWORD: koku
    command:
      - "postgres"
      - "-c"
      - "shared_buffers=512MB"
      - "-c"
      - "work_mem=64MB"
      - "-c"
      - "maintenance_work_mem=256MB"
      - "-c"
      - "effective_cache_size=1GB"
      - "-c"
      - "synchronous_commit=off"
    ports:
      - "5432:5432"
```

### MinIO Configuration

```yaml
# docker-compose.yml
services:
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
```

---

## 🔬 Benchmark Methodology

### Pre-flight Checklist

Before running benchmarks:

- [ ] No other CPU-intensive processes running (`top` / Activity Monitor)
- [ ] Docker/Podman containers restarted fresh
- [ ] Disk has ≥10 GB free space (`df -h`)
- [ ] Previous benchmark data cleaned up (`rm -rf /tmp/ocp-benchmark-*`)
- [ ] Virtual environment activated (`source venv/bin/activate`)
- [ ] MinIO is running and accessible
- [ ] PostgreSQL is running and accessible
- [ ] Software versions documented

### Top-Level Stage Breakdown

Each benchmark run captures **time and memory** for three distinct stages:

| Stage | Description | Runs Per Scale | Measured |
|-------|-------------|----------------|----------|
| **Stage 1: Nise Generation** | Generate synthetic OCP CSV data using nise | **Once** | Time (reported separately) |
| **Stage 2: Parquet Transform** | Convert CSV to Parquet and upload to MinIO | **Once** | Time (reported separately) |
| **Stage 3: Aggregation** | Run POC aggregation pipeline (in-memory) | **3 times** | Time + Memory |

### What We Measure (Stage 3 - Aggregation)

```
START TIMING + MEMORY SAMPLING (100ms interval)
├── Load OCP parquet files from MinIO
├── Calculate node capacity
├── Aggregate pod usage (CPU, memory, labels)
├── Aggregate storage usage (PVC, PV)
├── Output formatting
└── PostgreSQL bulk COPY insert
END TIMING + MEMORY SAMPLING
```

### Memory Measurement (Industry Standard)

```python
# Continuous sampling during execution (not before/after)
import threading
import psutil
import time

peak_memory_mb = [0]
done = [False]

def memory_monitor():
    process = psutil.Process()
    while not done[0]:
        current = process.memory_info().rss / 1024 / 1024
        peak_memory_mb[0] = max(peak_memory_mb[0], current)
        time.sleep(0.1)  # Sample every 100ms

monitor_thread = threading.Thread(target=memory_monitor)
monitor_thread.start()

# Run aggregation
main()

done[0] = True
monitor_thread.join()
# peak_memory_mb[0] now contains true peak
```

### What We Do NOT Measure (in primary results)

- ❌ CSV generation (nise) - reported separately as "data prep time"
- ❌ CSV to Parquet conversion - reported separately as "data prep time"
- ❌ PostgreSQL schema creation (one-time setup)

### 🎯 Memory Target

| Metric | Value | Notes |
|--------|-------|-------|
| **Current Trino VMs** | 48 GB | Production baseline |
| **Target: Stay under** | 48 GB | No infra changes needed |
| **Expected at 1M rows** | ~4 GB | Based on OCP simplicity |
| **Projected max rows** | ~10M+ rows | Before hitting 48 GB limit |

**Success Criteria**: If 1M rows can be processed with < 48 GB memory, in-memory processing is sufficient.

### Warmup Protocol

Before each benchmark run:
1. **Cold start elimination**: Run one iteration (discarded) to warm up:
   - MinIO/S3 connections
   - PostgreSQL connection pool
   - Python JIT compilation
2. **Measured runs**: Next 3 iterations are recorded
3. **Report**: Median of 3 runs ± standard deviation

---

## ✅ Correctness Validation

After each benchmark scale, verify results:

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| **Row count** | `SELECT COUNT(*)` | Within ±1% of target |
| **No NULLs in required columns** | `SELECT COUNT(*) WHERE col IS NULL` | 0 rows |
| **Date range correct** | `SELECT DISTINCT usage_start` | 24 hourly rows |
| **Spot check** | Compare 3 random rows | Values match expected |

```sql
-- Validation queries
SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary;
SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary
  WHERE pod IS NULL OR namespace IS NULL;
SELECT DISTINCT DATE(usage_start) FROM org1234567.reporting_ocpusagelineitem_daily_summary;
```

---

## 📈 Expected Results

### Processing Time vs Output Rows

```mermaid
xychart-beta
    title "Processing Time vs Output Rows"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Time (seconds)" 0 --> 300
    bar "IN-MEMORY" [5, 12, 25, 60, 120, 250]
```

**Expected Pattern**: Linear scaling with data size

---

### Memory Usage vs Output Rows

```mermaid
xychart-beta
    title "Peak Memory Usage vs Output Rows"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Memory (MB)" 0 --> 4000
    bar "IN-MEMORY" [200, 400, 800, 1500, 2500, 4000]
```

**Expected Pattern**: Linear memory growth with data size

---

### Throughput

```mermaid
xychart-beta
    title "Throughput (rows/sec) vs Scale"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Rows/Second" 0 --> 5000
    line "IN-MEMORY" [4000, 4167, 4000, 4167, 4167, 4000]
```

**Expected Pattern**: Consistent throughput ~4000 rows/sec

---

## 📋 Results Table Template

### Summary Results (Median ± StdDev from 3 runs)

| Scale | Output Rows | Time (s) | Time StdDev | Memory (MB) | Memory StdDev | Throughput |
|-------|-------------|----------|-------------|-------------|---------------|------------|
| scale-20k | 20,160 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-50k | 50,400 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-100k | 100,080 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-250k | 250,800 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-500k | 500,640 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-1m | 1,000,800 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-1.5m | 1,500,480 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-2m | 1,999,200 | ___ | ±___ | ___ | ±___ | ___ rows/s |

### Memory Efficiency

| Scale | Output Rows | Memory (MB) | KB/row |
|-------|-------------|-------------|--------|
| scale-20k | 20,160 | ___ | ___ |
| scale-50k | 50,400 | ___ | ___ |
| scale-100k | 100,080 | ___ | ___ |
| scale-250k | 250,800 | ___ | ___ |
| scale-500k | 500,640 | ___ | ___ |
| scale-1m | 1,000,800 | ___ | ___ |
| scale-1.5m | 1,500,480 | ___ | ___ |
| scale-2m | 1,999,200 | ___ | ___ |

---

## 🔧 Test Data Generation

### Existing Manifests

Manifests already exist in `test-manifests/ocp-benchmarks/`:

| Scale | Manifest | Nodes | Pods/Node | Total Pods |
|-------|----------|-------|-----------|------------|
| 20k | `benchmark_ocp_20k.yml` | 5 | 84 | 420 |
| 50k | `benchmark_ocp_50k.yml` | 10 | 105 | 1,050 |
| 100k | `benchmark_ocp_100k.yml` | 15 | 139 | 2,085 |
| 250k | `benchmark_ocp_250k.yml` | 25 | 209 | 5,225 |
| 500k | `benchmark_ocp_500k.yml` | 35 | 298 | 10,430 |
| 1m | `benchmark_ocp_1m.yml` | 50 | 417 | 20,850 |

### Pre-generated Data Location

```
nise_benchmark_data/ocp-benchmarks/
├── scale-20k/
│   └── ocp/           # Pre-generated OCP parquet
├── scale-50k/
├── scale-100k/
├── scale-250k/
├── scale-500k/
├── scale-1m/
├── scale-1.5m/
└── scale-2m/
```

---

## 🚀 Execution Plan

### Phase 1: Data Preparation

1. ✅ Manifests already created (6 manifests in `test-manifests/ocp-benchmarks/`)
2. Generate test data (CSV) using nise - run once per scale
3. Convert to Parquet and upload to MinIO
4. Validate row counts are within ±1% tolerance

### Phase 2: Benchmark Execution

#### Automated Script (Unattended Run)

```bash
# Run all 6 benchmarks (3 runs each = 18 total runs)
./scripts/run_ocp_full_benchmarks.sh

# Run specific scale
./scripts/run_ocp_full_benchmarks.sh 100k
```

#### Manual Execution (Single Run)

```bash
# Activate environment
source venv/bin/activate

# Run via main entry point
python -c "from src.main import main; main()"
```

#### Metrics Captured Per Run

| Metric | Source | Unit |
|--------|--------|------|
| `total_time` | POC logs | seconds |
| `peak_memory` | Continuous sampling (100ms) | MB |
| `output_rows` | PostgreSQL query | count |
| `ocp_input_rows` | POC logs | count |
| `phase_timings` | POC logs (PerformanceTimer) | seconds |

### Phase 3: Analysis

1. Compile results into summary table (Markdown)
2. Calculate median and standard deviation for each scale
3. Generate Mermaid charts (update results document)
4. Calculate derived metrics:
   - Throughput: `output_rows / total_time`
   - Memory efficiency: `peak_memory / output_rows`
5. Compare with OCP-on-AWS results

---

## 🔥 Failure Recovery

### If a Benchmark Fails

1. **Check logs**:
   ```bash
   ls -la $BENCHMARK_DIR/${SCALE}_*.log
   tail -50 $BENCHMARK_DIR/${SCALE}_agg.log
   ```

2. **Verify infrastructure**:
   ```bash
   curl -s http://localhost:9000/minio/health/live
   podman exec postgres-poc psql -U koku -d koku -c "SELECT 1"
   ```

3. **Clean up**:
   ```bash
   rm -rf /tmp/ocp-benchmark-*
   ```

4. **Re-run single scale**:
   ```bash
   ./scripts/run_ocp_full_benchmarks.sh ${SCALE}
   ```

### Common Failure Modes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "MinIO not running" | Container stopped | `podman-compose up -d` |
| "PostgreSQL not running" | Container stopped | `podman-compose up -d` |
| OOM during nise | Disk full | Free disk space |
| Slow performance | Background processes | Kill other apps, restart containers |

---

## 📊 Comparison with OCP-on-AWS

### Expected Differences

| Metric | OCP-Only | OCP-on-AWS | Reason |
|--------|----------|------------|--------|
| **Time** | Baseline | +30-50% | AWS matching + JOIN overhead |
| **Memory** | Baseline | +20-40% | AWS data must be in memory |
| **Throughput** | Higher | Lower | No JOIN processing |

---

## 📁 Deliverables

1. **`OCP_BENCHMARK_RESULTS.md`** - Complete results with Mermaid charts (update existing)
2. **`benchmark_results/ocp_<timestamp>/`** - Raw logs and metrics
3. **`benchmark_results/ocp_<timestamp>/RESULTS.csv`** - Machine-readable results
4. **Updated `UNIFIED_PERFORMANCE_ANALYSIS.md`** - Comparison with OCP-on-AWS

---

## 📅 Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 1 | Pre-flight checklist + validate manifests | 30 min |
| 2 | Generate and prepare test data (6 scales) | 3 hours |
| 3 | Run benchmarks (6 scales × 3 runs = 18 runs) | 3 hours |
| 4 | Analyze results and generate report | 1 hour |
| **Total** | | **~7.5 hours** |

---

## 🎯 Success Criteria

- [ ] Pre-flight checklist completed
- [ ] Software versions documented
- [ ] All 18 benchmark runs complete without errors (6 scales × 3 runs)
- [ ] Results captured with median ± stddev
- [ ] Correctness validation passed for all scales
- [ ] Memory stays within 16 GB limit (local) / 48 GB (production target)
- [ ] Charts generated showing scaling behavior
- [ ] Clear comparison with OCP-on-AWS overhead documented

---

**Status**: Ready for execution
