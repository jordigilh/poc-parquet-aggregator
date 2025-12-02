# Scenario 06: Multi-Cluster

## Overview

Tests cost attribution when multiple OCP clusters run on the same AWS account.

## What This Tests

- Multiple cluster IDs in OCP data
- Each cluster has unique resource IDs
- AWS costs correctly attributed to respective clusters
- No cross-cluster cost leakage

## Test Data

**OCP:**
- Cluster Alpha: `cluster-alpha-001`
  - Node: `i-alpha-node-001`
  - Namespace: `alpha-app`
- Cluster Beta: `cluster-beta-001`
  - Node: `i-beta-node-001`
  - Namespace: `beta-app`

**AWS:**
- EC2 for Alpha: $50.00
- EC2 for Beta: $30.00

## Expected Outcome

```yaml
expected_outcome:
  total_cost: 80.00
  clusters: 2
  cluster_costs:
    cluster-alpha-001: 50.00
    cluster-beta-001: 30.00
```

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh 06
```

## Validation Query

```sql
SELECT 
    cluster_id,
    COUNT(DISTINCT namespace) as namespaces,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY cluster_id
ORDER BY cluster_id;
```

## Files

- `manifest.yml` - Main test manifest (multi-cluster)
- `variation.yml` - Different cluster configurations

