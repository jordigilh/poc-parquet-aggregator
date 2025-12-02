# Scenario 10: storage cost category

## Overview

See main [README](../README.md) for scenario overview.

## What Is Validated

| Validation | Check |
|------------|-------|
| Row count | Output rows match expected |
| CPU hours | `SUM(pod_usage_cpu_core_hours)` |
| Memory hours | `SUM(pod_usage_memory_gigabyte_hours)` |
| Namespace count | Matches expected |

## How to Run

```bash
# Generate test data
nise report ocp -s 2025-10-01 -e 2025-10-02 \
  --ocp-cluster-id test-cluster \
  -w test-manifests/ocp-only/10-storage-cost-category/manifest.yml

# Run aggregation
python src/main.py --ocp-only --ocp-provider-uuid $OCP_UUID --year 2025 --month 10

# Validate
python scripts/validate_ocp_totals.py \
  test-manifests/ocp-only/10-storage-cost-category/manifest.yml
```

## Validation Query

```sql
SELECT 
    COUNT(*) as rows,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 4) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 4) as memory_hours,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpusagelineitem_daily_summary_p;
```

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest |

See [main README](../README.md) for detailed validation methodology.
