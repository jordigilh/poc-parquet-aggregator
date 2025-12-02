# Scenario 03: Multi-Namespace Cost Distribution

## Overview

Tests that AWS costs are correctly distributed across multiple namespaces based on resource usage ratios.

## What This Tests

- Single EC2 instance running pods from multiple namespaces
- Cost distribution based on CPU/memory usage ratios
- Weighted distribution (default: 73% CPU / 27% memory)

## Test Data

**OCP:**
- 1 node with 8 CPU cores, 32 GB memory
- 3 namespaces:
  - `frontend`: 2 CPU cores, 8 GB memory (25% CPU, 25% memory)
  - `backend`: 4 CPU cores, 16 GB memory (50% CPU, 50% memory)
  - `monitoring`: 2 CPU cores, 8 GB memory (25% CPU, 25% memory)

**AWS:**
- EC2 cost: $100.00

## Expected Outcome

With weighted distribution (73% CPU / 27% memory):

| Namespace | CPU % | Mem % | Weighted % | Cost |
|-----------|-------|-------|------------|------|
| frontend | 25% | 25% | 25% | $25.00 |
| backend | 50% | 50% | 50% | $50.00 |
| monitoring | 25% | 25% | 25% | $25.00 |

```yaml
expected_outcome:
  total_cost: 100.00
  namespaces: 3
  namespace_costs:
    frontend: 25.00
    backend: 50.00
    monitoring: 25.00
```

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh 03
```

## Validation Query

```sql
SELECT 
    namespace,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2) as mem_gb_hours
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY namespace
ORDER BY cost DESC;
```

## Files

- `manifest.yml` - Main test manifest

