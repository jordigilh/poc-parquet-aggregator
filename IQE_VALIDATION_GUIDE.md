# IQE-based Validation Guide

## Overview

This guide explains how to validate the POC aggregator using IQE test data **without requiring any IQE infrastructure dependencies**. We generate nise data from IQE YAML configs and validate results using reimplemented IQE calculation logic.

## Architecture

```
IQE YAML Config
      ↓
   [nise]  ← Generate synthetic data
      ↓
   CSV Files
      ↓
[CSV→Parquet Converter]
      ↓
   MinIO (S3)
      ↓
[POC Aggregator]
      ↓
  PostgreSQL
      ↓
[IQE Validator] ← Compare with expected values
      ↓
 Validation Report
```

## Prerequisites

1. **Local environment running**:
   ```bash
   ./scripts/start-local-env.sh
   ```

2. **Python venv activated**:
   ```bash
   source venv/bin/activate
   ```

3. **IQE plugin repository** (for YAML configs):
   ```bash
   # Should be at: ../iqe-cost-management-plugin
   # Or set: export IQE_PLUGIN_DIR=/path/to/iqe-cost-management-plugin
   ```

## Quick Start

### Option 1: Full End-to-End Validation (Recommended)

Run everything with one command:

```bash
./scripts/run_iqe_validation.sh
```

This will:
1. ✅ Start local environment (MinIO + PostgreSQL)
2. ✅ Generate nise data from IQE YAML
3. ✅ Convert CSV to Parquet
4. ✅ Upload to MinIO
5. ✅ Run POC aggregator
6. ✅ Validate against expected values
7. ✅ Generate detailed report

### Option 2: Step-by-Step Validation

#### Step 1: Generate Test Data

```bash
# Use default (ocp_report_advanced.yml)
./scripts/generate_iqe_test_data.sh

# Or specify a different YAML
IQE_YAML=ocp_report_0_template.yml ./scripts/generate_iqe_test_data.sh
```

This creates CSV files in `/tmp/nise-iqe-data/`.

#### Step 2: Convert and Upload to MinIO

```bash
python3 scripts/csv_to_parquet_minio.py --csv-dir /tmp/nise-iqe-data
```

#### Step 3: Run POC Aggregator

```bash
export S3_ENDPOINT=http://localhost:9000
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
export S3_BUCKET=cost-management
export POSTGRES_HOST=localhost
export POSTGRES_DB=koku
export POSTGRES_USER=koku
export POSTGRES_PASSWORD=koku123
export POSTGRES_SCHEMA=org1234567
export OCP_PROVIDER_UUID=00000000-0000-0000-0000-000000000002
export OCP_CLUSTER_ID=iqe-test-cluster
export ORG_ID=1234567
export PROVIDER_TYPE=OCP

python3 -m src.main --truncate
```

#### Step 4: Validate Results

```bash
export IQE_YAML_FILE=config/ocp_report_advanced.yml
python3 scripts/validate_against_iqe.py
```

## Available IQE Test Scenarios

### 1. **ocp_report_0_template.yml** (Simple)
- **Complexity**: Low
- **Coverage**: 2 nodes, 3 namespaces, 3 pods
- **Best for**: Quick sanity checks
- **Expected Results**:
  - Cluster CPU: 22 core-hours usage, 28 cores capacity
  - Cluster Memory: 22 GB-hours usage, 26 GB capacity

```bash
IQE_YAML=ocp_report_0_template.yml ./scripts/run_iqe_validation.sh
```

### 2. **ocp_report_advanced.yml** (Comprehensive) ⭐ RECOMMENDED
- **Complexity**: High
- **Coverage**: 3 nodes, 10+ namespaces, 15+ pods, multiple volumes
- **Edge Cases**:
  - Empty namespaces
  - Multiple volumes per pod
  - Cross-node projects
  - Various label combinations
- **Best for**: Comprehensive validation

```bash
IQE_YAML=ocp_report_advanced.yml ./scripts/run_iqe_validation.sh
```

### 3. **ocp_report_missing_items.yml** (Edge Cases)
- **Complexity**: Medium
- **Coverage**: Missing/null data handling
- **Edge Cases**:
  - Pods without labels
  - Nodes without capacity
  - Empty usage values
- **Best for**: Robustness testing

```bash
IQE_YAML=ocp_report_missing_items.yml ./scripts/run_iqe_validation.sh
```

### 4. **today_ocp_report_multiple_nodes_projects.yml** (Multi-node)
- **Complexity**: Medium
- **Coverage**: Multi-node resource allocation
- **Best for**: Testing cross-node aggregation

```bash
IQE_YAML=today_ocp_report_multiple_nodes_projects.yml ./scripts/run_iqe_validation.sh
```

## Validation Metrics

The validator checks:

### Cluster-Level
- ✅ Total CPU usage (core-hours)
- ✅ Total CPU requests (core-hours)
- ✅ Total CPU capacity (cores)
- ✅ Total memory usage (GB-hours)
- ✅ Total memory requests (GB-hours)
- ✅ Total memory capacity (GB)

### Node-Level
- ✅ Per-node CPU usage/requests/capacity
- ✅ Per-node memory usage/requests/capacity

### Namespace-Level
- ✅ Per-namespace CPU usage/requests
- ✅ Per-namespace memory usage/requests

### Pod-Level (Future)
- 🔜 Per-pod CPU usage/requests
- 🔜 Per-pod memory usage/requests

## Understanding Validation Results

### Success Example

```
================================================================================
IQE Validation Report
================================================================================
Total Checks: 24
Passed: 24 ✅
Failed: 0 ❌
Tolerance: 0.0100%
================================================================================
✅ ALL VALIDATIONS PASSED
```

### Failure Example

```
================================================================================
IQE Validation Report
================================================================================
Total Checks: 24
Passed: 22 ✅
Failed: 2 ❌
Tolerance: 0.0100%
================================================================================

Failed Checks:
--------------------------------------------------------------------------------
❌ node/qe-node/cpu_usage: expected=10.000000, actual=9.950000, diff=0.5000%
   Node capacity calculation may be incorrect
❌ cluster/total/memory_requests: expected=22.000000, actual=22.100000, diff=0.4545%
   Check memory unit conversions
================================================================================
```

## Tolerance Configuration

Default tolerance: **0.01%** (0.0001)

To adjust:

```python
# In scripts/validate_against_iqe.py
report = validate_poc_results(actual_df, expected_values, tolerance=0.001)  # 0.1%
```

## Troubleshooting

### Issue: "IQE YAML file not found"

**Solution**: Set the correct path to IQE plugin:

```bash
export IQE_PLUGIN_DIR=/path/to/iqe-cost-management-plugin
./scripts/generate_iqe_test_data.sh
```

### Issue: "nise is not installed"

**Solution**: Install nise in your venv:

```bash
source venv/bin/activate
pip install koku-nise
```

### Issue: "No CSV files generated"

**Solution**: Check nise output for errors. Ensure YAML is valid:

```bash
python3 -m src.iqe_validator /path/to/yaml/file.yml
```

### Issue: "Validation shows large differences"

**Possible causes**:
1. **Date mismatch**: Nise generates data for `last_month` by default
2. **Unit conversion**: Check seconds→hours, bytes→GB conversions
3. **Aggregation logic**: Review grouping keys in aggregator
4. **Label merging**: Verify pod+node+namespace label merge

**Debug steps**:

```bash
# 1. Check what nise generated
head -20 /tmp/nise-iqe-data/*ocp_pod_usage.csv

# 2. Check expected values
python3 -m src.iqe_validator config/ocp_report_advanced.yml

# 3. Check actual values in PostgreSQL
podman exec postgres-poc psql -U koku -d koku -c \
  "SELECT node, namespace, SUM(pod_usage_cpu_core_hours)
   FROM org1234567.reporting_ocpusagelineitem_daily_summary
   GROUP BY node, namespace ORDER BY node, namespace;"

# 4. Compare specific rows
python3 -c "
from src.iqe_validator import read_ocp_resources_from_yaml
expected = read_ocp_resources_from_yaml('config/ocp_report_advanced.yml')
print('Expected for qe-node:', expected['compute']['nodes']['qe-node'])
"
```

### Issue: "PostgreSQL connection failed"

**Solution**: Ensure local environment is running:

```bash
podman ps | grep postgres-poc
# If not running:
./scripts/start-local-env.sh
```

## CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/poc-validation.yml
name: POC Validation

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m venv venv
          source venv/bin/activate
          pip install -r requirements.txt

      - name: Start local environment
        run: ./scripts/start-local-env.sh

      - name: Run IQE validation
        run: |
          source venv/bin/activate
          ./scripts/run_iqe_validation.sh

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: validation-results
          path: |
            /tmp/nise-iqe-data/
            logs/
```

## Advanced Usage

### Test Multiple Scenarios

```bash
#!/bin/bash
SCENARIOS=(
    "ocp_report_0_template.yml"
    "ocp_report_advanced.yml"
    "ocp_report_missing_items.yml"
    "today_ocp_report_multiple_nodes_projects.yml"
)

for scenario in "${SCENARIOS[@]}"; do
    echo "Testing: $scenario"
    IQE_YAML=$scenario ./scripts/run_iqe_validation.sh
    if [ $? -ne 0 ]; then
        echo "❌ Failed: $scenario"
        exit 1
    fi
done

echo "✅ All scenarios passed!"
```

### Custom Expected Value Calculations

```python
from src.iqe_validator import read_ocp_resources_from_yaml

# Load expected values
expected = read_ocp_resources_from_yaml('config/ocp_report_advanced.yml')

# Calculate custom metrics
total_effective_usage = max(
    expected['compute']['usage'],
    expected['compute']['requests']
)

unused_capacity = expected['compute']['count'] - total_effective_usage

print(f"Unused capacity: {unused_capacity} cores")
```

## Next Steps

1. ✅ **Run simple validation**: `IQE_YAML=ocp_report_0_template.yml ./scripts/run_iqe_validation.sh`
2. ✅ **Run comprehensive validation**: `IQE_YAML=ocp_report_advanced.yml ./scripts/run_iqe_validation.sh`
3. ✅ **Test edge cases**: `IQE_YAML=ocp_report_missing_items.yml ./scripts/run_iqe_validation.sh`
4. 🔜 **Add storage validation** (volumes/PVCs)
5. 🔜 **Add pod-level validation**
6. 🔜 **Add label validation**
7. 🔜 **Integrate into CI/CD**

## Reference

- **IQE Plugin**: `../iqe-cost-management-plugin`
- **IQE YAML Configs**: `../iqe-cost-management-plugin/iqe_cost_management/data/openshift/`
- **IQE Calculation Logic**: `../iqe-cost-management-plugin/iqe_cost_management/fixtures/helpers.py:read_ocp_resources_from_yaml()`
- **POC Validator**: `src/iqe_validator.py`
- **Validation Script**: `scripts/validate_against_iqe.py`

