# Scenario 01: Resource ID Matching

## Overview

Tests the fundamental matching mechanism where AWS EC2 instance IDs are matched to OCP node `resource_id` values. This is the primary matching method used by Cost Management.

## What This Tests

- EC2 `lineitem_resourceid` contains instance ID (e.g., `i-0abc123def456`)
- OCP node has matching `resource_id` field
- Costs are correctly attributed to namespaces on that node
- Cost distribution uses weighted CPU/memory ratios

## Test Data

**OCP:**
- 1 cluster with 1 node
- Node has `resource_id: i-worker001`
- 2 namespaces: `frontend`, `backend`
- CPU/Memory usage defined for each namespace

**AWS:**
- EC2 costs for instance `i-worker001`
- Unblended cost: $16.08

## Expected Outcome

```yaml
expected_outcome:
  resource_id_matched: true
  tag_matched: false
  total_cost: 16.08
  namespaces: 2
```

---

## Validation Details

### What Is Validated

| Validation | Expected | Query/Check |
|------------|----------|-------------|
| Total cost | $16.08 ± $0.10 | `SUM(unblended_cost)` |
| Resource matching | true | `resource_id_matched = true` for all rows |
| Tag matching | false | `tag_matched = false` (resource match takes precedence) |
| Namespace count | 2 | `COUNT(DISTINCT namespace)` |
| No data loss | All costs attributed | Total equals AWS input cost |

### Validation Flow

```
1. Generate OCP data (nise) → Creates pod/node data with resource_id
2. Generate AWS data (nise) → Creates EC2 cost with matching instance ID
3. Run POC aggregation → Matches by resource_id, distributes costs
4. Validate totals → Compare SUM(cost) to expected $16.08
5. Validate matching → Verify resource_id_matched=true
```

### Why This Matters

Resource ID matching is the **most reliable** matching method because:
- EC2 instance IDs are unique and immutable
- No ambiguity (unlike tag matching)
- Direct 1:1 mapping between AWS and OCP

If this scenario fails, the fundamental matching logic is broken.

---

## How to Run

```bash
# Full automated run
./scripts/run_ocp_aws_scenario_tests.sh

# Or run just this scenario
cd /path/to/poc-parquet-aggregator
source venv/bin/activate

# 1. Generate test data
nise report ocp -s 2025-10-01 -e 2025-10-02 \
  --ocp-cluster-id test-cluster-001 \
  -w test-manifests/ocp-on-aws/01-resource-matching/manifest.yml

# 2. Upload to MinIO
python scripts/csv_to_parquet_minio.py ...

# 3. Run aggregation
python src/main.py --ocp-provider-uuid ... --aws-provider-uuid ...

# 4. Validate
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/01-resource-matching/manifest.yml
```

---

## Validation Queries

### Primary Validation (Totals)

```sql
-- This is what validate_ocp_aws_totals.py runs
SELECT 
    COUNT(*) as total_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT cluster_id) as clusters,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Expected: total_cost = 16.08, namespaces = 2
```

### Secondary Validation (Matching Flags)

```sql
-- Verify resource_id matching was used
SELECT 
    resource_id_matched,
    tag_matched,
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY resource_id_matched, tag_matched;

-- Expected: resource_id_matched=true, tag_matched=false for all rows
```

### Detailed Breakdown

```sql
-- Cost per namespace
SELECT 
    namespace,
    resource_id,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 4) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 4) as mem_hours
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY namespace, resource_id
ORDER BY namespace;
```

---

## Troubleshooting

### Total cost is $0.00

- **Cause**: No resource ID match found
- **Check**: Verify OCP `resource_id` matches AWS `lineitem_resourceid`
- **Debug**: `SELECT DISTINCT resource_id FROM ocp_data; SELECT DISTINCT lineitem_resourceid FROM aws_data;`

### Cost is different than expected

- **Cause**: Floating point precision or cost distribution
- **Check**: Tolerance is $0.10 - is the difference larger?
- **Debug**: Check cost distribution ratios

### resource_id_matched is false

- **Cause**: Resource ID format mismatch
- **Check**: AWS uses ARN format, OCP uses instance ID
- **Fix**: Ensure matching logic extracts instance ID from ARN

---

## Files

| File | Description |
|------|-------------|
| `manifest.yml` | Main test manifest with OCP and AWS definitions |

---

## Related Scenarios

- [02-tag-matching](../02-tag-matching/) - Fallback when resource ID doesn't match
- [07-partial-matching](../07-partial-matching/) - Mix of matched/unmatched
