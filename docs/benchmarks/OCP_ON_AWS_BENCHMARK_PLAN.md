# OCP-on-AWS Benchmark Plan

**Date**: November 26, 2025
**Status**: 🔄 **PENDING RE-RUN** (manifests updated to target input rows)
**Purpose**: Measure processing time and memory for OCP-on-AWS aggregation at production scale
**Note**: Scale names now refer to INPUT ROWS (combined OCP + AWS hourly data)

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

1. **Measure processing performance** at 8 scale points: 20K, 50K, 100K, 250K, 500K, 1M, 1.5M, 2M input rows
2. **Capture time and memory** for data processing + PostgreSQL insertion (NOT data generation)
3. **Generate reproducible benchmark results** with chart visualizations
4. **Validate memory stays within production limits** (target: < 32 GB)

---

## 📊 Benchmark Data Points

### Target Input Rows (OCP + AWS Combined)

Scale names refer to **INPUT ROWS** (combined OCP + AWS hourly data before aggregation).

| Scale ID | Target Input | Tolerance (±1%) | OCP Pods | Nodes | AWS Resources | Hours |
|----------|--------------|-----------------|----------|-------|---------------|-------|
| **scale-20k** | ~20,000 | 19,800 - 20,200 | 830 | 10 | 10 | 24 |
| **scale-50k** | ~50,000 | 49,500 - 50,500 | 2,080 | 20 | 20 | 24 |
| **scale-100k** | ~100,000 | 99,000 - 101,000 | 4,160 | 40 | 40 | 24 |
| **scale-250k** | ~250,000 | 247,500 - 252,500 | 10,400 | 100 | 100 | 24 |
| **scale-500k** | ~500,000 | 495,000 - 505,000 | 20,800 | 200 | 200 | 24 |
| **scale-1m** | ~1,000,000 | 990,000 - 1,010,000 | 41,600 | 400 | 400 | 24 |
| **scale-1.5m** | ~1,500,000 | 1,485,000 - 1,515,000 | 62,400 | 600 | 600 | 24 |
| **scale-2m** | ~2,000,000 | 1,980,000 - 2,020,000 | 83,200 | 800 | 800 | 24 |

### Scale Interpretation (Real-World Equivalents)

What does each scale represent in a production environment?

| Scale | Input Rows | Cluster Size | Use Case Example |
|-------|------------|--------------|------------------|
| **20k** | ~20,000 | 10 nodes, ~830 pods | Small OCP-on-AWS deployment |
| **50k** | ~50,000 | 20 nodes, ~2,080 pods | Medium production environment |
| **100k** | ~100,000 | 40 nodes, ~4,160 pods | Large enterprise deployment |
| **250k** | ~250,000 | 100 nodes, ~10,400 pods | Multi-cluster enterprise |
| **500k** | ~500,000 | 200 nodes, ~20,800 pods | Very large enterprise |
| **1m** | ~1,000,000 | 400 nodes, ~41,600 pods | Hyperscale platform |
| **1.5m** | ~1,500,000 | 600 nodes, ~62,400 pods | Major cloud provider scale |
| **2m** | ~2,000,000 | 800 nodes, ~83,200 pods | Maximum tested scale |

**Note**: Scale names refer to combined OCP + AWS hourly input rows.

### Input/Output Row Formula

```
Input Rows = (OCP Pods × 24 hours) + (AWS Resources × 24 hours)
Output Rows = Daily aggregated matched summaries (smaller than input)

Example for scale-20k:
  - OCP: 830 pods × 24 hours = 19,920 rows
  - AWS: 10 resources × 24 hours = 240 rows
  - Total input: ~20,160 rows ✓
  - Output: Aggregated by namespace/node/day
```

**Key Constraints**:
- Scale names refer to INPUT rows (combined OCP + AWS)
- Tolerance: ±1% of target input row count is acceptable
- 24-hour period (single day) for consistent hourly granularity

---

## 🔧 Processing Mode

### IN-MEMORY Processing

- Load all parquet files into memory at once
- Join OCP + AWS data in-memory
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
| **JOIN requirement** | AWS data must be fully loaded | ❌ Cannot chunk AWS side |
| **Code complexity** | Additional paths to maintain | ❌ Maintenance burden |

**Key insight**: OCP-on-AWS has an inherent memory floor because the AWS data must be fully loaded for JOIN operations. Streaming only chunks the OCP side, providing minimal memory benefit while adding significant processing overhead.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    OCP-on-AWS Memory Model                           │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────┐    JOIN    ┌─────────────────────────────────┐    │
│   │  OCP Chunk  │◄──────────►│  AWS Data (MUST be full)        │    │
│   │  (bounded)  │            │  - Resource IDs for matching    │    │
│   └─────────────┘            │  - Tags for attribution         │    │
│                              │  - Costs for calculation        │    │
│                              └─────────────────────────────────┘    │
│                                                                      │
│   Memory = OCP_chunk + AWS_full + intermediate_results + output     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

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
| **Step 2** | `aws_load_time` | Time to load AWS parquet from MinIO |
| **Step 3** | `resource_match_time` | Time for resource ID matching |
| **Step 4** | `tag_match_time` | Time for tag-based matching |
| **Step 5** | `disk_capacity_time` | Time for disk capacity calculation |
| **Step 6** | `attribution_time` | Time for cost attribution |
| **Step 7** | `format_time` | Time for output formatting |
| **Step 8** | `db_write_time` | Time for PostgreSQL COPY |
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

### Hardware (MacBook - Consistent with OCP-only benchmarks)

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

| Scale | OCP CSV (est.) | AWS CSV (est.) | Parquet (est.) | Working Space | Recommended Free |
|-------|----------------|----------------|----------------|---------------|------------------|
| 20k | ~50 MB | ~30 MB | ~20 MB | ~200 MB | 1 GB |
| 50k | ~125 MB | ~75 MB | ~50 MB | ~500 MB | 2 GB |
| 100k | ~250 MB | ~150 MB | ~100 MB | ~1 GB | 3 GB |
| 250k | ~625 MB | ~375 MB | ~250 MB | ~2.5 GB | 5 GB |
| 500k | ~1.25 GB | ~750 MB | ~500 MB | ~5 GB | 10 GB |
| 1m | ~2.5 GB | ~1.5 GB | ~1 GB | ~10 GB | 15 GB |

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
- [ ] Disk has ≥15 GB free space (`df -h`)
- [ ] Previous benchmark data cleaned up (`rm -rf /tmp/ocp-aws-benchmark-*`)
- [ ] Virtual environment activated (`source venv/bin/activate`)
- [ ] MinIO is running and accessible
- [ ] PostgreSQL is running and accessible
- [ ] Software versions documented

### Top-Level Stage Breakdown

Each benchmark run captures **time and memory** for three distinct stages:

| Stage | Description | Runs Per Scale | Measured |
|-------|-------------|----------------|----------|
| **Stage 1: Nise Generation** | Generate synthetic OCP + AWS CSV data using nise | **Once** | Time (reported separately) |
| **Stage 2: Parquet Transform** | Convert CSV to Parquet and upload to MinIO | **Once** | Time (reported separately) |
| **Stage 3: Aggregation** | Run POC aggregation pipeline (in-memory) | **3 times** | Time + Memory |

### What We Measure (Stage 3 - Aggregation)

```
START TIMING + MEMORY SAMPLING (100ms interval)
├── Load OCP parquet files from MinIO
├── Load AWS parquet files from MinIO
├── Resource ID matching (OCP ↔ AWS)
├── Tag matching (openshift_cluster, openshift_project, etc.)
├── Cost attribution (compute, storage, network)
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
| **Production VM** | 32 GB | Target production environment |
| **Target: Stay under** | 32 GB | No infra changes needed |
| **Expected at 2M input rows** | ~6 GB | Based on actual benchmarks |
| **Projected max input rows** | ~10M rows | Before hitting 32 GB limit |

**Success Criteria**: If 2M input rows can be processed with < 32 GB memory, in-memory processing is sufficient.

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
| **AWS costs present** | `SELECT SUM(infrastructure_cost)` | > 0 |
| **Spot check** | Compare 3 random rows | Values match expected |

```sql
-- Validation queries
SELECT COUNT(*) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
SELECT COUNT(*) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
  WHERE pod IS NULL OR namespace IS NULL;
SELECT DISTINCT DATE(usage_start) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
SELECT SUM(infrastructure_cost) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
```

---

## 📈 Expected Results

### Processing Time vs Output Rows

```mermaid
xychart-beta
    title "Processing Time vs Output Rows"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Time (seconds)" 0 --> 700
    bar "IN-MEMORY" [15, 35, 80, 180, 350, 600]
```

**Expected Pattern**: Linear scaling with data size

---

### Memory Usage vs Output Rows

```mermaid
xychart-beta
    title "Peak Memory Usage vs Output Rows"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Memory (MB)" 0 --> 12000
    bar "IN-MEMORY" [400, 800, 1500, 3500, 6000, 12000]
```

**Expected Pattern**: Linear memory growth with data size (~10 MB per 1K rows)

---

### Throughput

```mermaid
xychart-beta
    title "Throughput (rows/sec) vs Scale"
    x-axis "Output Rows" [20K, 50K, 100K, 250K, 500K, 1M]
    y-axis "Rows/Second" 0 --> 3000
    line "IN-MEMORY" [1333, 1429, 1250, 1389, 1429, 1667]
```

**Expected Pattern**: Consistent throughput ~1300-1700 rows/sec

---

## 📋 Results Table Template

### Summary Results (Median ± StdDev from 3 runs)

| Scale | Input Rows | Time (s) | Time StdDev | Memory (MB) | Memory StdDev | Throughput |
|-------|------------|----------|-------------|-------------|---------------|------------|
| scale-20k | ~20,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-50k | ~50,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-100k | ~100,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-250k | ~250,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-500k | ~500,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-1m | ~1,000,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-1.5m | ~1,500,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |
| scale-2m | ~2,000,000 | ___ | ±___ | ___ | ±___ | ___ rows/s |

### Memory Efficiency

| Scale | Input Rows | Memory (MB) | KB/row |
|-------|------------|-------------|--------|
| scale-20k | ~20,000 | ___ | ___ |
| scale-50k | ~50,000 | ___ | ___ |
| scale-100k | ~100,000 | ___ | ___ |
| scale-250k | ~250,000 | ___ | ___ |
| scale-500k | ~500,000 | ___ | ___ |
| scale-1m | ~1,000,000 | ___ | ___ |
| scale-1.5m | ~1,500,000 | ___ | ___ |
| scale-2m | ~2,000,000 | ___ | ___ |

---

## 🔧 Test Data Generation

### Data Generator Configuration

Each scale requires a specific nise manifest to generate the right data volume.

```yaml
# Template for scale-100k
ocp:
  generators:
  - OCPGenerator:
      start_date: '2025-10-01'
      end_date: '2025-10-02'
      nodes:
      - node_name: node-{1..50}  # 50 nodes
        cpu_cores: 8
        memory_gig: 32
        namespaces:
          app-{1..42}:  # ~42 pods per node = 2,083 pods
            pods:
            - pod_name: pod-{1..n}
              pod_seconds: 3600

aws:
  generators:
  - EC2Generator:
      resource_id: 'i-node-{1..50}'
      instance_type:
        inst_type: m5.xlarge
```

### Pre-generated Data Location

```
nise_benchmark_data/ocp-aws-benchmarks/
├── scale-20k/
│   ├── ocp/           # Pre-generated OCP parquet
│   └── aws/           # Pre-generated AWS parquet
├── scale-50k/
├── scale-100k/
├── scale-250k/
├── scale-500k/
└── scale-1m/
```

---

## 🚀 Execution Plan

### Phase 1: Data Preparation

1. Create/validate nise manifests for each scale (6 manifests)
2. Generate test data (CSV) using nise - run once per scale
3. Convert to Parquet and upload to MinIO
4. Validate row counts are within ±1% tolerance

### Phase 2: Benchmark Execution

#### Automated Script (Unattended Run)

```bash
# Run all 6 benchmarks (3 runs each = 18 total runs)
./scripts/run_ocp_aws_benchmarks.sh

# Run specific scale
./scripts/run_ocp_aws_benchmarks.sh scale-100k
```

#### Manual Execution (Single Run)

```bash
# Activate environment
source venv/bin/activate

# Set required environment variables
export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"

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
| `aws_input_rows` | POC logs | count |
| `phase_timings` | POC logs (PerformanceTimer) | seconds |

### Phase 3: Analysis

1. Compile results into summary table (Markdown)
2. Calculate median and standard deviation for each scale
3. Generate Mermaid charts (update results document)
4. Calculate derived metrics:
   - Throughput: `output_rows / total_time`
   - Memory efficiency: `peak_memory / output_rows`
5. Compare with OCP-only results

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
   rm -rf /tmp/ocp-aws-benchmark-*
   ```

4. **Re-run single scale**:
   ```bash
   ./scripts/run_ocp_aws_benchmarks.sh ${SCALE}
   ```

### Common Failure Modes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "MinIO not running" | Container stopped | `podman-compose up -d` |
| "PostgreSQL not running" | Container stopped | `podman-compose up -d` |
| OOM during nise | Disk full or too much data | Free disk space, reduce scale |
| Slow performance | Background processes | Kill other apps, restart containers |
| AWS data missing | Wrong provider UUID | Check `AWS_PROVIDER_UUID` matches S3 path |

---

## 📊 Comparison with OCP-only

### Expected Differences

| Metric | OCP-Only | OCP-on-AWS | Reason |
|--------|----------|------------|--------|
| **Time** | Baseline | +30-50% | AWS matching + JOIN overhead |
| **Memory** | Baseline | +20-40% | AWS data must be in memory |
| **Throughput** | Higher | Lower | More complex processing |

**Note**: OCP-on-AWS includes additional processing steps:
- AWS CUR file parsing
- Resource ID matching
- Tag matching (openshift_cluster, openshift_project, etc.)
- Multi-table cost attribution (compute, storage, network)

---

## 📁 Deliverables

1. **`OCP_ON_AWS_BENCHMARK_RESULTS.md`** - Complete results with Mermaid charts (update existing)
2. **`benchmark_results/ocp_aws_<timestamp>/`** - Raw logs and metrics
3. **`benchmark_results/ocp_aws_<timestamp>/RESULTS.csv`** - Machine-readable results
4. **Updated `UNIFIED_PERFORMANCE_ANALYSIS.md`** - Comparison with OCP-only

---

## 📅 Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 1 | Pre-flight checklist + validate manifests | 30 min |
| 2 | Generate and prepare test data (6 scales) | 4 hours |
| 3 | Run benchmarks (6 scales × 3 runs = 18 runs) | 4 hours |
| 4 | Analyze results and generate report | 1 hour |
| **Total** | | **~9.5 hours** |

---

## 🎯 Success Criteria

- [ ] Pre-flight checklist completed
- [ ] Software versions documented
- [ ] All 24 benchmark runs complete without errors (8 scales × 3 runs)
- [ ] Results captured with median ± stddev
- [ ] Correctness validation passed for all scales
- [ ] Memory stays within 32 GB limit
- [ ] Charts generated showing scaling behavior
- [ ] Clear comparison with OCP-only documented

---

**Status**: Ready for execution
