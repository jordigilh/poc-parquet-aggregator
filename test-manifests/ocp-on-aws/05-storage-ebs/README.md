# Scenario 05: Storage EBS Attribution

## Overview

Tests EBS volume cost attribution via CSI volume handle matching.

## What This Tests

- OCP PersistentVolume has `csi_volume_handle` field
- AWS EBS `lineitem_resourceid` contains volume ID
- CSI handle matches EBS volume ID
- Storage costs attributed to namespace owning the PVC

## Test Data

**OCP:**
- Namespace `backend` with PVC
- PV with `csi_volume_handle: vol-0abc123def456`
- PVC capacity: 100 GB

**AWS:**
- EBS volume `vol-0abc123def456`
- Storage cost: $10.00/month

## Expected Outcome

```yaml
expected_outcome:
  total_cost: 10.00
  storage_attributed: true
  namespace_with_storage: backend
```

## How to Run

```bash
./scripts/run_ocp_aws_scenario_tests.sh 05
```

## Validation Query

```sql
SELECT 
    namespace,
    persistentvolumeclaim,
    csi_volume_handle,
    ROUND(persistentvolumeclaim_capacity_gigabyte::numeric, 2) as capacity_gb,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE data_source = 'Storage'
GROUP BY namespace, persistentvolumeclaim, csi_volume_handle, persistentvolumeclaim_capacity_gigabyte;
```

## Files

- `manifest.yml` - Main test manifest
- `variation.yml` - Multiple PVCs across namespaces

