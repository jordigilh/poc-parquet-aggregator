# Scenario 15: rds datauase costs

## Overview

See main [README](../README.md) for scenario overview.

## What Is Validated

| Validation | Check |
|------------|-------|
| Total cost | `SUM(unblended_cost)` matches expected |
| Row count | Within expected range |
| Namespace count | Matches expected |

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh

# Or validate directly
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/15-rds-database-costs/manifest.yml
```

## Validation Query

```sql
SELECT 
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
```

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest |

See [main README](../README.md) for detailed validation methodology.
