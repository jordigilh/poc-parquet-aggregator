# POC Validation Workflow - Using Nise Static Data

## Overview

This document describes the validation workflow for the OCP Parquet Aggregator POC using nise static YAML configurations for predictable, mathematical validation.

## Why Nise Static Data?

**Confidence: 95%** ✅

- ✅ **100% Predictable**: Every value is explicitly defined in YAML
- ✅ **Mathematically Verifiable**: Can calculate expected results
- ✅ **Battle-Tested**: Same configs used in Koku's CI/CD
- ✅ **Zero Randomization**: Completely deterministic output

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Install nise
pip install koku-nise

# Set environment variables
cp env.example .env
# Edit .env with your credentials
export $(cat .env | xargs)
```

### Run Minimal Validation (Recommended First)

```bash
# Make script executable
chmod +x scripts/run_poc_validation.sh

# Run minimal test (3 days, 2 nodes, 4 pods)
./scripts/run_poc_validation.sh minimal
```

### Run Full Validation

```bash
# Run full test (using complete ocp_static_data.yml)
./scripts/run_poc_validation.sh full
```

## Validation Modes

### Mode 1: Minimal (Quick Test)

**Purpose**: Validate core aggregation logic with minimal data

**Configuration**: `config/ocp_poc_minimal.yml`

**Data**:
- 2 nodes (1 compute, 1 master)
- 3 namespaces (test-app, monitoring, kube-system)
- 4 pods
- 1 storage volume
- 3 days (2025-11-01 to 2025-11-03)

**Expected Output**: 9 summary rows (3 days × 3 namespace-node combinations)

**Expected Metrics** (per day):
```
Namespace: test-app, Node: poc_node_compute_1
  pod_request_cpu_core_hours: 2.0
  pod_request_memory_gigabyte_hours: 4.0
  node_capacity_cpu_core_hours: 96.0

Namespace: monitoring, Node: poc_node_compute_1
  pod_request_cpu_core_hours: 0.75
  pod_request_memory_gigabyte_hours: 1.5
  node_capacity_cpu_core_hours: 96.0

Namespace: kube-system, Node: poc_node_master_1
  pod_request_cpu_core_hours: 12.0
  pod_request_memory_gigabyte_hours: 24.0
  node_capacity_cpu_core_hours: 48.0
```

**Duration**: ~2 minutes

### Mode 2: Full (Comprehensive Test)

**Purpose**: Validate against production-like data

**Configuration**: `dev/scripts/nise_ymls/ocp_on_aws/ocp_static_data.yml`

**Data**:
- 4 nodes (3 compute, 1 master)
- 7 namespaces
- 13 pods
- 4 storage volumes
- 30 days (configurable)

**Expected Output**: ~84 summary rows (30 days × ~3 namespace-node combinations)

**Duration**: ~10 minutes

## Manual Step-by-Step Validation

### Step 1: Calculate Expected Results

```bash
python -m src.expected_results \
    config/ocp_poc_minimal.yml \
    --print \
    --output expected_results.csv
```

**Output**:
```
================================================================================
EXPECTED RESULTS SUMMARY
================================================================================
Total Rows: 9
Date Range: 2025-11-01 to 2025-11-03
Nodes: 2 (poc_node_compute_1, poc_node_master_1)
Namespaces: 3 (test-app, monitoring, kube-system)

Total Metrics:
  Total CPU Request:    44.25 core-hours
  Total Memory Request: 79.50 GB-hours
  Total CPU Capacity:   864.00 core-hours
  Total Memory Capacity:1,728.00 GB-hours

Per-Day Breakdown:
  2025-11-01:
    Rows: 3
    CPU Request: 14.75 core-hours
    Memory Request: 26.50 GB-hours
  ...
================================================================================
```

### Step 2: Generate Test Data with Nise

```bash
nise report ocp \
    --static-report-file config/ocp_poc_minimal.yml \
    --ocp-cluster-id poc-test-cluster \
    --start-date 2025-11-01 \
    --end-date 2025-11-03 \
    --write-monthly \
    --insights-upload /tmp/poc-nise-data
```

**Output**: CSV files with OCP usage data

### Step 3: Convert CSV to Parquet (via MASU)

**Option A**: Use existing MASU pipeline
```bash
# Trigger MASU processing (requires running Koku instance)
# This will automatically convert CSV → Parquet → Upload to S3
```

**Option B**: Manual conversion (for POC testing)
```bash
# Use MASU's parquet_report_processor directly
python -m koku.masu.processor.parquet.parquet_report_processor \
    --csv-dir /tmp/poc-nise-data \
    --output-dir /tmp/poc-parquet \
    --provider-uuid poc-test-provider
```

### Step 4: Upload Parquet to S3

```bash
# Use AWS CLI or MinIO client
aws --endpoint-url $S3_ENDPOINT s3 sync \
    /tmp/poc-parquet \
    s3://$S3_BUCKET/data/poc-test-provider/2025/11/
```

### Step 5: Run POC Aggregator with Validation

```bash
export OCP_PROVIDER_UUID="poc-test-provider"
export OCP_CLUSTER_ID="poc-test-cluster"
export OCP_YEAR="2025"
export OCP_MONTH="11"

python -m src.main \
    --truncate \
    --validate-expected config/ocp_poc_minimal.yml
```

**Expected Output**:
```
================================================================================
POC COMPLETED SUCCESSFULLY
================================================================================
Total duration: 12.3s
Input rows: 1,234
Output rows: 9
Compression ratio: 137.1x
Processing rate: 100 rows/sec
================================================================================

================================================================================
✅ VALIDATION SUCCESS: ALL RESULTS MATCH EXPECTED VALUES!
================================================================================
Matched 90/90 comparisons
================================================================================
```

### Step 6: Verify in PostgreSQL

```bash
psql -h $POSTGRES_HOST -U koku -d koku -c "
SELECT
    usage_start,
    namespace,
    node,
    ROUND(pod_request_cpu_core_hours::numeric, 2) as cpu_req,
    ROUND(pod_request_memory_gigabyte_hours::numeric, 2) as mem_req
FROM $POSTGRES_SCHEMA.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = 'poc-test-provider'
  AND year = '2025'
  AND month = '11'
ORDER BY usage_start, namespace, node;
"
```

**Expected Results**:
```
 usage_start |  namespace  |         node         | cpu_req | mem_req
-------------+-------------+----------------------+---------+---------
 2025-11-01  | kube-system | poc_node_master_1    |   12.00 |   24.00
 2025-11-01  | monitoring  | poc_node_compute_1   |    0.75 |    1.50
 2025-11-01  | test-app    | poc_node_compute_1   |    2.00 |    4.00
 2025-11-02  | kube-system | poc_node_master_1    |   12.00 |   24.00
 2025-11-02  | monitoring  | poc_node_compute_1   |    0.75 |    1.50
 2025-11-02  | test-app    | poc_node_compute_1   |    2.00 |    4.00
 2025-11-03  | kube-system | poc_node_master_1    |   12.00 |   24.00
 2025-11-03  | monitoring  | poc_node_compute_1   |    0.75 |    1.50
 2025-11-03  | test-app    | poc_node_compute_1   |    2.00 |    4.00
(9 rows)
```

## Understanding the Validation

### How Expected Results are Calculated

From the YAML configuration:

```yaml
- pod:
  pod_name: test_pod_1a
  cpu_request: 1
  mem_request_gig: 2
  pod_seconds: 3600  # 1 hour
```

**Expected Aggregation**:
```python
# CPU
pod_request_cpu_core_hours = cpu_request * (pod_seconds / 3600)
                           = 1 * (3600 / 3600)
                           = 1.0

# Memory
pod_request_memory_gigabyte_hours = mem_request_gig * (pod_seconds / 3600)
                                  = 2 * (3600 / 3600)
                                  = 2.0

# Node Capacity (24-hour day)
node_capacity_cpu_core_hours = node.cpu_cores * 24
                             = 4 * 24
                             = 96.0
```

### Validation Comparison

The POC compares:
1. **Row Count**: Expected vs Actual rows
2. **Metric Values**: Each metric compared with 0.01% tolerance
3. **Missing Rows**: Rows in expected but not in actual
4. **Extra Rows**: Rows in actual but not in expected

**Success Criteria**:
- All rows present (no missing, no extra)
- All metric values within 0.01% tolerance
- 100% of comparisons pass

## Troubleshooting

### Issue: Expected results don't match

**Check**:
1. YAML configuration is correct
2. Date range matches between nise generation and POC
3. Provider UUID is consistent
4. Enabled tag keys are correct in PostgreSQL

### Issue: No Parquet files found

**Check**:
1. CSV to Parquet conversion completed
2. Parquet files uploaded to correct S3 path
3. S3 credentials are correct
4. S3 path follows pattern: `data/{provider_uuid}/{year}/{month}/`

### Issue: POC aggregation fails

**Check**:
1. PostgreSQL connection is working
2. S3 connection is working
3. Schema exists in PostgreSQL
4. Enabled tag keys query returns results

## Success Metrics

### Minimal Validation

- ✅ 9 rows generated
- ✅ All metrics match expected (0.00% error)
- ✅ Processing time < 60 seconds
- ✅ Memory usage < 500 MB

### Full Validation

- ✅ 84+ rows generated
- ✅ All metrics match expected (< 0.01% error)
- ✅ Processing time < 2 minutes
- ✅ Memory usage < 1 GB

## Next Steps After Validation

### If All Tests Pass ✅

1. **Document Results**: Add performance metrics to POC_VALIDATION_STRATEGY.md
2. **Compare with Trino**: Run same data through Trino SQL, compare results
3. **Performance Optimization**: If needed, optimize based on benchmarks
4. **Decision Meeting**: Present results, get Go/No-Go for full implementation

### If Tests Fail ❌

1. **Review Discrepancies**: Analyze which metrics don't match
2. **Debug Aggregation Logic**: Check aggregator_pod.py for errors
3. **Verify Capacity Calculation**: Ensure node/cluster capacity is correct
4. **Check Label Filtering**: Verify enabled tags are applied correctly
5. **Re-run with Debug Logging**: `export LOG_LEVEL=DEBUG`

## Files Reference

- `config/ocp_poc_minimal.yml`: Minimal test configuration
- `src/expected_results.py`: Expected results calculator
- `src/main.py`: POC main entry point with validation
- `scripts/run_poc_validation.sh`: Automated validation workflow
- `expected_results.csv`: Generated expected results (gitignored)

## Timeline

- **Week 1**: Minimal validation (3 days data)
- **Week 2**: Full validation (30 days data)
- **Week 3**: Trino comparison + performance optimization

## Confidence

**95%** - Using nise static data provides the highest confidence for POC validation.

The remaining 5% uncertainty is addressed during actual execution when we validate floating-point precision and edge cases.

