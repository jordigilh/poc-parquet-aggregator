# OCP-Only Aggregation

> **OpenShift pod and storage usage aggregation without cloud provider integration**

## Table of Contents

1. [Overview](#overview)
2. [Status](#status)
3. [Data Flow](#data-flow)
4. [Key Tables](#key-tables)
5. [Running](#running)
6. [Documentation](#documentation)
7. [Scripts](#scripts)

---

## Overview

OCP-only mode aggregates OpenShift usage data directly from Parquet files:
- Pod CPU/memory usage and requests
- Storage volume usage and capacity
- Unallocated cluster capacity
- Node role detection (master/infra/worker)

## Status

| Metric | Value |
|--------|-------|
| **E2E Scenarios** | 20/20 Passing ✅ |
| **Trino Parity** | 100% |

## Data Flow

```
S3/MinIO (Parquet) → POC Aggregator → PostgreSQL
                          │
                          ├── Pod aggregation
                          ├── Storage aggregation
                          └── Unallocated capacity
```

## Key Tables

| Table | Description |
|-------|-------------|
| `reporting_ocpusagelineitem_daily_summary` | Daily pod/storage usage |

## Running

```bash
# Required environment
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export OCP_CLUSTER_ID="my-cluster"

# Run aggregation
python -m src.main
```

## Documentation

| Document | Description |
|----------|-------------|
| **[MATCHING_LABELS.md](MATCHING_LABELS.md)** | Trino parity reference (36/36 features) |
| [Benchmark Plan](../benchmarks/OCP_BENCHMARK_PLAN.md) | Performance methodology |
| [Test Scenarios](../../test-manifests/ocp-only/README.md) | E2E test cases (20 scenarios) |

## Scripts

```bash
# Run E2E tests
./scripts/run_ocp_scenario_tests.sh

# Run benchmarks
./scripts/run_ocp_full_benchmarks.sh
```

