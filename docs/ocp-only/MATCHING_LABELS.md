# OCP-Only Matching Labels Reference

> **Purpose**: Complete reference of OCP-only aggregation logic and Trino SQL parity
> **Audience**: Dev team, QE team, and anyone validating Trino parity
> **Status**: ✅ **100% Trino Parity Achieved** (36/36 features implemented)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Feature Implementation](#feature-implementation)
3. [CTE: Enabled Tag Keys](#cte-enabled-tag-keys)
4. [CTE: Node Labels](#cte-node-labels)
5. [CTE: Namespace Labels](#cte-namespace-labels)
6. [CTE: Node Capacity](#cte-node-capacity)
7. [CTE: Cluster Capacity](#cte-cluster-capacity)
8. [CTE: Volume Nodes](#cte-volume-nodes)
9. [CTE: Shared Volume Node Count](#cte-shared-volume-node-count)
10. [Pod Aggregation](#pod-aggregation)
11. [Storage Aggregation](#storage-aggregation)
12. [Unallocated Capacity](#unallocated-capacity)
13. [Final Output](#final-output)
14. [Test Scenarios](#test-scenarios)
15. [Code References](#code-references)

---

## Executive Summary

The POC replicates Trino's OCP aggregation SQL (`reporting_ocpusagelineitem_daily_summary.sql`) using Pandas DataFrames instead of SQL queries.

### Current Status

| Category | Trino Features | POC Implemented | Status |
|----------|---------------|-----------------|--------|
| **Pod Aggregation** | 14 | 14 | ✅ Complete |
| **Storage Aggregation** | 12 | 12 | ✅ Complete |
| **Unallocated Capacity** | 6 | 6 | ✅ Complete |
| **Label Processing** | 4 | 4 | ✅ Complete |
| **TOTAL** | 36 | 36 | ✅ 100% |

---

## Feature Implementation

### ✅ 100% Trino Parity Achieved

All Trino SQL features have been implemented and tested:

| # | Feature | Trino SQL Lines | Status | Test Coverage |
|---|---------|-----------------|--------|---------------|
| 1 | **Shared Volume Node Count** | 205-212, 410-411 | ✅ Implemented | `TestSharedVolumeNodeCount` |
| 2 | **Days in Month Formula** | 358-363 | ✅ Implemented | `TestDaysInMonthFormula` |
| 3 | **Storage Cost Category** | 406, 428-429 | ✅ Implemented | `TestStorageCostCategory` |
| 4 | **PVC Capacity Gigabyte** | 356-357 | ✅ Implemented | `TestPVCCapacityGigabyte` |

### Implementation Details

#### Feature 1: Shared Volume Node Count

**Trino SQL (lines 205-212):**
```sql
cte_shared_volume_node_count AS (
    SELECT usage_start,
        persistentvolume,
        count(DISTINCT node) as node_count
    FROM cte_volume_nodes
    GROUP BY usage_start, persistentvolume
)
```

**Trino SQL (lines 410-411):**
```sql
sum(sli.volume_request_storage_byte_seconds) / max(nc.node_count) as volume_request_storage_byte_seconds,
sum(sli.persistentvolumeclaim_usage_byte_seconds) / max(nc.node_count) as persistentvolumeclaim_usage_byte_seconds
```

**POC (`src/aggregator_storage.py`):**
```python
# Calculate node count per PV
node_counts = df.groupby(['usage_start', 'persistentvolume'])['node'].nunique().reset_index()
node_counts.columns = ['usage_start', 'persistentvolume', 'node_count']
df = pd.merge(df, node_counts, on=['usage_start', 'persistentvolume'], how='left')

# Divide by node count
df['volume_request_storage_byte_seconds'] /= df['node_count']
df['persistentvolumeclaim_usage_byte_seconds'] /= df['node_count']
```

**Status:** ✅ IMPLEMENTED

---

#### Feature 2: Days in Month Formula

**Trino SQL (lines 358-363):**
```sql
(capacity_byte_seconds / (86400 * days_in_month) * power(2, -30))
```

**POC (`src/aggregator_storage.py`):**
```python
import calendar
def get_days_in_month(usage_start):
    return calendar.monthrange(year, month)[1]

df['_days_in_month'] = df['usage_start'].apply(get_days_in_month)
# Uses actual 28/29/30/31 days instead of fixed 730 hours
```

**Status:** ✅ IMPLEMENTED

---

#### Feature 3: Storage Cost Category

**Trino SQL (lines 428-429):**
```sql
LEFT JOIN postgres.reporting_ocp_cost_category_namespace AS cat_ns
    ON sli.namespace LIKE cat_ns.namespace
max(cat_ns.cost_category_id) as cost_category_id
```

**POC (`src/aggregator_storage.py`):**
```python
def _join_cost_category(self, aggregated_df, cost_category_df):
    def match_cost_category(namespace):
        # LIKE pattern matching with % wildcard
        for _, row in cost_category_df.iterrows():
            pattern = row['namespace']
            if pattern.endswith('%') and namespace.startswith(pattern[:-1]):
                matching_ids.append(row['cost_category_id'])
        return max(matching_ids) if matching_ids else None
```

**Status:** ✅ IMPLEMENTED

---

#### Feature 4: PVC Capacity Gigabyte

**Trino SQL (lines 356-357):**
```sql
(sua.persistentvolumeclaim_capacity_bytes * power(2, -30)) as persistentvolumeclaim_capacity_gigabyte
```

**POC (`src/aggregator_storage.py`):**
```python
if 'persistentvolumeclaim_capacity_bytes' in df.columns:
    agg_dict['persistentvolumeclaim_capacity_bytes'] = 'max'
# ...
result['persistentvolumeclaim_capacity_gigabyte'] = df['persistentvolumeclaim_capacity_bytes'] / (1024 ** 3)
```

**Status:** ✅ IMPLEMENTED

---

## CTE: Enabled Tag Keys

**Trino SQL (lines 95-100):**
```sql
cte_pg_enabled_keys as (
    select array['vm_kubevirt_io_name'] || array_agg(key order by key) as keys
      from postgres.{{schema}}.reporting_enabledtagkeys
     where enabled = true
     and provider_type = 'OCP'
)
```

**POC (`src/db_writer.py`, lines 79-112):**
```python
def get_enabled_tag_keys(self) -> List[str]:
    query = f"""
        SELECT key
        FROM {self.schema}.reporting_ocpenabledtagkeys
        WHERE enabled = true
        ORDER BY key
    """
    # ...
    # Always include 'vm_kubevirt_io_name' (from Trino SQL line 96)
    keys = ['vm_kubevirt_io_name'] + keys
    return keys
```

**Status:** ✅ IMPLEMENTED

**Test Coverage:** Unit tests verify enabled keys are fetched and `vm_kubevirt_io_name` is always included

---

## CTE: Node Labels

**Trino SQL (lines 101-120):**
```sql
cte_ocp_node_label_line_item_daily AS (
    SELECT date(nli.interval_start) as usage_start,
        nli.node,
        cast(
            map_filter(
                cast(json_parse(nli.node_labels) as map(varchar, varchar)),
                (k,v) -> contains(pek.keys, k)
            ) as json
        ) as node_labels
    FROM hive.{{schema}}.openshift_node_labels_line_items_daily AS nli
    CROSS JOIN cte_pg_enabled_keys AS pek
    WHERE nli.source = {{source}}
        AND nli.year = {{year}}
        AND nli.month = {{month}}
    GROUP BY date(nli.interval_start), nli.node, 3
)
```

**POC (`src/aggregator_pod.py`, lines 545-567):**
```python
# Parse node labels
node_labels_df['node_labels_dict'] = node_labels_df['node_labels'].apply(parse_json_labels)

# Filter by enabled keys
node_labels_df['node_labels_filtered'] = node_labels_df['node_labels_dict'].apply(
    lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
)
```

**Status:** ✅ IMPLEMENTED

**Match Verified:**
- Filters labels by enabled keys ✅
- Groups by usage_start + node ✅

---

## CTE: Namespace Labels

**Trino SQL (lines 122-141):**
```sql
cte_ocp_namespace_label_line_item_daily AS (
    SELECT date(nli.interval_start) as usage_start,
        nli.namespace,
        cast(
            map_filter(
                cast(json_parse(nli.namespace_labels) as map(varchar, varchar)),
                (k,v) -> contains(pek.keys, k)
            ) as json
        ) as namespace_labels
    FROM hive.{{schema}}.openshift_namespace_labels_line_items_daily AS nli
    CROSS JOIN cte_pg_enabled_keys AS pek
    ...
    GROUP BY date(nli.interval_start), nli.namespace, 3
)
```

**POC (`src/aggregator_pod.py`, lines 595-617):**
```python
# Filter by enabled keys
namespace_labels_df['namespace_labels_filtered'] = namespace_labels_df['namespace_labels_dict'].apply(
    lambda labels: filter_labels_by_enabled_keys(labels, self.enabled_tag_keys)
)
```

**Status:** ✅ IMPLEMENTED

---

## CTE: Node Capacity

**Trino SQL (lines 143-164):**
```sql
cte_ocp_node_capacity AS (
    SELECT date(nc.interval_start) as usage_start,
        nc.node,
        sum(nc.node_capacity_cpu_core_seconds) as node_capacity_cpu_core_seconds,
        sum(nc.node_capacity_memory_byte_seconds) as node_capacity_memory_byte_seconds
    FROM (
        SELECT li.interval_start,
            li.node,
            max(li.node_capacity_cpu_core_seconds) as node_capacity_cpu_core_seconds,
            max(li.node_capacity_memory_byte_seconds) as node_capacity_memory_byte_seconds
        FROM hive.{{schema}}.openshift_pod_usage_line_items AS li
        ...
        GROUP BY li.interval_start, li.node
    ) as nc
    GROUP BY date(nc.interval_start), nc.node
)
```

**Logic:**
1. Inner query: MAX capacity per interval + node
2. Outer query: SUM of max capacities per day + node

**POC (`src/aggregator_pod.py`, lines 879-948):**
```python
def calculate_node_capacity(pod_usage_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    # Step 1: Get max capacity per interval + node
    interval_capacity = df.groupby(['interval_start_clean', 'node']).agg({
        'node_capacity_cpu_core_seconds': 'max',
        'node_capacity_memory_byte_seconds': 'max'
    }).reset_index()

    # Step 2: Sum across intervals per day + node
    node_capacity = interval_capacity.groupby(['usage_start', 'node']).agg({
        'node_capacity_cpu_core_seconds': 'sum',
        'node_capacity_memory_byte_seconds': 'sum'
    }).reset_index()
```

**Status:** ✅ IMPLEMENTED

---

## CTE: Cluster Capacity

**Trino SQL (lines 165-171):**
```sql
cte_ocp_cluster_capacity AS (
    SELECT nc.usage_start,
        sum(nc.node_capacity_cpu_core_seconds) as cluster_capacity_cpu_core_seconds,
        sum(nc.node_capacity_memory_byte_seconds) as cluster_capacity_memory_byte_seconds
    FROM cte_ocp_node_capacity AS nc
    GROUP BY nc.usage_start
)
```

**POC (`src/aggregator_pod.py`, lines 951-961):**
```python
# Step 3: Calculate cluster capacity (Trino lines 165-171)
cluster_capacity = node_capacity.groupby('usage_start').agg({
    'node_capacity_cpu_core_seconds': 'sum',
    'node_capacity_memory_byte_seconds': 'sum'
}).reset_index()
```

**Status:** ✅ IMPLEMENTED

---

## CTE: Volume Nodes

**Trino SQL (lines 175-204):**
```sql
cte_volume_nodes AS (
    SELECT date(sli.interval_start) as usage_start,
        sli.persistentvolumeclaim,
        sli.persistentvolume,
        sli.pod,
        sli.namespace,
        uli.node,
        uli.resource_id
    FROM hive.{{schema}}.openshift_storage_usage_line_items_daily as sli
    JOIN hive.{{schema}}.openshift_pod_usage_line_items_daily as uli
        ON uli.source = sli.source
            AND uli.namespace = sli.namespace
            AND uli.pod = sli.pod
            AND date(uli.interval_start) = date(sli.interval_start)
    ...
    GROUP BY date(sli.interval_start),
        sli.persistentvolumeclaim, sli.persistentvolume,
        sli.pod, sli.namespace, uli.node, uli.resource_id
)
```

**POC (`src/aggregator_storage.py`, lines 168-233):**
```python
def _join_with_pods(self, storage_df: pd.DataFrame, pod_df: pd.DataFrame) -> pd.DataFrame:
    # Join storage with pod to get node/resource_id
    result = pd.merge(
        storage_df,
        pod_subset,
        on=['usage_date', 'namespace', 'pod'],
        how='left'
    )
```

**Status:** ✅ IMPLEMENTED

---

## CTE: Shared Volume Node Count

**Trino SQL (lines 205-212):**
```sql
cte_shared_volume_node_count AS (
    SELECT usage_start,
        persistentvolume,
        count(DISTINCT node) as node_count
    FROM cte_volume_nodes
    GROUP BY usage_start, persistentvolume
)
```

**Usage (lines 410-411):**
```sql
sum(sli.volume_request_storage_byte_seconds) / max(nc.node_count) as volume_request_storage_byte_seconds,
sum(sli.persistentvolumeclaim_usage_byte_seconds) / max(nc.node_count) as persistentvolumeclaim_usage_byte_seconds
```

**POC Status:** ✅ **IMPLEMENTED** (aggregator_storage.py lines 290-316)

**Implementation:**
```python
# In _group_and_aggregate():
# 1. Calculate node count per PV (Trino lines 205-212)
node_counts = df.groupby(['usage_start', 'persistentvolume'])['node'].nunique().reset_index()
node_counts.columns = ['usage_start', 'persistentvolume', 'node_count']

# 2. Join node count to storage data
df = pd.merge(df, node_counts, on=['usage_start', 'persistentvolume'], how='left')
df['node_count'] = df['node_count'].fillna(1)

# 3. Divide usage by node count
df['volume_request_storage_byte_seconds'] = df['volume_request_storage_byte_seconds'] / df['node_count']
df['persistentvolumeclaim_usage_byte_seconds'] = df['persistentvolumeclaim_usage_byte_seconds'] / df['node_count']
```

---

## Pod Aggregation

### Label Merging (lines 266-273)

**Trino SQL:**
```sql
map_concat(
    cast(coalesce(nli.node_labels, cast(map(array[], array[]) as json)) as map(varchar, varchar)),
    cast(coalesce(nsli.namespace_labels, cast(map(array[], array[]) as json)) as map(varchar, varchar)),
    map_filter(
        cast(json_parse(li.pod_labels) AS MAP(VARCHAR, VARCHAR)),
        (k, v) -> CONTAINS(pek.keys, k)
    )
) as pod_labels
```

**Precedence:** Pod > Namespace > Node (later keys override earlier)

**POC (`src/aggregator_pod.py`, lines 470-498):**
```python
def merge_labels_with_precedence(row):
    # Start with node labels (lowest precedence)
    merged.update(node_labels)
    # Override with namespace labels
    merged.update(namespace_labels)
    # Override with pod labels (highest precedence)
    merged.update(pod_labels)
    return merged
```

**Status:** ✅ IMPLEMENTED

---

### Effective Usage Calculation (lines 277, 281)

**Trino SQL:**
```sql
sum(coalesce(li.pod_effective_usage_cpu_core_seconds,
    greatest(li.pod_usage_cpu_core_seconds, li.pod_request_cpu_core_seconds))) / 3600.0
```

**POC (`src/aggregator_pod.py`, lines 681-704):**
```python
df['pod_effective_usage_cpu_core_seconds'] = df.apply(
    lambda row: coalesce(
        row.get('pod_effective_usage_cpu_core_seconds'),
        safe_greatest(
            row.get('pod_usage_cpu_core_seconds'),
            row.get('pod_request_cpu_core_seconds')
        )
    ),
    axis=1
)
```

**Status:** ✅ IMPLEMENTED

---

### Cost Category Join (lines 302-303)

**Trino SQL:**
```sql
LEFT JOIN postgres.{{schema}}.reporting_ocp_cost_category_namespace AS cat_ns
    ON li.namespace LIKE cat_ns.namespace
...
max(cat_ns.cost_category_id) as cost_category_id
```

**POC (`src/aggregator_pod.py`, lines 773-807):**
```python
def _join_cost_category(self, aggregated_df, cost_category_df):
    def match_cost_category(namespace):
        matching_ids = []
        for _, row in cost_category_df.iterrows():
            pattern = row['namespace']
            # Simple pattern match (% wildcard)
            if pattern.endswith('%'):
                if namespace.startswith(pattern[:-1]):
                    matching_ids.append(row['cost_category_id'])
            elif namespace == pattern:
                matching_ids.append(row['cost_category_id'])
        # Return MAX of matching IDs (Trino SQL line 264)
        return max(matching_ids) if matching_ids else None
```

**Status:** ✅ IMPLEMENTED (for pods)

---

### Pod Aggregation Columns

| Column | Trino SQL | POC | Status |
|--------|-----------|-----|--------|
| `pod_usage_cpu_core_hours` | sum(seconds) / 3600 | ✅ | ✅ |
| `pod_request_cpu_core_hours` | sum(seconds) / 3600 | ✅ | ✅ |
| `pod_effective_usage_cpu_core_hours` | coalesce/greatest | ✅ | ✅ |
| `pod_limit_cpu_core_hours` | sum(seconds) / 3600 | ✅ | ✅ |
| `pod_usage_memory_gigabyte_hours` | sum * 2^-30 / 3600 | ✅ | ✅ |
| `pod_request_memory_gigabyte_hours` | sum * 2^-30 / 3600 | ✅ | ✅ |
| `pod_effective_usage_memory_gigabyte_hours` | coalesce/greatest | ✅ | ✅ |
| `pod_limit_memory_gigabyte_hours` | sum * 2^-30 / 3600 | ✅ | ✅ |
| `node_capacity_cpu_cores` | max | ✅ | ✅ |
| `node_capacity_cpu_core_hours` | max / 3600 | ✅ | ✅ |
| `node_capacity_memory_gigabytes` | max * 2^-30 | ✅ | ✅ |
| `node_capacity_memory_gigabyte_hours` | max * 2^-30 / 3600 | ✅ | ✅ |
| `cluster_capacity_cpu_core_hours` | max / 3600 | ✅ | ✅ |
| `cluster_capacity_memory_gigabyte_hours` | max * 2^-30 / 3600 | ✅ | ✅ |

---

## Storage Aggregation

### Storage Volume Labels (lines 392-403)

**Trino SQL:**
```sql
map_concat(
    cast(coalesce(nli.node_labels, ...) as map(varchar, varchar)),
    cast(coalesce(nsli.namespace_labels, ...) as map(varchar, varchar)),
    map_filter(cast(json_parse(sli.persistentvolume_labels) AS MAP(VARCHAR, VARCHAR)), ...),
    map_filter(cast(json_parse(sli.persistentvolumeclaim_labels) AS MAP(VARCHAR, VARCHAR)), ...)
) as volume_labels
```

**POC (`src/aggregator_storage.py`, lines 463-478):**
```python
def merge_labels_with_precedence(row):
    # Apply precedence: start with node, override with namespace, override with volume
    merged = {}
    merged.update(node_labels)
    merged.update(namespace_labels)
    merged.update(volume_labels)  # PV + PVC labels already merged
    return json.dumps(merged)
```

**Status:** ✅ IMPLEMENTED

---

### Storage Aggregation Columns

| Column | Trino SQL | POC | Status |
|--------|-----------|-----|--------|
| `persistentvolumeclaim` | GROUP BY | ✅ | ✅ |
| `persistentvolume` | GROUP BY | ✅ | ✅ |
| `storageclass` | GROUP BY | ✅ | ✅ |
| `volume_labels` | 4-way merge | ✅ | ✅ |
| `node` | from volume_nodes CTE | ✅ | ✅ |
| `resource_id` | from volume_nodes CTE | ✅ | ✅ |
| `csi_volume_handle` | max | ✅ | ✅ |
| `persistentvolumeclaim_capacity_gigabyte` | max * 2^-30 | ✅ | ✅ |
| `persistentvolumeclaim_capacity_gigabyte_months` | sum / days | ✅ | ✅ |
| `volume_request_storage_gigabyte_months` | sum / node_count / days | ✅ | ✅ |
| `persistentvolumeclaim_usage_gigabyte_months` | sum / node_count / days | ✅ | ✅ |
| `cost_category_id` | max | ✅ | ✅ |

---

## Unallocated Capacity

**Trino SQL (lines 491-581):**
```sql
WITH cte_node_role AS (
    SELECT max(node_role) AS node_role, node, resource_id
    FROM postgres.{{schema}}.reporting_ocp_nodes
    GROUP BY node, resource_id
),
cte_unallocated_capacity AS (
    SELECT
        CASE max(nodes.node_role)
            WHEN 'master' THEN 'Platform unallocated'
            WHEN 'infra' THEN 'Platform unallocated'
            WHEN 'worker' THEN 'Worker unallocated'
        END as namespace,
        lids.node,
        (max(lids.node_capacity_cpu_core_hours) - sum(lids.pod_usage_cpu_core_hours)) as pod_usage_cpu_core_hours,
        ...
    WHERE lids.namespace != 'Platform unallocated'
        AND lids.namespace != 'Worker unallocated'
        AND lids.namespace != 'Network unattributed'
        AND lids.namespace != 'Storage unattributed'
        AND lids.data_source = 'Pod'
    GROUP BY lids.node, lids.usage_start, lids.source_uuid
)
```

**POC (`src/aggregator_unallocated.py`):**
- ✅ Fetches node roles from PostgreSQL
- ✅ Excludes already-unallocated namespaces
- ✅ Calculates: `max(capacity) - sum(usage)`
- ✅ Assigns namespace: "Platform unallocated" or "Worker unallocated"
- ✅ Ensures negative values become zero

**Status:** ✅ FULLY IMPLEMENTED

---

## Final Output

### all_labels Column (lines 651-654)

**Trino SQL:**
```sql
json_parse(json_format(cast(map_concat(
    cast(json_parse(coalesce(pod_labels, '{}')) as map(varchar, varchar)),
    cast(json_parse(coalesce(volume_labels, '{}')) as map(varchar, varchar))
)as json))) as all_labels
```

**POC (`src/aggregator_pod.py`, line 823):**
```python
df['all_labels'] = df['merged_labels']
```

**POC (`src/aggregator_storage.py`, line 547):**
```python
result['all_labels'] = df['merged_labels']
```

**Status:** ✅ IMPLEMENTED

---

## Test Scenarios

### E2E Scenario Matrix (20/20 Passing)

| # | Scenario | Feature Tested | Trino SQL Lines | Status |
|---|----------|----------------|-----------------|--------|
| **Core Aggregation** |||||
| 01 | Basic Pod Aggregation | CPU/memory metrics, label merging | 260-316 | ✅ E2E |
| 02 | Storage Aggregation | PVC/PV metrics, volume labels | 327-446 | ✅ E2E |
| 03 | Multi-Namespace | Namespace grouping | 261, 310 | ✅ E2E |
| 04 | Multi-Node | Node capacity calculations | 143-171 | ✅ E2E |
| 05 | Cluster Capacity | Cluster-wide capacity | 165-171 | ✅ E2E |
| 06 | Cost Category | cost_category_id assignment | 302-303 | ✅ E2E |
| 07 | Unallocated Capacity | Platform/Worker unallocated | 491-581 | ✅ E2E |
| **Storage Features** |||||
| 08 | Shared PV Across Nodes | Division by node_count | 205-212, 410-411 | ✅ E2E |
| 09 | Days in Month | Month-specific formula | 358-363 | ✅ E2E |
| 10 | Storage Cost Category | cost_category_id for storage | 406, 428-429 | ✅ E2E |
| 11 | PVC Capacity GB | persistentvolumeclaim_capacity_gigabyte | 356-357 | ✅ E2E |
| **Label Handling** |||||
| 12 | Label Precedence | Pod > Namespace > Node | 266-273 | ✅ E2E |
| 13 | Labels Special Chars | Unicode, emoji handling | 267-268 | ✅ E2E |
| 14 | Empty Labels | Graceful NULL handling | 267-268 | ✅ E2E |
| 15 | Effective Usage | coalesce/greatest logic | 277, 281 | ✅ E2E |
| 16 | all_labels Column | Merged pod + volume labels | 266-273 | ✅ E2E |
| **Edge Cases** |||||
| 17 | Node Roles | Master/infra/worker detection | 507-511 | ✅ E2E |
| 18 | Zero CPU/Memory | No division by zero | 275-282 | ✅ E2E |
| 19 | VM Pods (KubeVirt) | vm_kubevirt_io_name always enabled | 95-100 | ✅ E2E |
| 20 | Storage No Pod Match | LEFT JOIN handling | 183-188 | ✅ E2E |

**Legend:**
- ✅ Implemented & Tested

---

## Code References

### Key POC Files

| File | Purpose | Trino SQL Section |
|------|---------|-------------------|
| `src/aggregator_pod.py` | Pod aggregation | lines 260-316 |
| `src/aggregator_storage.py` | Storage aggregation | lines 327-446 |
| `src/aggregator_unallocated.py` | Unallocated capacity | lines 491-581 |
| `src/db_writer.py` | PostgreSQL operations | CTEs to postgres.* |
| `src/utils.py` | Label filtering | map_filter logic |

### Trino SQL Reference

**File:** `koku/masu/database/trino_sql/reporting_ocpusagelineitem_daily_summary.sql`

| Section | Lines | Description |
|---------|-------|-------------|
| CTEs | 95-212 | Helper queries (enabled keys, labels, capacity) |
| Pod Aggregation | 219-316 | Pod metrics and labels |
| Storage Aggregation | 327-446 | Storage metrics and labels |
| Unallocated Capacity | 461-581 | Platform/Worker unallocated |
| Final Insert | 583-667 | Insert to PostgreSQL |

---

## Quick Reference: Implementation Checklist

All features are implemented and tested:

```
✅ Feature 1: Shared Volume Node Count
  - [x] Added node_count calculation in _group_and_aggregate()
  - [x] Divide storage metrics by node_count
  - [x] Unit test: test_shared_pv_across_3_nodes_divides_usage_by_3
  - [x] Unit test: test_single_node_pv_not_affected
  - [x] Unit test: test_mixed_shared_and_single_pvs

✅ Feature 2: Days in Month
  - [x] Calculate actual days from usage_start date (calendar.monthrange)
  - [x] Replace fixed 730 hours/month with actual days * 24
  - [x] Unit test: test_february_28_days
  - [x] Unit test: test_july_31_days
  - [x] Unit test: test_february_vs_july_difference

✅ Feature 3: Storage Cost Category
  - [x] Added cost_category_df parameter to StorageAggregator.aggregate()
  - [x] Implemented _join_cost_category() for storage
  - [x] Unit test: test_storage_cost_category_applied
  - [x] Unit test: test_storage_cost_category_no_match_is_null

✅ Feature 4: PVC Capacity Gigabyte
  - [x] Added persistentvolumeclaim_capacity_bytes to agg_dict with 'max'
  - [x] Calculate: max(capacity_bytes) / 2^30 in _format_output()
  - [x] Unit test: test_pvc_capacity_gigabyte_calculated
  - [x] Unit test: test_pvc_capacity_gigabyte_max_across_intervals
```

---

*Document last updated: November 26, 2025*
*POC Version: 1.0*
*Trino Parity: 100% (36/36 features)*

