# Scenario 07: Partial Matching

## Overview

Tests handling when only some AWS resources match OCP workloads.

## What This Tests

- Some EC2 instances match OCP nodes (attributed)
- Some EC2 instances don't match (unattributed)
- Unmatched costs should NOT appear in output
- Only matched costs are distributed

## Test Data

**OCP:**
- Node with `resource_id: i-matched-001`
- No node with `i-unmatched-002`

**AWS:**
- EC2 `i-matched-001`: $50.00 (should be attributed)
- EC2 `i-unmatched-002`: $30.00 (should NOT appear)

## Expected Outcome

```yaml
expected_outcome:
  total_cost: 50.00  # Only matched costs
  unmatched_excluded: true
```

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh 07
```

## Validation Query

```sql
-- Should only see $50, not $80
SELECT 
    ROUND(SUM(unblended_cost)::numeric, 2) as total_attributed_cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Verify no unmatched resources appear
SELECT COUNT(*) 
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE resource_id LIKE '%unmatched%';
```

## Files

- `manifest.yml` - Main test manifest
- `variation.yml` - Different match ratios

