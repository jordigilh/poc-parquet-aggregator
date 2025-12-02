# OCP-Only Test Scenarios

This directory contains test scenarios for validating the OCP-only cost aggregation pipeline. These scenarios test OpenShift pod and storage aggregation without AWS cost attribution.

## Quick Start

### Prerequisites

1. Start the required containers:
   ```bash
   cd /path/to/poc-parquet-aggregator
   podman-compose up -d
   ```

2. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

### Running a Single Scenario

```bash
# Run scenario 01 (Basic Pod)
python src/main.py --ocp-only --manifest test-manifests/ocp-only/01-basic-pod/manifest.yml
```

### Running All Scenarios

```bash
./scripts/run_ocp_scenario_tests.sh
```

---

## Validation Methodology

### How E2E Validation Works (Core-Style)

The POC uses a **totals-based validation approach** similar to OCP-on-AWS:

1. **Row Count** - Number of aggregated output rows
2. **CPU/Memory Totals** - Sum of usage and request hours
3. **Storage Totals** - PVC capacity and usage
4. **Namespace Count** - Number of unique namespaces in output

### Key Difference from OCP-on-AWS

OCP-only aggregation produces **daily summaries** (24:1 compression ratio):
- Input: Hourly pod usage data (24 rows per pod per day)
- Output: Daily aggregated summaries (1 row per pod/namespace/node per day)

### Validation Script

The primary validation script is [`scripts/validate_ocp_totals.py`](../../scripts/validate_ocp_totals.py):

```sql
-- Core validation query for OCP-only
SELECT
    COUNT(*) as total_rows,
    COUNT(DISTINCT namespace) as namespaces,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 4) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 4) as memory_gb_hours
FROM {schema}.reporting_ocpusagelineitem_daily_summary_p;
```

---

## Scenario Overview

### Phase 1: Core Functionality (5 scenarios)

| # | Scenario | Description |
|---|----------|-------------|
| 01 | [Basic Pod](./01-basic-pod/) | Single pod aggregation |
| 02 | [Storage Volume](./02-storage-volume/) | PVC/PV aggregation |
| 03 | [Multi-Namespace](./03-multi-namespace/) | Multiple namespaces |
| 04 | [Multi-Node](./04-multi-node/) | Pods across multiple nodes |
| 05 | [Cluster Capacity](./05-cluster-capacity/) | Node capacity calculations |

### Phase 2: Cost Categories & Capacity (5 scenarios)

| # | Scenario | Description |
|---|----------|-------------|
| 06 | [Cost Category](./06-cost-category/) | Namespace cost category mapping |
| 07 | [Unallocated Capacity](./07-unallocated-capacity/) | Unused cluster resources |
| 08 | [Shared PV Nodes](./08-shared-pv-nodes/) | PVs shared across nodes |
| 09 | [Days in Month](./09-days-in-month/) | Month boundary handling |
| 10 | [Storage Cost Category](./10-storage-cost-category/) | Storage with cost categories |

### Phase 3: Labels & Edge Cases (5 scenarios)

| # | Scenario | Description |
|---|----------|-------------|
| 11 | [PVC Capacity GB](./11-pvc-capacity-gb/) | PVC capacity calculations |
| 12 | [Label Precedence](./12-label-precedence/) | Pod > Namespace > Node label merge |
| 13 | [Labels Special Chars](./13-labels-special-chars/) | Special characters in labels |
| 14 | [Empty Labels](./14-empty-labels/) | Handling empty/null labels |
| 15 | [Effective Usage](./15-effective-usage/) | MAX(usage, request) calculation |

### Phase 4: Advanced Scenarios (5 scenarios)

| # | Scenario | Description |
|---|----------|-------------|
| 16 | [All Labels](./16-all-labels/) | Combined pod + volume labels |
| 17 | [Node Roles](./17-node-roles/) | Worker/master/infra nodes |
| 18 | [Zero Usage](./18-zero-usage/) | Pods with zero resource usage |
| 19 | [VM Pods](./19-vm-pods/) | KubeVirt VM pods |
| 20 | [Storage No Pod](./20-storage-no-pod/) | Storage without associated pods |

---

## Directory Structure

Each scenario directory contains:

```
XX-scenario-name/
├── README.md           # Scenario description and validation details
└── manifest.yml        # Test manifest (nise format)
```

---

## What Each Scenario Validates

| Scenario | Primary Validation | Secondary Validation |
|----------|-------------------|---------------------|
| 01 Basic Pod | Row count, CPU/memory hours | Daily aggregation |
| 02 Storage Volume | PVC capacity, storage class | Volume labels |
| 03 Multi-Namespace | Namespace count | Per-namespace totals |
| 04 Multi-Node | Node count | Per-node capacity |
| 05 Cluster Capacity | Cluster totals | Node vs cluster capacity |
| 06 Cost Category | cost_category_id assigned | Namespace matching |
| 07 Unallocated | Unallocated rows exist | Capacity - usage |
| 08-20 | Various edge cases | Specific to scenario |

---

## Running Validation Manually

### Step 1: Generate Test Data

```bash
nise report ocp \
  -s 2025-10-01 -e 2025-10-02 \
  --ocp-cluster-id test-cluster \
  -w test-manifests/ocp-only/01-basic-pod/manifest.yml
```

### Step 2: Upload to MinIO

```bash
python scripts/csv_to_parquet_minio.py \
  --input-dir ./generated-data \
  --bucket cost-usage
```

### Step 3: Run Aggregation

```bash
python src/main.py \
  --ocp-only \
  --ocp-provider-uuid $OCP_UUID \
  --year 2025 --month 10
```

### Step 4: Validate

```bash
python scripts/validate_ocp_totals.py \
  test-manifests/ocp-only/01-basic-pod/manifest.yml
```

---

## Validation Queries

### Row Count and Totals

```sql
SELECT 
    COUNT(*) as rows,
    COUNT(DISTINCT namespace) as namespaces,
    COUNT(DISTINCT node) as nodes,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 4) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 4) as memory_hours
FROM org1234567.reporting_ocpusagelineitem_daily_summary_p;
```

### Per-Namespace Breakdown

```sql
SELECT 
    namespace,
    COUNT(*) as rows,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 4) as cpu_hours
FROM org1234567.reporting_ocpusagelineitem_daily_summary_p
GROUP BY namespace
ORDER BY namespace;
```

### Storage Validation

```sql
SELECT 
    namespace,
    persistentvolumeclaim,
    ROUND(persistentvolumeclaim_capacity_gigabyte::numeric, 2) as capacity_gb
FROM org1234567.reporting_ocpusagelineitem_daily_summary_p
WHERE data_source = 'Storage';
```

---

## Related Documentation

- [OCP-on-AWS Scenarios](../ocp-on-aws/)
- [Benchmark Results](../../docs/benchmarks/OCP_BENCHMARK_RESULTS.md)
- [Architecture Overview](../../docs/architecture/)
- [Validation Script](../../scripts/validate_ocp_totals.py)

