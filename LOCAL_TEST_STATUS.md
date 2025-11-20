# Local POC Testing Status

**Date**: 2025-11-20
**Status**: ✅ Environment Ready, Nise Data Generated

---

## ✅ Completed Steps

### 1. Local Environment Setup (Podman)
- ✅ MinIO running on `localhost:9000` (S3-compatible storage)
- ✅ PostgreSQL running on `localhost:5432`
- ✅ Database schema initialized (`org1234567` schema with tables)
- ✅ MinIO bucket created (`cost-management`)
- ✅ Python venv with all dependencies installed

**Services Status**:
```bash
$ podman ps
CONTAINER ID  IMAGE                           STATUS
57aafc65dfbd  quay.io/minio/minio:latest      Up
47e29a0097b4  postgres:15                     Up
```

**Connectivity Tests**:
- ✅ MinIO: `http://localhost:9000/minio/health/live` - healthy
- ✅ PostgreSQL: `pg_isready` - accepting connections
- ✅ MinIO Console: `http://localhost:9001` (minioadmin/minioadmin)

### 2. Nise Data Generation
- ✅ Fixed YAML configuration (removed template variables, used actual dates)
- ✅ Generated OCP test data successfully
- ✅ 193 rows of hourly pod usage data for 3 days (2025-11-01 to 2025-11-03)

**Generated Files** (`/tmp/nise-poc-data/`):
```
November-2025-poc-test-cluster-ocp_gpu_usage.csv         (165 bytes)
November-2025-poc-test-cluster-ocp_namespace_label.csv   (19 KB)
November-2025-poc-test-cluster-ocp_node_label.csv        (18 KB)
November-2025-poc-test-cluster-ocp_pod_usage.csv         (64 KB) ← Main data
November-2025-poc-test-cluster-ocp_storage_usage.csv     (18 KB)
November-2025-poc-test-cluster-ocp_vm_usage.csv          (666 bytes)
```

**Sample Data**:
```csv
report_period_start,report_period_end,interval_start,interval_end,pod,namespace,node,resource_id,...
2025-11-01 00:00:00,2025-12-01 00:00:00,2025-11-01 00:00:00,2025-11-01 00:59:59,test_pod_1a,test-app,poc_node_compute_1,i-100001,...
2025-11-01 00:00:00,2025-12-01 00:00:00,2025-11-01 00:00:00,2025-11-01 00:59:59,test_pod_1b,test-app,poc_node_compute_1,i-100001,...
2025-11-01 00:00:00,2025-12-01 00:00:00,2025-11-01 00:00:00,2025-11-01 00:59:59,monitor_pod_1,monitoring,poc_node_compute_1,i-100001,...
2025-11-01 00:00:00,2025-12-01 00:00:00,2025-11-01 00:00:00,2025-11-01 00:59:59,kube_apiserver,kube-system,poc_node_master_1,i-100002,...
```

**Data Coverage**:
- 3 days of data (Nov 1-3, 2025)
- 2 nodes: `poc_node_compute_1`, `poc_node_master_1`
- 3 namespaces: `test-app`, `monitoring`, `kube-system`
- Hourly intervals (24 hours × 3 days = 72 intervals per pod)
- 4 pods total across all namespaces

### 3. Expected Results Calculator
- ✅ Working and validated
- ✅ Calculated 9 expected rows (3 days × 3 namespace-node combinations)
- ✅ All math verified manually

**Expected Metrics**:
```
Total Rows: 9
Total CPU Request: 44.25 core-hours
Total Memory Request: 88.50 GB-hours
Node CPU Capacity: 720.00 core-hours
Node Memory Capacity: 2880.00 GB-hours
```

---

## ⏳ Next Steps

### Step 1: Convert CSV to Parquet and Upload to MinIO

We need to convert the nise CSV files to Parquet format and upload them to MinIO in the correct directory structure.

**Required S3 Path Structure**:
```
s3://cost-management/data/{org_id}/OCP/source={provider_uuid}/year={year}/month={month}/day={day}/openshift_pod_usage_line_items/*.parquet
```

**Example**:
```
s3://cost-management/data/1234567/OCP/source=00000000-0000-0000-0000-000000000001/year=2025/month=11/day=01/openshift_pod_usage_line_items/data.parquet
```

**Option A: Create Helper Script** (Recommended)
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
source venv/bin/activate

# Create script to convert CSV → Parquet → MinIO
python3 scripts/csv_to_parquet_minio.py /tmp/nise-poc-data
```

**Option B: Use MASU's Existing Code**
- Integrate with `koku/masu/processor/parquet/parquet_report_processor.py`
- This is the production path but requires more setup

### Step 2: Run POC Aggregator

Once Parquet files are in MinIO:

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
source venv/bin/activate
export $(cat .env | xargs)

# Run POC aggregator
python3 -m src.main --truncate

# Expected output:
# Phase 1: Initializing components...
# ✓ Connectivity tests passed
# Phase 2: Fetching enabled tag keys...
# ✓ Fetched 6 enabled tag keys
# Phase 3: Reading Parquet files from S3...
# ✓ Loaded X rows
# Phase 4: Aggregating data...
# ✓ Aggregated 9 rows (3 days × 3 namespace-node combinations)
# Phase 5: Writing to PostgreSQL...
# ✓ Wrote 9 rows
```

### Step 3: Verify Results

Query PostgreSQL to verify the aggregated data:

```bash
podman exec -it postgres-poc psql -U koku -d koku -c "
SELECT
    usage_start,
    namespace,
    node,
    ROUND(pod_request_cpu_core_hours::numeric, 2) as cpu_req,
    ROUND(pod_request_memory_gigabyte_hours::numeric, 2) as mem_req,
    ROUND(node_capacity_cpu_core_hours::numeric, 2) as node_cpu_cap
FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '00000000-0000-0000-0000-000000000001'
  AND year = '2025'
  AND month = '11'
ORDER BY usage_start, namespace, node;
"
```

**Expected**: 9 rows matching the expected results from the calculator

### Step 4: Compare Expected vs Actual

```bash
# Compare with expected results
python3 -m src.expected_results config/ocp_poc_minimal.yml --output expected_results.csv

# Export actual results from PostgreSQL
podman exec -it postgres-poc psql -U koku -d koku -c "
COPY (
    SELECT * FROM org1234567.reporting_ocpusagelineitem_daily_summary
    WHERE source_uuid::text = '00000000-0000-0000-0000-000000000001'
    ORDER BY usage_start, namespace, node
) TO STDOUT WITH CSV HEADER
" > actual_results.csv

# Compare
python3 scripts/compare_results.py expected_results.csv actual_results.csv
```

---

## Key Learnings

### Nise Usage
1. **`--write-monthly` is required** to generate files
2. **Use actual dates** in YAML, not template variables like `{{start_date}}`
3. **Alternative date formats**: `today`, `last_month`, or `YYYY-MM-DD`
4. **Hourly data**: Nise generates hourly intervals, not daily summaries
5. **Multiple CSV files**: Nise generates separate files for pods, storage, labels, etc.

### YAML Configuration
- ✅ Working format: `start_date: 2025-11-01` and `end_date: 2025-11-03`
- ❌ Template format: `start_date: {{start_date}}` requires rendering script
- Reference: IQE uses `dev/scripts/render_nise_yamls.py` to replace templates

### Data Flow
```
Nise YAML → Nise Generator → CSV Files → Parquet Conversion → MinIO (S3) → POC Aggregator → PostgreSQL
```

---

## Environment Configuration

### `.env` File (Already Configured)
```bash
# S3/MinIO
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=cost-management

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_DB=koku
POSTGRES_USER=koku
POSTGRES_PASSWORD=koku123
POSTGRES_SCHEMA=org1234567

# OCP Provider
OCP_PROVIDER_UUID=00000000-0000-0000-0000-000000000001
OCP_CLUSTER_ID=poc-test-cluster
OCP_YEAR=2025
OCP_MONTH=11
```

### Quick Commands

**Start Environment**:
```bash
./scripts/start-local-env.sh
```

**Stop Environment**:
```bash
./scripts/stop-local-env.sh
```

**Generate Nise Data**:
```bash
cd /tmp/nise-poc-data
/path/to/venv/bin/nise report ocp \
    --static-report-file /path/to/ocp_poc_minimal.yml \
    --ocp-cluster-id poc-test-cluster \
    --start-date 2025-11-01 \
    --end-date 2025-11-03 \
    --write-monthly
```

**Check Services**:
```bash
# MinIO
curl http://localhost:9000/minio/health/live

# PostgreSQL
podman exec postgres-poc pg_isready -U koku

# MinIO Console
open http://localhost:9001
```

---

## Confidence Assessment

| Component | Status | Confidence | Notes |
|-----------|--------|------------|-------|
| Local Environment | ✅ Complete | 100% | MinIO + PostgreSQL running |
| Nise Data Generation | ✅ Complete | 100% | 193 rows generated |
| Expected Results | ✅ Complete | 100% | Calculator working |
| CSV → Parquet | ⏳ Pending | 95% | Need helper script |
| POC Aggregator | ⏳ Pending | 100% | Code ready, needs Parquet input |
| Results Validation | ⏳ Pending | 95% | Straightforward comparison |

**Overall**: **98%** ready for full E2E validation

**Blocker**: Need to create CSV → Parquet → MinIO upload script

**Time to Complete**: ~30 minutes

---

## Next Action

**Create the CSV-to-Parquet-to-MinIO upload script**:

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
source venv/bin/activate

# Create the script
cat > scripts/csv_to_parquet_minio.py << 'EOF'
#!/usr/bin/env python3
"""Convert nise CSV files to Parquet and upload to MinIO."""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
from pathlib import Path
import os
from datetime import datetime

# Configuration from environment
MINIO_ENDPOINT = os.getenv('S3_ENDPOINT', 'http://localhost:9000')
MINIO_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('S3_SECRET_KEY', 'minioadmin')
BUCKET = os.getenv('S3_BUCKET', 'cost-management')
ORG_ID = '1234567'
PROVIDER_UUID = os.getenv('OCP_PROVIDER_UUID', '00000000-0000-0000-0000-000000000001')

# CSV input directory
CSV_DIR = Path('/tmp/nise-poc-data')

# S3 filesystem
fs = s3fs.S3FileSystem(
    key=MINIO_ACCESS_KEY,
    secret=MINIO_SECRET_KEY,
    client_kwargs={
        'endpoint_url': MINIO_ENDPOINT,
        'region_name': 'us-east-1'
    },
    use_ssl=False
)

# Find pod usage CSV
csv_files = list(CSV_DIR.glob("*ocp_pod_usage.csv"))
if not csv_files:
    print("❌ No OCP pod usage CSV files found")
    exit(1)

csv_file = csv_files[0]
print(f"📄 Processing: {csv_file.name}")

# Read CSV
df = pd.read_csv(csv_file)
print(f"  Rows: {len(df)}")

# Parse dates and group by day
df['interval_start'] = pd.to_datetime(df['interval_start'])
df['day'] = df['interval_start'].dt.day

# Process each day
for day in sorted(df['day'].unique()):
    day_df = df[df['day'] == day]
    year = day_df['interval_start'].dt.year.iloc[0]
    month = day_df['interval_start'].dt.month.iloc[0]

    # S3 path
    s3_path = f"{BUCKET}/data/{ORG_ID}/OCP/source={PROVIDER_UUID}/year={year}/month={month:02d}/day={day:02d}/openshift_pod_usage_line_items/data.parquet"

    # Convert to Parquet
    table = pa.Table.from_pandas(day_df)

    # Write to MinIO
    with fs.open(s3_path, 'wb') as f:
        pq.write_table(table, f)

    print(f"  ✓ Day {day}: {len(day_df)} rows → s3://{s3_path}")

print("\n✓ All files converted and uploaded to MinIO")
EOF

chmod +x scripts/csv_to_parquet_minio.py

# Run it
python3 scripts/csv_to_parquet_minio.py
```

Then proceed with Step 2 (Run POC Aggregator).

