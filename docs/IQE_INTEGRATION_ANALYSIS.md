# IQE Integration Analysis for POC Validation

## Executive Summary

**Recommendation: Option 2 - Generate nise data from IQE YAML and validate against expected values**

This approach provides the best balance of:
- ✅ Predictable, deterministic test data
- ✅ Known expected results for validation
- ✅ No dependency on full Koku/IQE infrastructure
- ✅ Reusable for CI/CD pipeline
- ✅ Fast iteration cycle

## Option 1: Run Full IQE Tests Against POC

### What This Involves

Running the actual IQE test suite (`test__i_source.py`) against the POC aggregator instead of the production Trino SQL path.

### Pros
- ✅ Uses production-grade test suite
- ✅ Comprehensive coverage (all edge cases)
- ✅ Validates API contract compatibility
- ✅ Tests real-world scenarios

### Cons
- ❌ Requires full Koku infrastructure (API, MASU, PostgreSQL, Kafka, etc.)
- ❌ Complex setup and dependencies
- ❌ Slow feedback loop (minutes to hours)
- ❌ Hard to debug failures (many moving parts)
- ❌ POC doesn't have API layer yet (only aggregator + DB)
- ❌ Would need to mock/bypass API calls
- ❌ Overkill for POC validation

### Feasibility: **Medium-Low**

The POC is currently just:
```
Parquet Files → Aggregator → PostgreSQL
```

IQE tests expect:
```
Nise → S3 → MASU → Trino → API → Tests
```

We'd need to:
1. Build API layer or mock it
2. Set up full Koku environment
3. Modify IQE tests to bypass API and query PostgreSQL directly
4. Handle authentication, RBAC, etc.

**Estimated Effort: 3-5 days**

## Option 2: Generate Nise Data from IQE YAML + Validate Expected Results ⭐ RECOMMENDED

### What This Involves

1. Use IQE YAML configs (e.g., `ocp_report_advanced.yml`) to generate nise data
2. Run POC aggregator on this data
3. Use IQE's `read_ocp_resources_from_yaml()` helper to calculate expected values
4. Compare POC output against expected values directly in PostgreSQL

### Pros
- ✅ **Deterministic**: Same input always produces same output
- ✅ **Known expectations**: IQE already calculates expected values
- ✅ **Self-contained**: No external dependencies
- ✅ **Fast**: Runs in seconds
- ✅ **Debuggable**: Clear input → output → expected mapping
- ✅ **Reusable**: Can be automated in CI/CD
- ✅ **Comprehensive**: IQE YAMLs cover many edge cases

### Cons
- ❌ Need to extract/adapt IQE's calculation logic
- ❌ Doesn't test full E2E flow (but POC isn't E2E anyway)
- ❌ Need to handle date calculations (last_month, etc.)

### Implementation Plan

#### Phase 1: Extract IQE Calculation Logic (1 day)

Create `poc-parquet-aggregator/src/iqe_validator.py`:

```python
def read_ocp_resources_from_yaml(yaml_file_path: str) -> Dict:
    """
    Adapted from IQE's helpers.py:read_ocp_resources_from_yaml()

    Calculates expected values for:
    - CPU usage/request/capacity per pod/namespace/node/cluster
    - Memory usage/request/capacity per pod/namespace/node/cluster
    - Storage usage/request/capacity per PVC

    Returns nested dict with expected values.
    """
    # Parse YAML
    # Calculate totals per pod, namespace, node, cluster
    # Handle edge cases (nise limits, PV splitting, etc.)
    pass

def validate_poc_results(
    postgres_results: pd.DataFrame,
    expected_values: Dict,
    tolerance: float = 0.0001
) -> ValidationReport:
    """
    Compare POC aggregation results against expected values.

    Returns detailed report with:
    - Pass/fail per metric
    - Actual vs expected values
    - Percentage differences
    """
    pass
```

#### Phase 2: Generate Test Data (0.5 days)

Enhance `scripts/generate_iqe_test_data.sh`:

```bash
#!/bin/bash
# Generate nise data from IQE YAML

IQE_YAML="ocp_report_advanced.yml"
OUTPUT_DIR="/tmp/nise-iqe-data"

# Copy IQE YAML to POC directory
cp "../iqe-cost-management-plugin/iqe_cost_management/data/openshift/${IQE_YAML}" \
   "config/${IQE_YAML}"

# Generate data with nise
nise report ocp \
    --static-report-file "config/${IQE_YAML}" \
    --ocp-cluster-id "iqe-test-cluster" \
    --insights-upload "${OUTPUT_DIR}" \
    --write-monthly

# Convert to Parquet and upload to MinIO
python3 scripts/csv_to_parquet_minio.py --csv-dir "${OUTPUT_DIR}"
```

#### Phase 3: Validation Script (1 day)

Create `scripts/validate_against_iqe.py`:

```python
#!/usr/bin/env python3
"""
Validate POC aggregation results against IQE expected values.
"""

import sys
from src.iqe_validator import read_ocp_resources_from_yaml, validate_poc_results
from src.db_writer import DatabaseWriter

def main():
    # 1. Load IQE YAML and calculate expected values
    expected = read_ocp_resources_from_yaml("config/ocp_report_advanced.yml")

    # 2. Query POC results from PostgreSQL
    db = DatabaseWriter(config)
    actual_df = db.read_summary_data()

    # 3. Validate
    report = validate_poc_results(actual_df, expected)

    # 4. Print report
    print(report.summary())

    # 5. Exit with appropriate code
    sys.exit(0 if report.all_passed else 1)

if __name__ == "__main__":
    main()
```

#### Phase 4: Integration (0.5 days)

Update `scripts/run_poc_validation.sh`:

```bash
#!/bin/bash
set -e

echo "=== POC Validation with IQE Test Data ==="

# 1. Start local environment
./scripts/start-local-env.sh

# 2. Generate IQE test data
./scripts/generate_iqe_test_data.sh

# 3. Run POC aggregator
python3 -m src.main --truncate

# 4. Validate against IQE expectations
python3 scripts/validate_against_iqe.py

echo "✅ POC validation complete!"
```

### Feasibility: **High**

All components exist:
- ✅ IQE YAML configs (20+ test scenarios)
- ✅ IQE calculation logic (in `helpers.py`)
- ✅ Nise can generate from YAML
- ✅ POC can process the data
- ✅ PostgreSQL has the results

Just need to connect them!

**Estimated Effort: 2-3 days**

## Option 3: Hybrid Approach

### What This Involves

1. Use IQE YAML for data generation (Option 2)
2. Run simplified IQE tests that only validate PostgreSQL results (not full API)

### Pros
- ✅ Best of both worlds
- ✅ Can reuse some IQE test logic
- ✅ More "official" validation

### Cons
- ❌ More complex than Option 2
- ❌ Still need to adapt IQE tests
- ❌ Longer implementation time

### Feasibility: **Medium**

**Estimated Effort: 4-5 days**

## Recommended IQE Test Scenarios for POC

Based on analysis of IQE test suite, these scenarios provide comprehensive coverage:

### 1. **ocp_report_advanced.yml** ⭐ PRIMARY
- **Coverage**: Multi-node, multi-namespace, multiple pods, volumes
- **Edge Cases**:
  - Empty namespaces
  - Multiple volumes per pod
  - Cross-node projects
  - Various label combinations
- **Complexity**: High
- **Why**: Most comprehensive single test

### 2. **today_ocp_report_multiple_nodes_projects.yml**
- **Coverage**: Multi-node resource allocation
- **Edge Cases**: Pods spanning multiple nodes
- **Complexity**: Medium

### 3. **ocp_report_missing_items.yml**
- **Coverage**: Missing/null data handling
- **Edge Cases**:
  - Pods without labels
  - Nodes without capacity
  - Empty usage values
- **Complexity**: Medium
- **Why**: Tests robustness

### 4. **ocp_report_0_template.yml**
- **Coverage**: Basic single-node scenario
- **Edge Cases**: Minimal
- **Complexity**: Low
- **Why**: Baseline sanity check

## Expected Validation Metrics

Based on IQE test suite, we should validate:

### Per-Pod Metrics
- `pod_usage_cpu_core_hours`
- `pod_request_cpu_core_hours`
- `pod_effective_usage_cpu_core_hours` (greatest of usage/request)
- `pod_limit_cpu_core_hours`
- `pod_usage_memory_gigabyte_hours`
- `pod_request_memory_gigabyte_hours`
- `pod_effective_usage_memory_gigabyte_hours`
- `pod_limit_memory_gigabyte_hours`

### Per-Node Metrics
- `node_capacity_cpu_cores`
- `node_capacity_cpu_core_hours`
- `node_capacity_memory_gigabytes`
- `node_capacity_memory_gigabyte_hours`

### Per-Cluster Metrics
- `cluster_capacity_cpu_core_hours`
- `cluster_capacity_memory_gigabyte_hours`

### Aggregation Validation
- **Row Count**: Expected number of summary rows
- **Namespace Count**: Distinct namespaces
- **Node Count**: Distinct nodes
- **Label Merging**: Correct pod+node+namespace label merge
- **Unused Capacity**: `capacity - max(usage, request)`
- **Unused Request**: `request - usage`

## Implementation Checklist

- [ ] Extract IQE calculation logic to `src/iqe_validator.py`
- [ ] Create `scripts/generate_iqe_test_data.sh`
- [ ] Create `scripts/validate_against_iqe.py`
- [ ] Update `scripts/run_poc_validation.sh`
- [ ] Test with `ocp_report_0_template.yml` (simple)
- [ ] Test with `ocp_report_advanced.yml` (complex)
- [ ] Test with `ocp_report_missing_items.yml` (edge cases)
- [ ] Document validation results
- [ ] Add to CI/CD pipeline

## Success Criteria

✅ POC passes validation for:
1. **ocp_report_0_template.yml** - 100% match
2. **ocp_report_advanced.yml** - 100% match within 0.01% tolerance
3. **ocp_report_missing_items.yml** - Handles nulls correctly

## Timeline Estimate

- **Option 1 (Full IQE)**: 3-5 days, Medium-Low feasibility
- **Option 2 (YAML + Expected Values)**: 2-3 days, High feasibility ⭐
- **Option 3 (Hybrid)**: 4-5 days, Medium feasibility

## Recommendation

**Proceed with Option 2** for the following reasons:

1. **Speed**: Can be implemented in 2-3 days
2. **Reliability**: Deterministic, repeatable results
3. **Debuggability**: Clear failure points
4. **Automation**: Easy to integrate into CI/CD
5. **Coverage**: IQE YAMLs are comprehensive
6. **Validation**: Uses IQE's own calculation logic

Once Option 2 is proven, we can consider Option 3 (running actual IQE tests) for the full production implementation.

