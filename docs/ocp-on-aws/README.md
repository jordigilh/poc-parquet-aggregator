# OCP-on-AWS Aggregation

> **OpenShift usage matched with AWS costs for infrastructure attribution**

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

OCP-on-AWS mode matches OpenShift resources to AWS costs using:
- Resource ID matching (EC2 instances, EBS volumes)
- Tag matching (openshift_cluster, openshift_project, openshift_node)
- Storage matching (CSI volumes, PV names)

## Status

| Metric | Value |
|--------|-------|
| **E2E Scenarios** | 23/23 Passing ✅ |
| **Trino Parity** | 100% |

## Data Flow

```
S3/MinIO (Parquet)
      │
      ├── OCP Data ──┐
      │              ├──► POC Aggregator ──► PostgreSQL
      └── AWS Data ──┘
                │
                ├── Resource matching
                ├── Tag matching
                └── Cost attribution
```

## Key Tables

| Table | Description |
|-------|-------------|
| `reporting_ocpawscostlineitem_project_daily_summary_p` | Daily OCP-AWS matched costs |

## Running

```bash
# Required environment
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"
export OCP_CLUSTER_ID="my-cluster"

# Run aggregation
python -m src.main
```

## Documentation

| Document | Description |
|----------|-------------|
| **[MATCHING_LABELS.md](MATCHING_LABELS.md)** | Trino parity reference (resource/tag matching) |
| [Benchmark Plan](../benchmarks/OCP_ON_AWS_BENCHMARK_PLAN.md) | Performance methodology |
| [Benchmark Results](../benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) | Latest performance results |
| [Test Scenarios](../../test-manifests/ocp-on-aws/README.md) | E2E test cases (23 scenarios) |

## Scripts

```bash
# Run E2E tests
./scripts/run_ocp_aws_scenario_tests.sh --all

# Run benchmarks
./scripts/run_ocp_aws_benchmarks.sh
```
