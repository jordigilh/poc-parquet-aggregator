# POC Architecture: Parquet-Based Cost Aggregation

> **Purpose**: Technical architecture for replacing Trino + Hive with custom Python aggregation
> **Audience**: Development team, architects, operations
> **Version**: 2.0 (OCP + OCP-on-AWS)
> **Status**: ✅ Production-Ready POC

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Supported Modes](#supported-modes)
4. [Component Details](#component-details)
5. [Data Flow](#data-flow)
6. [Performance Characteristics](#performance-characteristics)
7. [Scaling Strategies](#scaling-strategies)
8. [Deployment](#deployment)
9. [Migration Strategy](#migration-strategy)

---

## Executive Summary

This POC replaces **Trino + Hive** with a custom Python aggregation layer that:

- ✅ Reads Parquet files directly from S3/MinIO
- ✅ Performs all aggregation logic in Python/Pandas
- ✅ Writes results directly to PostgreSQL
- ✅ Supports both **OCP-only** and **OCP-on-AWS** workloads
- ✅ Achieves **100% Trino parity** (43 test scenarios passing: 20 OCP + 23 OCP-on-AWS)

### Key Benefits

- **Fewer components**: Removes Trino, Hive Metastore, and Metastore DB
- **Simpler operations**: Single Python process instead of distributed JVM services
- **Direct writes**: S3 → Aggregator → PostgreSQL (no intermediate storage)
- **Self-contained**: No external query engine dependencies

---

## Architecture Overview

### Before: Trino + Hive

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Current Architecture (Trino)                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   S3 ◄──► Trino ◄──► Hive Metastore ◄──► Metastore DB (PostgreSQL)     │
│              │                                                          │
│              ▼                                                          │
│   OCP-only:    Trino → Hive/S3 (summary) → MASU → PostgreSQL           │
│   OCP-on-AWS:  Trino → PostgreSQL (direct via postgres connector)      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### After: POC Aggregator

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          New Architecture                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   S3/MinIO ──► POC Aggregator (Python) ──► PostgreSQL                  │
│                      │                                                  │
│                      ├── PyArrow (Parquet reading)                     │
│                      ├── Pandas (Aggregation)                          │
│                      ├── psycopg2 (DB writes)                          │
│                      └── s3fs (S3 access)                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Supported Modes

### 1. OCP-Only Aggregation

Aggregates OpenShift Container Platform metrics without cloud cost matching.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          OCP-Only Mode                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   OCP Parquet ──► PodAggregator ──► PostgreSQL                         │
│       │                                                                 │
│       ├── Pod usage (CPU, memory)                                      │
│       ├── Node capacity                                                 │
│       ├── Namespace labels                                              │
│       └── Storage usage                                                 │
│                                                                         │
│   Output: reporting_ocpusagelineitem_daily_summary                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Streaming Support**: ⚠️ Available but [not recommended](../benchmarks/OCP_BENCHMARK_PLAN.md#why-not-streaming)

---

### 2. OCP-on-AWS Aggregation

Matches OCP resources to AWS costs and attributes cloud spending.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        OCP-on-AWS Mode                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   OCP Parquet ──┬──► ResourceMatcher ──► TagMatcher ──► CostAttributor │
│                 │           │                              │            │
│   AWS Parquet ──┘           ▼                              ▼            │
│                        Matched Data                   Attributed Costs  │
│                             │                              │            │
│                             └──────────────┬───────────────┘            │
│                                            ▼                            │
│                                      PostgreSQL                         │
│                                                                         │
│   Output: reporting_ocpawscostlineitem_project_daily_summary_p         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Streaming Support**: ❌ Not applicable ([JOIN requires full data in memory](../benchmarks/OCP_ON_AWS_BENCHMARK_PLAN.md#why-not-streaming))

---

## Component Details

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| `ParquetReader` | `src/parquet_reader.py` | Read Parquet from S3/MinIO |
| `PodAggregator` | `src/aggregator_pod.py` | OCP-only aggregation |
| `OCPAWSAggregator` | `src/aggregator_ocp_aws.py` | OCP-on-AWS aggregation |
| `DBWriter` | `src/db_writer.py` | PostgreSQL writes |

### OCP-on-AWS Specific

| Component | File | Purpose |
|-----------|------|---------|
| `ResourceMatcher` | `src/resource_matcher.py` | EC2/EBS resource ID matching |
| `TagMatcher` | `src/tag_matcher.py` | OpenShift tag matching |
| `CostAttributor` | `src/cost_attributor.py` | Cost attribution logic |
| `DiskCapacityCalculator` | `src/disk_capacity_calculator.py` | Storage capacity calculation |
| `NetworkCostHandler` | `src/network_cost_handler.py` | Network cost detection |

### Supporting Components

| Component | File | Purpose |
|-----------|------|---------|
| `StreamingProcessor` | `src/streaming_processor.py` | Chunk-based processing |
| `StreamingSelector` | `src/streaming_selector.py` | Auto-select processing mode |

---

## Data Flow

### OCP-on-AWS Processing Pipeline

```
1. LOAD DATA
   ├── Load OCP Parquet (pod usage, storage, node capacity)
   └── Load AWS Parquet (CUR line items)

2. RESOURCE MATCHING
   ├── EC2 Instance ID → Node (suffix match)
   ├── EBS Volume ID → CSI Handle (substring match)
   └── EBS Volume ID → PV Name (suffix match)

3. TAG MATCHING
   ├── openshift_cluster → cluster_id OR cluster_alias
   ├── openshift_project → namespace
   ├── openshift_node → node
   └── Generic tags → pod_labels OR volume_labels

4. COST ATTRIBUTION
   ├── Compute: pod_ratio × node_cost
   ├── Storage (CSI): pvc_ratio × disk_cost
   ├── Storage (non-CSI): full cost → namespace
   └── Network: data_transfer → unattributed

5. OUTPUT
   └── Write to PostgreSQL (reporting_ocpawscostlineitem_project_daily_summary_p)
```

---

## Performance Characteristics

### OCP-on-AWS Benchmarks (In-Memory)

Results from 3 runs per scale (median values). See [benchmark results](../benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) for full details.

| Scale | Input Rows | Output Rows | Time | Memory | Throughput |
|-------|------------|-------------|------|--------|------------|
| 20k | ~20,000 | 19,920 | 7.99s | 381 MB | 2,493 r/s |
| 100k | ~100,000 | 99,840 | 34.10s | 1,108 MB | 2,927 r/s |
| 500k | ~500,000 | 499,200 | 166.84s | 4,188 MB | 2,992 r/s |
| 1m | ~1,000,000 | 998,400 | 334.29s | 6,862 MB | 2,986 r/s |
| 2m | ~2,000,000 | 1,996,800 | 640.26s | 7,326 MB | 3,118 r/s |

**Memory Scaling**: ~4-7 MB per 1K input rows at production scale

### OCP-Only Benchmarks (In-Memory)

OCP-only is simpler (no JOIN) and uses less memory. See [benchmark results](../benchmarks/OCP_BENCHMARK_RESULTS.md) for full details.

| Scale | Input Rows | Output Rows | Time | Memory | Throughput |
|-------|------------|-------------|------|--------|------------|
| 20k | ~20,000 | 830 | 4.35s | 328 MB | 191 r/s |
| 100k | ~100,000 | 4,160 | 15.60s | 839 MB | 267 r/s |
| 500k | ~500,000 | 20,800 | 72.04s | 3,689 MB | 289 r/s |
| 1m | ~1,000,000 | 41,600 | 139.67s | 7,171 MB | 298 r/s |
| 2m | ~2,000,000 | 83,200 | 282.76s | 10,342 MB | 294 r/s |

**Memory Scaling**: ~5-7 MB per 1K input rows at production scale

---

## Scaling Strategies

### 1. Horizontal Scaling (Across Clusters)

Partition workload by OCP cluster - each cluster processed independently.

```
┌─────────────────────────────────────────────────────────────────────────┐
│   Orchestrator (K8s Job Controller)                                    │
│   └── Spawns one job per cluster                                       │
│                                                                         │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐      ┌─────────┐              │
│   │ Job 1   │  │ Job 2   │  │ Job 3   │ ...  │ Job N   │              │
│   │ ClusterA│  │ ClusterB│  │ ClusterC│      │ ClusterN│              │
│   └────┬────┘  └────┬────┘  └────┬────┘      └────┬────┘              │
│        └────────────┴────────────┴────────────────┘                    │
│                              │                                          │
│                              ▼                                          │
│                      ┌─────────────┐                                   │
│                      │ PostgreSQL  │                                   │
│                      └─────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2. Time-Based Partitioning (Large Clusters)

For clusters exceeding memory limits, process hour-by-hour.

```
Instead of:  Load 24 hours → JOIN → Output

Do this:     For each hour:
             ├── Load 1 hour of OCP
             ├── Load 1 hour of AWS
             ├── JOIN → Output
             └── Free memory, next hour

Memory reduction: ~24x
```

### 3. Streaming Mode (OCP-Only)

For OCP-only workloads, streaming provides memory-bounded processing:

```python
# Process in chunks
for chunk in parquet_reader.stream(chunk_size=50000):
    result = aggregator.process_chunk(chunk)
    db_writer.write_chunk(result)
    # Memory freed after each chunk
```

**Note**: Streaming has limited benefit for OCP-on-AWS due to JOIN requirements.

---

## Deployment

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ocp-parquet-aggregator
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: aggregator
        image: quay.io/cloudservices/ocp-parquet-aggregator:latest
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "8Gi"
            cpu: "4000m"
        env:
        - name: S3_ENDPOINT
          value: "https://s3.amazonaws.com"
        - name: POSTGRES_HOST
          valueFrom:
            secretKeyRef:
              name: postgres-credentials
              key: host
```

### Configuration

```yaml
# config/config.yaml
cost:
  distribution:
    method: cpu  # cpu, memory, or weighted

performance:
  max_workers: 4
  use_streaming: false  # Enable for OCP-only large datasets
  chunk_size: 100000
  use_bulk_copy: true
```

---

## Migration Strategy

### Phase 1: Parallel Run (1-2 months)

1. Deploy POC alongside Trino
2. Process same data through both paths
3. Compare results daily
4. Monitor for discrepancies

### Phase 2: Feature Flag Cutover

```python
if feature_flags.use_custom_aggregator(provider_type):
    run_parquet_aggregator(provider_uuid)
else:
    run_trino_aggregation(provider_uuid)
```

### Phase 3: Decommission Trino

1. Disable Trino path via feature flag
2. Monitor for 2 weeks
3. Remove Trino/Hive infrastructure
4. Clean up code

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [OCP-only MATCHING_LABELS](../ocp-only/MATCHING_LABELS.md) | OCP-only resource/tag matching reference |
| [OCP-on-AWS MATCHING_LABELS](../ocp-on-aws/MATCHING_LABELS.md) | OCP-on-AWS resource/tag matching reference |
| [OCP Benchmark Results](../benchmarks/OCP_BENCHMARK_RESULTS.md) | OCP-only performance results |
| [OCP-on-AWS Benchmark Results](../benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) | OCP-on-AWS performance results |

---

*Document Version: 2.0*
*Last Updated: November 27, 2025*
*POC Status: Production-Ready*
