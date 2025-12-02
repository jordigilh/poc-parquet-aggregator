# Scenario 02: Tag Matching

## Overview

Tests AWS resource tag matching when resource IDs don't match. This is the secondary matching mechanism used when an AWS resource (like RDS, S3, or Lambda) cannot be matched by resource ID.

## What This Tests

- AWS resource has `openshift_cluster` tag matching OCP cluster ID
- AWS resource has `openshift_node` tag matching OCP node name
- AWS resource has `openshift_project` tag matching OCP namespace
- Tag matching is used as fallback when resource ID doesn't match
- Costs are attributed via tag matching

## Test Data

**OCP:**
- 1 cluster: `test-cluster-001`
- 1 node: `ip-10-0-1-100.ec2.internal`
- Namespace: `backend`

**AWS:**
- RDS instance with tag `openshift_cluster: test-cluster-001`
- No matching resource ID (RDS ARNs don't match EC2 instance IDs)
- Cost: $16.08

## Expected Outcome

```yaml
expected_outcome:
  resource_id_matched: false
  tag_matched: true
  matched_tag: openshift_cluster
  total_cost: 16.08
```

---

## Validation Details

### What Is Validated

| Validation | Expected | Query/Check |
|------------|----------|-------------|
| Total cost | $16.08 ± $0.10 | `SUM(unblended_cost)` |
| Resource matching | false | `resource_id_matched = false` |
| Tag matching | true | `tag_matched = true` |
| Matched tag type | openshift_cluster | Verify which tag caused match |
| Cost attribution | Costs go to correct namespace | Check namespace in output |

### Validation Flow

```
1. Generate OCP data → Creates cluster/node/namespace
2. Generate AWS data → Creates RDS cost with openshift_cluster tag
3. Run POC aggregation:
   a. Try resource_id matching → No match (RDS vs EC2)
   b. Try tag matching → Match on openshift_cluster tag
   c. Distribute costs based on resource usage
4. Validate totals → Compare SUM(cost) to expected
5. Validate tag_matched=true
```

### Tag Matching Priority

When multiple tags exist, matching follows this priority:

1. `openshift_cluster` - Matches cluster ID
2. `openshift_node` - Matches node name
3. `openshift_project` - Matches namespace directly

### Why This Matters

Tag matching enables cost attribution for:
- **RDS databases** - Tagged with cluster/project
- **S3 buckets** - Tagged for specific namespaces
- **Lambda functions** - Tagged for OpenShift integration
- **Any AWS service** that doesn't run on EC2

---

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh

# Or manually:
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/02-tag-matching/manifest.yml
```

---

## Validation Queries

### Primary Validation (Totals)

```sql
SELECT 
    COUNT(*) as total_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Expected: total_cost = 16.08
```

### Secondary Validation (Tag Matching)

```sql
-- Verify tag matching was used
SELECT 
    resource_id_matched,
    tag_matched,
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY resource_id_matched, tag_matched;

-- Expected: resource_id_matched=false, tag_matched=true
```

### Verify Tag Source

```sql
-- Check which AWS resource types were tag-matched
SELECT 
    product_code,
    tag_matched,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE tag_matched = true
GROUP BY product_code, tag_matched;

-- Expected: AmazonRDS with tag_matched=true
```

---

## Troubleshooting

### tag_matched is false when expected true

- **Cause**: Tag key doesn't match expected format
- **Check**: AWS tag must be exactly `openshift_cluster`, `openshift_node`, or `openshift_project`
- **Debug**: Check `resourcetags` column in AWS data

### Costs attributed to wrong namespace

- **Cause**: Tag value doesn't match OCP data
- **Check**: Tag value must exactly match cluster ID, node name, or namespace
- **Debug**: Compare tag values to OCP metadata

---

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest with RDS + openshift_cluster tag |

---

## Related Scenarios

- [01-resource-matching](../01-resource-matching/) - Primary matching method
- [15-rds-database-costs](../15-rds-database-costs/) - RDS-specific tag matching
- [20-cluster-alias-matching](../20-cluster-alias-matching/) - Match by cluster alias
