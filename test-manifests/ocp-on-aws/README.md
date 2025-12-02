# OCP-on-AWS Test Scenarios

This directory contains comprehensive test scenarios for validating the OCP-on-AWS cost aggregation pipeline. Each scenario tests a specific aspect of the cost attribution logic.

## Quick Start

### Prerequisites

1. Start the required containers:
   ```bash
   cd /path/to/poc-parquet-aggregator
   podman-compose up -d
   ```

2. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

### Running a Single Scenario

```bash
# Run scenario 01 (Resource Matching)
./scripts/run_single_scenario.sh 01-resource-matching

# Or run manually:
python src/main.py --manifest test-manifests/ocp-on-aws/01-resource-matching/manifest.yml
```

### Running All Scenarios

```bash
./scripts/run_ocp_aws_scenario_tests.sh
```

---

## Validation Methodology

### How E2E Validation Works (Core-Style)

The POC uses a **totals-based validation approach** that mirrors how Cost Management Core validates aggregation results. This approach validates:

1. **Total Cost** - Sum of all attributed costs matches expected value
2. **Row Count** - Number of output rows is within expected range
3. **Namespace Count** - Number of unique namespaces matches
4. **Namespace-Level Costs** - (Optional) Per-namespace cost breakdown

### Why Totals-Based Validation?

Core's validation philosophy focuses on **business outcomes** rather than implementation details:

- ✅ **Validates**: "Did the customer get charged the correct amount?"
- ✅ **Validates**: "Are costs attributed to the correct namespaces?"
- ❌ **Does NOT validate**: Specific row-by-row matching logic
- ❌ **Does NOT validate**: Internal implementation details

This approach ensures:
1. **Trino parity** - Results match what Trino would produce
2. **Business correctness** - Costs are accurate for billing
3. **Flexibility** - Implementation can change without breaking tests

### Validation Script

The primary validation script is [`scripts/validate_ocp_aws_totals.py`](../../scripts/validate_ocp_aws_totals.py):

```python
# Core validation query
SELECT
    COUNT(*) as total_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT cluster_id) as clusters,
    COUNT(DISTINCT namespace) as namespaces
FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE usage_start::date >= '{start_date}' AND usage_start::date < '{end_date}';
```

### Validation Tolerance

- **Cost tolerance**: $0.10 (10 cents) for floating-point precision
- **Row count tolerance**: ±20% for approximate matching
- **Namespace count tolerance**: ±20%

### What Each Scenario Validates

| Scenario | Primary Validation | Secondary Validation |
|----------|-------------------|---------------------|
| 01 Resource Matching | Total cost matches | `resource_id_matched=true` |
| 02 Tag Matching | Total cost matches | `tag_matched=true` |
| 03 Multi-Namespace | Namespace cost breakdown | Cost distribution ratios |
| 04 Network Costs | Network namespace exists | IN/OUT direction |
| 05 Storage EBS | Storage cost attributed | CSI handle present |
| 06 Multi-Cluster | Per-cluster costs | Cluster isolation |
| 07-23 | Various edge cases | Specific to scenario |

---

## Scenario Overview

### Phase 0: Happy Path (70% Confidence)

| # | Scenario | Description |
|---|----------|-------------|
| 01 | [Resource Matching](./01-resource-matching/) | EC2 instance ID matches OCP node resource_id |
| 02 | [Tag Matching](./02-tag-matching/) | AWS resource tags match OCP cluster/node |
| 03 | [Multi-Namespace](./03-multi-namespace/) | Cost distribution across multiple namespaces |
| 04 | [Network Costs](./04-network-costs/) | Data transfer costs to "Network unattributed" |
| 05 | [Storage EBS](./05-storage-ebs/) | EBS volume costs via CSI handle matching |
| 06 | [Multi-Cluster](./06-multi-cluster/) | Multiple OCP clusters on same AWS account |

### Phase 1: Critical Edge Cases (90% Confidence)

| # | Scenario | Description |
|---|----------|-------------|
| 07 | [Partial Matching](./07-partial-matching/) | Mix of matched and unmatched resources |
| 08 | [Zero Usage](./08-zero-usage/) | Pods with zero CPU/memory usage |
| 09 | [Cost Types](./09-cost-types/) | All AWS cost types (unblended, blended, amortized) |
| 10 | [Unmatched Storage](./10-unmatched-storage/) | Storage costs that can't be attributed |

### Phase 2: Resilience (99% Confidence)

| # | Scenario | Description |
|---|----------|-------------|
| 11 | [Corrupted Data](./11-corrupted-data/) | Handling malformed/missing data |
| 12 | [Trino Precision](./12-trino-precision/) | Decimal precision matching Trino output |

### Phase 3: Trino Compliance

| # | Scenario | Description |
|---|----------|-------------|
| 13 | [Network Data Transfer](./13-network-data-transfer/) | IN/OUT direction handling |
| 14 | [SavingsPlan Costs](./14-savingsplan-costs/) | AWS SavingsPlan cost attribution |

### Phase 4: AWS Services

| # | Scenario | Description |
|---|----------|-------------|
| 15 | [RDS Database Costs](./15-rds-database-costs/) | RDS costs via tag matching |
| 16 | [S3 Storage Costs](./16-s3-storage-costs/) | S3 bucket costs |
| 17 | [Reserved Instances](./17-reserved-instances/) | RI cost handling |

### Phase 5: Advanced Matching

| # | Scenario | Description |
|---|----------|-------------|
| 18 | [Multi-Cluster Shared Disk](./18-multi-cluster-shared-disk/) | EBS shared across clusters |
| 19 | [Non-CSI Storage](./19-non-csi-storage/) | Storage without CSI handles |
| 20 | [Cluster Alias Matching](./20-cluster-alias-matching/) | Match by cluster alias tag |
| 21 | [Volume Labels Matching](./21-volume-labels-matching/) | Match by OCP volume labels |
| 22 | [PV Name Suffix Matching](./22-pv-name-suffix-matching/) | PV name contains AWS volume ID |
| 23 | [Generic Pod Labels](./23-generic-pod-labels-matching/) | Custom tag key matching |

---

## Directory Structure

Each scenario directory contains:

```
XX-scenario-name/
├── README.md           # Scenario description, validation details, expected outcomes
├── manifest.yml        # Main test manifest (nise format)
├── variation.yml       # (Optional) Alternative test case
└── manifest_fixed.yml  # (Optional) Fixed version for known issues
```

---

## How Validation Aligns with Cost Management Core

### Core's Validation Approach

Cost Management Core uses a similar totals-based validation:

1. **Generate test data** using nise (same tool as POC)
2. **Run aggregation pipeline** (Trino SQL in Core, Python in POC)
3. **Query results** from PostgreSQL
4. **Compare totals** against expected values from manifest

### POC Validation Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Test Manifest  │────▶│  POC Aggregator │────▶│   PostgreSQL    │
│   (YAML file)   │     │   (Python)      │     │   (Results)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  PASS / FAIL    │◀────│   Validation    │◀────│  Query Results  │
│                 │     │    Script       │     │  SUM(cost)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Key Differences from Core

| Aspect | Core | POC |
|--------|------|-----|
| Aggregation Engine | Trino SQL | Python (pandas) |
| Data Source | S3 Parquet | MinIO Parquet |
| Validation Script | Core test suite | `validate_ocp_aws_totals.py` |
| Database | RDS PostgreSQL | Local PostgreSQL |
| Test Data | nise | nise (same) |

### Same Validation Queries

Both Core and POC use equivalent validation queries:

```sql
-- Total cost validation (Core and POC)
SELECT ROUND(SUM(unblended_cost)::numeric, 2) as total_cost
FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Namespace breakdown (Core and POC)
SELECT namespace, ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM {schema}.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY namespace;
```

---

## Running Validation Manually

### Step 1: Run Aggregation

```bash
python src/main.py \
  --ocp-provider-uuid $OCP_UUID \
  --aws-provider-uuid $AWS_UUID \
  --year 2025 --month 10
```

### Step 2: Validate Results

```bash
python scripts/validate_ocp_aws_totals.py \
  test-manifests/ocp-on-aws/01-resource-matching/manifest.yml
```

### Step 3: Manual Verification (Optional)

```bash
podman exec postgres-poc psql -U koku -d koku -c "
SELECT 
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces,
    COUNT(DISTINCT cluster_id) as clusters
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
"
```

---

## Creating New Scenarios

1. Create a new directory: `mkdir XX-new-scenario`
2. Copy a similar manifest as template
3. Add a README.md with:
   - Scenario description
   - What it tests
   - **Detailed validation criteria**
   - Expected outcomes
   - How to run
4. Update this main README with the new scenario

---

## Related Documentation

- [Benchmark Results](../../docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md)
- [Architecture Overview](../../docs/architecture/)
- [Main README](../../README.md)
- [Validation Script](../../scripts/validate_ocp_aws_totals.py)
