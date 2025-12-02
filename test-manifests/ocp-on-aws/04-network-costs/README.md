# Scenario 04: Network Costs

## Overview

Tests that AWS data transfer costs are correctly identified and attributed to the special "Network unattributed" namespace. Network costs cannot be attributed to specific pods, so they are tracked separately.

## What This Tests

- Detection of network costs via `product_productfamily: Data Transfer`
- Detection via `lineitem_usagetype` containing `DataTransfer`
- Separation of IN vs OUT data transfer direction
- Attribution to "Network unattributed" namespace
- Compute costs are NOT mixed with network costs

## Test Data

**OCP:**
- 1 cluster with 2 nodes
- Regular compute workloads in `frontend` and `backend` namespaces

**AWS:**
- EC2 compute costs: $80.00
- Data Transfer IN: $10.00
- Data Transfer OUT: $20.00

## Expected Outcome

```yaml
expected_outcome:
  total_cost: 110.00
  namespaces:
    - frontend
    - backend
    - "Network unattributed"
  network_costs:
    IN: 10.00
    OUT: 20.00
  compute_costs: 80.00
```

---

## Validation Details

### What Is Validated

| Validation | Expected | Query/Check |
|------------|----------|-------------|
| Total cost | $110.00 ± $0.10 | `SUM(unblended_cost)` |
| Network namespace exists | Yes | `namespace = 'Network unattributed'` |
| Network cost total | $30.00 | SUM where namespace='Network unattributed' |
| Data transfer direction | IN, OUT present | `data_transfer_direction` column |
| Compute costs separate | $80.00 | SUM where namespace != 'Network unattributed' |
| No cross-contamination | Network != Compute | Verify separation |

### Validation Flow

```
1. Generate OCP data → Creates pods with compute usage
2. Generate AWS data → Creates EC2 (compute) + Data Transfer (network)
3. Run POC aggregation:
   a. Detect network costs by product_family or usage_type
   b. Separate network from compute
   c. Attribute compute to namespaces
   d. Attribute network to "Network unattributed"
4. Validate:
   - Total cost = $110.00
   - Network namespace exists
   - Directions (IN/OUT) are tracked
```

### Network Cost Detection Logic

AWS costs are classified as network if:
```python
product_productfamily == 'Data Transfer'
OR lineitem_usagetype LIKE '%DataTransfer%'
OR lineitem_operation LIKE '%DataTransfer%'
```

### Why This Matters

Network costs are fundamentally different:
- **Cannot be attributed to pods** - Data transfer happens at instance level
- **Must be tracked separately** - For accurate cost reporting
- **Direction matters** - IN vs OUT for capacity planning

---

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh

# Validate
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/04-network-costs/manifest.yml
```

---

## Validation Queries

### Primary Validation (Totals)

```sql
SELECT 
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Expected: total_cost = 110.00, namespaces includes "Network unattributed"
```

### Network Cost Validation

```sql
-- Verify network costs are separated
SELECT 
    namespace,
    data_transfer_direction,
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE namespace = 'Network unattributed'
GROUP BY namespace, data_transfer_direction;

-- Expected:
-- Network unattributed | IN  | $10.00
-- Network unattributed | OUT | $20.00
```

### Compute Cost Validation

```sql
-- Verify compute costs are NOT in Network namespace
SELECT 
    namespace,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE namespace != 'Network unattributed'
GROUP BY namespace
ORDER BY cost DESC;

-- Expected: frontend + backend = $80.00
```

### Cross-Contamination Check

```sql
-- Ensure no compute costs in Network namespace
SELECT COUNT(*) 
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE namespace = 'Network unattributed'
  AND product_code = 'AmazonEC2'
  AND data_transfer_direction IS NULL;

-- Expected: 0 (no compute in network namespace)
```

---

## Troubleshooting

### "Network unattributed" namespace missing

- **Cause**: Network costs not detected
- **Check**: Verify AWS data has `product_productfamily = 'Data Transfer'`
- **Debug**: Check `lineitem_usagetype` for DataTransfer patterns

### Network costs mixed with compute

- **Cause**: Detection logic not working
- **Check**: `product_productfamily` must be exactly 'Data Transfer'
- **Debug**: Print network detection results during aggregation

### Missing IN or OUT direction

- **Cause**: Direction not extracted from usage type
- **Check**: Usage type should contain 'In' or 'Out'
- **Debug**: Check `lineitem_usagetype` values

---

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest with EC2 + Data Transfer costs |

---

## Related Scenarios

- [13-network-data-transfer](../13-network-data-transfer/) - Advanced network direction handling
- [01-resource-matching](../01-resource-matching/) - Compute cost matching
