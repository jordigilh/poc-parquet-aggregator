# OCP-on-AWS Matching Labels Reference

> **Purpose**: Complete reference of how OCP resources are matched to AWS costs
> **Audience**: Dev team, QE team, and anyone validating Trino parity
> **Status**: ✅ 100% Trino Parity Achieved (23/23 scenarios passing)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Matching Overview](#matching-overview)
3. [Resource ID Matching](#resource-id-matching)
4. [Tag Matching](#tag-matching)
5. [Storage Matching](#storage-matching)
6. [Cost Attribution](#cost-attribution)
7. [Test Scenarios](#test-scenarios)
8. [Code References](#code-references)

---

## Executive Summary

The POC matches OCP resources to AWS costs using **two primary mechanisms**:

| Mechanism | Description | Use Case |
|-----------|-------------|----------|
| **Resource ID Matching** | OCP resource IDs are matched to AWS `lineitem_resourceid` | EC2 instances, EBS volumes |
| **Tag Matching** | AWS tags are matched to OCP cluster/namespace/node | All AWS resources with OpenShift tags |

### Matching Priority

```
1. Resource ID Match (exact/suffix/substring)
   ↓ (if no match)
2. Tag Match (openshift_cluster, openshift_project, openshift_node)
   ↓ (if no match)
3. Generic Tag Match (pod_labels, volume_labels)
   ↓ (if no match)
4. Unattributed (costs go to "unattributed" namespace)
```

---

## Matching Overview

### What Gets Matched

| OCP Resource | AWS Resource | Match Type | Trino SQL | POC Code |
|--------------|--------------|------------|-----------|----------|
| EC2 Instance | lineitem_resourceid | Suffix | `substr(resource_id, -length(...))` | `resource_matcher.py` |
| Node | lineitem_resourceid | Suffix | `substr(resource_id, -length(...))` | `resource_matcher.py` |
| CSI Volume | lineitem_resourceid | Substring | `strpos(resource_id, csi_handle) != 0` | `resource_matcher.py` |
| PV Name | lineitem_resourceid | Suffix | `substr(resource_id, -length(pv))` | `resource_matcher.py` |
| Namespace | openshift_project tag | Exact | `json_query(tags, '$.openshift_project')` | `tag_matcher.py` |
| Cluster | openshift_cluster tag | Exact | `json_query(tags, '$.openshift_cluster')` | `tag_matcher.py` |
| Node | openshift_node tag | Exact | `json_query(tags, '$.openshift_node')` | `tag_matcher.py` |

---

## Resource ID Matching

### 1. EC2 Instance Matching (Suffix)

**Logic**: AWS `lineitem_resourceid` ends with OCP `resource_id`

**Example**:
```
AWS:  i-1234567890abcdef0
OCP:  1234567890abcdef0
Match: ✅ (AWS ends with OCP)
```

**Trino SQL** (`1_resource_matching_by_cluster.sql`, line ~50):
```sql
WHERE substr(aws.lineitem_resourceid, -length(ocp.resource_id)) = ocp.resource_id
```

**POC Code** (`src/resource_matcher.py`):
```python
def suffix_match(aws_resource_id: str, ocp_resource_id: str) -> bool:
    return aws_resource_id.endswith(ocp_resource_id)
```

**Test Scenario**: `Scenario 01`

---

### 2. Node Matching (Suffix)

**Logic**: Same as EC2 - AWS resource ID ends with OCP node resource ID

**Trino SQL** (`1_resource_matching_by_cluster.sql`, line ~50):
```sql
WHERE substr(aws.lineitem_resourceid, -length(node.resource_id)) = node.resource_id
```

**POC Code**: Same as EC2 instance matching

**Test Scenario**: `Scenario 01`

---

### 3. CSI Volume Handle Matching (Substring)

**Logic**: AWS `lineitem_resourceid` contains OCP `csi_volume_handle`

**Example**:
```
AWS:  vol-0abc123def456789
OCP:  abc123def456789
Match: ✅ (OCP is substring of AWS)
```

**Trino SQL** (`1_resource_matching_by_cluster.sql`, line ~89):
```sql
WHERE strpos(aws.lineitem_resourceid, ocp.csi_volume_handle) != 0
```

**POC Code** (`src/resource_matcher.py`):
```python
def substring_match(aws_resource_id: str, ocp_csi_handle: str) -> bool:
    return ocp_csi_handle in aws_resource_id
```

**Test Scenario**: `Scenario 05`

---

### 4. PV Name Matching (Suffix)

**Logic**: AWS `lineitem_resourceid` ends with OCP `persistentvolume` name

**Example**:
```
AWS:  vol-pvc-abc123-shared-disk
OCP:  shared-disk
Match: ✅ (AWS ends with OCP PV name)
```

**Trino SQL** (`1_resource_matching_by_cluster.sql`, line ~76):
```sql
WHERE substr(aws.lineitem_resourceid, -length(ocp.persistentvolume)) = ocp.persistentvolume
```

**POC Code** (`src/resource_matcher.py`):
```python
def pv_suffix_match(aws_resource_id: str, pv_name: str) -> bool:
    return aws_resource_id.endswith(pv_name)
```

**Test Scenario**: `Scenario 22`

---

## Tag Matching

### Overview

AWS resources tagged with OpenShift metadata are matched to OCP resources.

### 1. openshift_cluster Tag

**Logic**: AWS `openshift_cluster` tag equals OCP `cluster_id` OR `cluster_alias`

**Example**:
```json
AWS Tags: {"openshift_cluster": "my-prod-cluster"}
OCP: cluster_id = "my-prod-cluster"
Match: ✅
```

**Trino SQL** (`2_summarize_data_by_cluster.sql`, lines 637-639):
```sql
WHERE json_query(aws.tags, 'strict $.openshift_cluster' OMIT QUOTES) = ocp.cluster_id
   OR json_query(aws.tags, 'strict $.openshift_cluster' OMIT QUOTES) = ocp.cluster_alias
```

**POC Code** (`src/tag_matcher.py`):
```python
def match_cluster_tag(aws_tags: dict, ocp_cluster_id: str, ocp_cluster_alias: str) -> bool:
    cluster_tag = aws_tags.get('openshift_cluster')
    return cluster_tag == ocp_cluster_id or cluster_tag == ocp_cluster_alias
```

**Test Scenarios**: `Scenario 02`, `Scenario 20`

---

### 2. openshift_project Tag

**Logic**: AWS `openshift_project` tag equals OCP `namespace`

**Example**:
```json
AWS Tags: {"openshift_project": "production-app"}
OCP: namespace = "production-app"
Match: ✅ → Full cost attributed to namespace
```

**Trino SQL** (`2_summarize_data_by_cluster.sql`, line 637):
```sql
WHERE json_query(aws.tags, 'strict $.openshift_project' OMIT QUOTES) = ocp.namespace
```

**POC Code** (`src/tag_matcher.py`):
```python
def match_namespace_tag(aws_tags: dict, ocp_namespace: str) -> bool:
    return aws_tags.get('openshift_project') == ocp_namespace
```

**Test Scenario**: `Scenario 19` (Non-CSI storage attribution)

---

### 3. openshift_node Tag

**Logic**: AWS `openshift_node` tag equals OCP `node` name

**Example**:
```json
AWS Tags: {"openshift_node": "worker-1"}
OCP: node = "worker-1"
Match: ✅
```

**Trino SQL** (`2_summarize_data_by_cluster.sql`, line 638):
```sql
WHERE json_query(aws.tags, 'strict $.openshift_node' OMIT QUOTES) = ocp.node
```

**POC Code** (`src/tag_matcher.py`):
```python
def match_node_tag(aws_tags: dict, ocp_node: str) -> bool:
    return aws_tags.get('openshift_node') == ocp_node
```

**Test Scenario**: `Scenario 02`

---

### 4. Generic Tags (pod_labels, volume_labels)

**Logic**: Any AWS tag key exists as substring in OCP `pod_labels` or `volume_labels` JSON

**Example**:
```json
AWS Tags: {"app": "frontend", "tier": "web"}
OCP pod_labels: '{"app": "frontend", "environment": "prod"}'
Match: ✅ ("app" exists in both)
```

**Trino SQL** (`2_summarize_data_by_cluster.sql`, lines 641-642):
```sql
WHERE any_match(
    map_keys(cast(json_parse(aws.tags) as map(varchar, varchar))),
    x -> strpos(ocp.pod_labels, x) != 0
)
```

**POC Code** (`src/tag_matcher.py`):
```python
def match_generic_tags(aws_tags: dict, ocp_labels: str) -> bool:
    for tag_key in aws_tags.keys():
        if tag_key in ocp_labels:
            return True
    return False
```

**Test Scenarios**: `Scenario 21` (volume_labels), `Scenario 23` (pod_labels)

---

## Storage Matching

### CSI Storage (with csi_volume_handle)

1. OCP reports `csi_volume_handle` from CSI driver
2. POC matches to AWS EBS `lineitem_resourceid` via substring
3. Cost is proportionally attributed based on PVC usage

**Test Scenario**: `Scenario 05`

---

### Non-CSI Storage (tag-based)

For EBS volumes without CSI handles but tagged with `openshift_project`:

1. AWS EBS has `openshift_project: namespace-name` tag
2. POC matches tag to OCP namespace
3. **Full cost** is attributed directly to namespace (no proportioning)

**Important**: This handles legacy OCP 3.x and manually provisioned volumes.

**Test Scenario**: `Scenario 19`

---

### Multi-Cluster Shared Storage

For EBS volumes shared across multiple OCP clusters:

1. Calculate **global** disk capacity (not per-cluster)
2. Sum all PVC usage from all clusters
3. Attribute proportionally: `(pvc_gb / global_capacity) * cost`
4. Remaining capacity goes to "Storage unattributed"

**Test Scenario**: `Scenario 18`

---

## Cost Attribution

### Compute Costs

| Method | Formula | When Used |
|--------|---------|-----------|
| CPU-only | `pod_cpu / node_cpu * node_cost` | Default (Trino compatible) |
| Memory-only | `pod_memory / node_memory * node_cost` | Configurable |
| Weighted | `0.73 * cpu_ratio + 0.27 * memory_ratio` | Configurable |

**Configuration** (`config/config.yaml`):
```yaml
cost:
  distribution:
    method: cpu  # cpu, memory, or weighted
```

---

### Storage Costs (CSI)

```
storage_cost = (pvc_capacity / disk_capacity) * ebs_cost
```

**Test Scenario**: `Scenario 05`

---

### Network Costs

- Data transfer IN/OUT detected from `lineitem_usagetype`
- Attributed to "Network unattributed" namespace

**Test Scenario**: `Scenario 13`

---

## Test Scenarios

### Complete Scenario Matrix

| # | Name | Matching Type | Status |
|---|------|---------------|--------|
| 01 | Resource ID Matching | EC2/Node suffix | ✅ |
| 02 | Tag Matching | cluster, node tags | ✅ |
| 03 | Multi-Namespace | Multiple namespaces | ✅ |
| 04 | Network Costs | Data transfer | ✅ |
| 05 | Storage EBS | CSI substring | ✅ |
| 06 | Multi-Cluster | Multiple clusters | ✅ |
| 07 | Partial Matching | Mixed match rates | ✅ |
| 08 | Zero Usage | Edge case | ✅ |
| 09 | Cost Types | Blended/unblended | ✅ |
| 10 | Unmatched Storage | No match | ✅ |
| 11 | Corrupted Data | Bad input | ✅ |
| 12 | Trino Precision | Float precision | ✅ |
| 13 | Network Transfer | IN/OUT detection | ✅ |
| 14 | SavingsPlan | COST-5098 | ✅ |
| 15 | RDS Database | Tag-based | ✅ |
| 16 | S3 Storage | Tag-based | ✅ |
| 17 | Reserved Instances | RI handling | ✅ |
| 18 | Shared CSI Disk | Global capacity | ✅ |
| 19 | Non-CSI Storage | openshift_project tag | ✅ |
| 20 | Cluster Alias | cluster_alias match | ✅ |
| 21 | Volume Labels | Generic tags | ✅ |
| 22 | PV Name Suffix | PV name match | ✅ |
| 23 | Pod Labels | Generic pod tags | ✅ |

**Pass Rate**: 23/23 (100%)

---

## Code References

### Key Files

| File | Purpose |
|------|---------|
| `src/resource_matcher.py` | Resource ID matching (suffix, substring) |
| `src/tag_matcher.py` | Tag matching (cluster, namespace, node, generic) |
| `src/cost_attributor.py` | Cost attribution logic |
| `src/disk_capacity_calculator.py` | Storage capacity calculation |
| `src/network_cost_handler.py` | Network cost detection |

### Trino SQL Files (Reference)

| File | Purpose |
|------|---------|
| `1_resource_matching_by_cluster.sql` | Resource ID matching queries |
| `2_summarize_data_by_cluster.sql` | Tag matching and aggregation |

---

## Quick Reference

### Match Type Decision Tree

```
Is there a resource_id match?
├── YES → Use resource ID matching
│   ├── EC2/Node? → Suffix match
│   ├── CSI Volume? → Substring match
│   └── PV Name? → Suffix match
│
└── NO → Use tag matching
    ├── Has openshift_project? → Namespace match
    ├── Has openshift_cluster? → Cluster match
    ├── Has openshift_node? → Node match
    ├── Has generic tags? → Label match
    └── No tags? → Unattributed
```

---

*Document last updated: November 25, 2025*
*POC Version: 1.0*
*Trino Parity: 100%*


