# Scenario 14: SavingsPlan Costs

## Overview

Tests handling of AWS SavingsPlan cost types. SavingsPlans provide discounted pricing, and the POC must correctly attribute the `savingsplan_effective_cost` column instead of `unblended_cost`.

## What This Tests

- Detection of SavingsPlan coverage in AWS data
- Use of `savingsplan_effective_cost` for attribution
- Correct handling when SavingsPlan partially covers costs
- Validation uses amortized cost instead of unblended

## Test Data

**OCP:**
- 1 cluster with compute workloads
- Standard pod resource usage

**AWS:**
- EC2 costs with SavingsPlan coverage
- `unblended_cost`: $100.00 (on-demand price)
- `savingsplan_effective_cost`: $70.00 (discounted price)

## Expected Outcome

```yaml
expected_outcome:
  total_amortized_cost: 70.00  # Uses SavingsPlan cost, not unblended
  savingsplan_applied: true
```

---

## Validation Details

### What Is Validated

| Validation | Expected | Query/Check |
|------------|----------|-------------|
| Total cost | $70.00 ± $0.10 | `SUM(savingsplan_effective_cost)` |
| Cost column used | savingsplan_effective_cost | Not unblended_cost |
| All cost types present | Yes | Check all cost columns populated |

### Validation Flow

```
1. Generate AWS data with SavingsPlan costs
2. Run POC aggregation
3. Validate using savingsplan_effective_cost (not unblended_cost)
4. Verify markup calculated on effective cost
```

### Cost Column Priority

For SavingsPlan scenarios, validation uses:
```
savingsplan_effective_cost > 0 → Use savingsplan_effective_cost
Otherwise → Use unblended_cost
```

### Why This Matters

Customers with SavingsPlans pay discounted rates. Billing must reflect:
- **Actual cost paid** (effective cost), not list price
- **Markup calculations** based on actual cost
- **Accurate showback/chargeback** to teams

---

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh

# Validate (script auto-detects SavingsPlan scenario)
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/14-savingsplan-costs/manifest.yml
```

---

## Validation Queries

### Primary Validation (SavingsPlan Cost)

```sql
-- For SavingsPlan scenarios, validate effective cost
SELECT 
    ROUND(SUM(savingsplan_effective_cost)::numeric, 2) as total_savingsplan_cost,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_unblended_cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Expected: savingsplan = $70.00, unblended = $100.00
-- Validation uses savingsplan cost
```

### Verify All Cost Types

```sql
SELECT 
    ROUND(SUM(unblended_cost)::numeric, 2) as unblended,
    ROUND(SUM(blended_cost)::numeric, 2) as blended,
    ROUND(SUM(savingsplan_effective_cost)::numeric, 2) as savingsplan,
    ROUND(SUM(calculated_amortized_cost)::numeric, 2) as amortized
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
```

### Markup Validation

```sql
-- Verify markup is based on effective cost, not unblended
SELECT 
    ROUND(SUM(savingsplan_effective_cost)::numeric, 2) as base_cost,
    ROUND(SUM(markup_cost_savingsplan)::numeric, 2) as markup,
    ROUND(SUM(markup_cost_savingsplan) / NULLIF(SUM(savingsplan_effective_cost), 0) * 100, 1) as markup_pct
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Expected: markup_pct matches configured markup (e.g., 10%)
```

---

## Troubleshooting

### Validation fails with wrong cost

- **Cause**: Validating unblended instead of savingsplan
- **Check**: Manifest should have `total_amortized_cost` in expected_outcome
- **Fix**: Validation script auto-detects via manifest filename or expected_outcome key

### savingsplan_effective_cost is 0

- **Cause**: AWS data doesn't have SavingsPlan coverage
- **Check**: Verify `savingsplan_savingsplaneffectivecost` column in AWS CUR
- **Debug**: Check raw Parquet data for this column

---

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest with SavingsPlan costs |

---

## Related Scenarios

- [09-cost-types](../09-cost-types/) - All cost types validation
- [17-reserved-instances](../17-reserved-instances/) - RI cost handling

