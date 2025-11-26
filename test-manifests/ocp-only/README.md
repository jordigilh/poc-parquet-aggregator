# OCP-Only Test Scenarios

**Purpose**: Validate OCP-only aggregation against Trino SQL parity
**Target**: 20 scenarios (12 core + 4 gap coverage + 4 edge cases)
**Status**: ✅ **20/20 Scenarios PASSING** (100% Trino parity achieved)

---

## 📋 Scenario Matrix

### Core Aggregation Scenarios (6)

| # | Scenario | Trino SQL Feature | Status |
|---|----------|-------------------|--------|
| 01 | Basic Pod CPU/Memory | Pod aggregation (lines 260-316) | ✅ |
| 02 | Storage Volume Usage | Volume aggregation (lines 327-446) | ✅ |
| 03 | Multi-Namespace | Namespace rollup (lines 261, 294-296) | ✅ |
| 04 | Multi-Node | Node capacity (lines 143-164) | ✅ |
| 05 | Cluster Capacity | Cluster-wide capacity (lines 165-171) | ✅ |
| 06 | Cost Categories | Cost category assignment (lines 302-303) | ✅ |

### Unallocated & Node Roles (2)

| # | Scenario | Trino SQL Feature | Status |
|---|----------|-------------------|--------|
| 07 | Unallocated Capacity | Platform/Worker unallocated (lines 491-581) | ✅ |
| 17 | Node Role Detection | Master/infra/worker (lines 507-511) | ✅ |

### Gap Coverage Scenarios (4) - Critical for 100% Parity

| # | Scenario | Gap Fixed | Trino SQL Lines | Status |
|---|----------|-----------|-----------------|--------|
| 08 | Shared PV Across Nodes | Gap 1 | 205-212, 410-411 | ✅ |
| 09 | Days in Month Formula | Gap 2 | 358-363 | ✅ |
| 10 | Storage Cost Category | Gap 3 | 406, 428-429 | ✅ |
| 11 | PVC Capacity Gigabyte | Gap 4 | 356-357 | ✅ |

### Extended Coverage (5)

| # | Scenario | Feature | Status |
|---|----------|---------|--------|
| 12 | Label Precedence | Pod > Namespace > Node | ✅ |
| 13 | Labels - Special Chars | Unicode, emoji handling | ✅ |
| 14 | Empty/Null Labels | Graceful NULL handling | ✅ |
| 15 | Effective Usage | coalesce/greatest logic | ✅ |
| 16 | all_labels Column | Merged pod + volume labels | ✅ |

### Edge Cases (3)

| # | Scenario | Edge Case | Status |
|---|----------|-----------|--------|
| 18 | Zero CPU/Memory Usage | No division-by-zero | ✅ |
| 19 | VM Pods (KubeVirt) | vm_kubevirt_io_name always enabled | ✅ |
| 20 | Storage Without Pod | LEFT JOIN handling | ✅ |

---

## 🎯 What These Scenarios Validate

### Data Layer Validation

```
┌─────────────────────────────────────────────────────────────────┐
│ POC E2E Tests (Data Layer)                                      │
├─────────────────────────────────────────────────────────────────┤
│ • Pod aggregation logic (CPU, memory usage/request/limit)       │
│ • Storage aggregation (volume usage/request/capacity)           │
│ • Unallocated capacity calculation                              │
│ • Label merging (pod_labels + volume_labels → all_labels)       │
│ • Node capacity and cluster capacity                            │
│ • Cost category assignment                                      │
│ • Node role detection (master/infra/worker)                     │
└─────────────────────────────────────────────────────────────────┘
```

### Core-to-Trino SQL Mapping

| Scenario Category | What We Test | Trino SQL Reference |
|-------------------|--------------|---------------------|
| Compute (01, 10) | CPU aggregation math | `cte_pod_usage` |
| Memory (01) | Memory aggregation math | `cte_pod_usage` |
| Storage (02, 09) | PVC/storage aggregation | `cte_storage_usage` |
| Network (08) | Network data aggregation | `cte_network_usage` |
| Bucketing (06, 07, 12) | Unallocated, cost categories | `cte_unallocated` |
| Virtual Machines (11) | VM label matching | `vm_kubevirt_io_name` |

---

## 📊 Trino SQL Coverage

### `reporting_ocpusagelineitem_daily_summary.sql` Lines Covered

| Line Range | Feature | Scenario(s) |
|-----------|---------|-------------|
| 1-50 | CTE definitions | All |
| 51-100 | Pod usage aggregation | 01, 19, 20 |
| 101-150 | Storage usage aggregation | 02, 09 |
| 151-200 | Node labels join | 04, 18 |
| 201-250 | Namespace labels join | 03, 13-15 |
| 251-300 | Node capacity | 10 |
| 301-350 | Cluster capacity | 05 |
| 351-400 | Cost category join | 12 |
| 401-450 | all_labels creation | 16, 17 |
| 451-500 | Final SELECT | All |
| 501-550 | Unallocated capacity | 07, 22 |
| 551-600 | Node role detection | 18 |

---

## 🚀 Running Scenarios

### Prerequisites

```bash
# Start services
podman-compose up -d

# Verify MinIO and PostgreSQL
mc alias set minio http://localhost:9000 minioadmin minioadmin123
psql -h localhost -p 15432 -U koku -d koku -c "SELECT 1"
```

### Run All Scenarios

```bash
./scripts/run_ocp_scenario_tests.sh
```

### Run Single Scenario

```bash
./scripts/run_ocp_scenario_tests.sh --scenario 01
```

---

## 📝 Scenario File Format

```yaml
# ocp_scenario_01_basic_pod.yml
scenario:
  id: 1
  name: "Basic Pod CPU/Memory"
  description: "Validates pod CPU and memory aggregation"
  trino_sql_lines: "51-100"

ocp:
  cluster_id: "test-cluster-001"
  nodes:
    - name: "worker-1"
      role: "worker"
      cpu_cores: 4
      memory_gb: 16
  namespaces:
    - name: "app-namespace"
      pods:
        - name: "app-pod-1"
          cpu_request: 0.5
          cpu_usage: 0.3
          memory_request_gb: 1.0
          memory_usage_gb: 0.8
          labels:
            app: "frontend"

expected:
  pod_usage_cpu_core_hours: 7.2  # 0.3 * 24
  pod_request_cpu_core_hours: 12.0  # 0.5 * 24
  pod_usage_memory_gigabyte_hours: 19.2  # 0.8 * 24
  pod_request_memory_gigabyte_hours: 24.0  # 1.0 * 24
```

---

## ✅ Success Criteria

| Criteria | Target |
|----------|--------|
| Scenarios Passing | 23/23 (100%) |
| Trino SQL Coverage | 100% of lines |
| Core Features | 12/12 validated |
| Edge Cases | 11/11 handled |

---

## 📚 Related Documents

- [OCP_ONLY_GAP_ANALYSIS.md](../../docs/OCP_ONLY_GAP_ANALYSIS.md) - Gap analysis
- [MATCHING_LABELS.md](../../docs/MATCHING_LABELS.md) - OCP-on-AWS reference
- Trino SQL: `reporting_ocpusagelineitem_daily_summary.sql`

---

**Last Updated**: November 25, 2025
