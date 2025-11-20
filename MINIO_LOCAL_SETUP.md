# Local MinIO Setup for POC Validation

**Goal**: Run POC validation entirely locally without requiring a Kubernetes cluster.

**Components**:
- ✅ MinIO (local S3-compatible storage)
- ✅ PostgreSQL (Docker container)
- ✅ POC aggregator (Python venv)
- ✅ Nise (data generator)

---

## Architecture

```
┌─────────────┐
│    Nise     │ Generate CSV data
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  CSV Files  │ Local filesystem
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    MASU     │ Convert CSV → Parquet (optional: use existing code)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   MinIO     │ S3-compatible storage (localhost:9000)
│  (Docker)   │ Stores Parquet files
└──────┬──────┘
       │
       ▼
┌─────────────┐
│POC Aggregator│ Read Parquet, aggregate, write to PostgreSQL
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ PostgreSQL  │ Database (localhost:5432)
│  (Docker)   │ Stores summary tables
└─────────────┘
```

---

## Step 1: Start MinIO (Podman)

### Option A: Podman Run (Simple)
```bash
podman run -d \
  --name minio-poc \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  -v /tmp/minio-data:/data:Z \
  quay.io/minio/minio server /data --console-address ":9001"
```

### Option B: Podman Compose (Recommended)
**Note**: Podman supports docker-compose files via `podman-compose`

Install podman-compose if not already installed:
```bash
pip3 install --user podman-compose
# OR
brew install podman-compose
```

Create `docker-compose.yml` (works with podman-compose):
```yaml
version: '3.8'

services:
  minio:
    image: quay.io/minio/minio:latest
    container_name: minio-poc
    ports:
      - "9000:9000"  # S3 API
      - "9001:9001"  # Web Console
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - /tmp/minio-data:/data
    command: server /data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  postgres:
    image: postgres:15
    container_name: postgres-poc
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: koku
      POSTGRES_PASSWORD: koku123
      POSTGRES_DB: koku
    volumes:
      - /tmp/postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U koku"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Start services:
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator

# Using podman-compose
podman-compose up -d

# OR using podman directly (without compose)
podman pod create --name poc-pod -p 9000:9000 -p 9001:9001 -p 5432:5432

podman run -d \
  --pod poc-pod \
  --name minio-poc \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  -v minio-data:/data:Z \
  quay.io/minio/minio server /data --console-address ":9001"

podman run -d \
  --pod poc-pod \
  --name postgres-poc \
  -e POSTGRES_USER=koku \
  -e POSTGRES_PASSWORD=koku123 \
  -e POSTGRES_DB=koku \
  -v postgres-data:/var/lib/postgresql/data:Z \
  -v ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:Z \
  postgres:15

# Check status
podman ps
# OR
podman-compose ps

# View logs
podman logs -f minio-poc
podman logs -f postgres-poc
# OR
podman-compose logs -f
```

---

## Step 2: Configure MinIO

### Access MinIO Console
Open browser: http://localhost:9001
- Username: `minioadmin`
- Password: `minioadmin`

### Create Bucket (via Console)
1. Click "Buckets" → "Create Bucket"
2. Bucket Name: `cost-management`
3. Click "Create Bucket"

### Create Bucket (via CLI)
```bash
# Install MinIO client
brew install minio/stable/mc

# Configure alias
mc alias set local http://localhost:9000 minioadmin minioadmin

# Create bucket
mc mb local/cost-management

# Verify
mc ls local/
```

---

## Step 3: Initialize PostgreSQL Schema

### Connect to PostgreSQL
```bash
podman exec -it postgres-poc psql -U koku -d koku
```

### Create Schema and Table
```sql
-- Create schema for organization
CREATE SCHEMA IF NOT EXISTS org1234567;

-- Create summary table (simplified for POC)
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocpusagelineitem_daily_summary (
    uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_period_id INTEGER,
    cluster_id VARCHAR(50),
    cluster_alias VARCHAR(256),
    data_source VARCHAR(64),
    namespace VARCHAR(253),
    node VARCHAR(253),
    resource_id VARCHAR(253),
    usage_start DATE NOT NULL,
    usage_end DATE NOT NULL,
    pod_labels JSONB,
    pod_usage_cpu_core_hours NUMERIC(24,6),
    pod_request_cpu_core_hours NUMERIC(24,6),
    pod_effective_usage_cpu_core_hours NUMERIC(24,6),
    pod_limit_cpu_core_hours NUMERIC(24,6),
    pod_usage_memory_gigabyte_hours NUMERIC(24,6),
    pod_request_memory_gigabyte_hours NUMERIC(24,6),
    pod_effective_usage_memory_gigabyte_hours NUMERIC(24,6),
    pod_limit_memory_gigabyte_hours NUMERIC(24,6),
    node_capacity_cpu_cores NUMERIC(24,6),
    node_capacity_cpu_core_hours NUMERIC(24,6),
    node_capacity_memory_gigabytes NUMERIC(24,6),
    node_capacity_memory_gigabyte_hours NUMERIC(24,6),
    cluster_capacity_cpu_core_hours NUMERIC(24,6),
    cluster_capacity_memory_gigabyte_hours NUMERIC(24,6),
    persistentvolumeclaim VARCHAR(253),
    persistentvolume VARCHAR(253),
    storageclass VARCHAR(50),
    volume_labels JSONB,
    persistentvolumeclaim_capacity_gigabyte NUMERIC(24,6),
    persistentvolumeclaim_capacity_gigabyte_months NUMERIC(24,6),
    volume_request_storage_gigabyte_months NUMERIC(24,6),
    persistentvolumeclaim_usage_gigabyte_months NUMERIC(24,6),
    cost_category_id INTEGER,
    source_uuid UUID,
    year VARCHAR(4),
    month VARCHAR(2)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS summary_source_uuid_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (source_uuid);
CREATE INDEX IF NOT EXISTS summary_usage_start_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (usage_start);
CREATE INDEX IF NOT EXISTS summary_namespace_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (namespace);
CREATE INDEX IF NOT EXISTS summary_node_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (node);

-- Create mock enabled tag keys table
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocpenabledtagkeys (
    id SERIAL PRIMARY KEY,
    key VARCHAR(253) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE
);

-- Insert some test enabled tag keys
INSERT INTO org1234567.reporting_ocpenabledtagkeys (key) VALUES
    ('app'),
    ('environment'),
    ('tier'),
    ('component');

-- Create mock cost category table
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocp_cost_category (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    namespace_pattern VARCHAR(255) NOT NULL
);

-- Insert test cost categories
INSERT INTO org1234567.reporting_ocp_cost_category (id, name, namespace_pattern) VALUES
    (1, 'Production', 'prod-%'),
    (2, 'Development', 'dev-%'),
    (3, 'Testing', 'test-%');

-- Verify
\dt org1234567.*
```

Exit psql: `\q`

---

## Step 4: Configure POC Environment

### Create `.env` file
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
cp env.example .env
```

### Edit `.env` for local MinIO + PostgreSQL
```bash
# S3/MinIO Configuration
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=cost-management

# PostgreSQL Configuration
POSTGRES_HOST=localhost
POSTGRES_DB=koku
POSTGRES_USER=koku
POSTGRES_PASSWORD=koku123
POSTGRES_SCHEMA=org1234567

# OCP Provider Configuration
OCP_PROVIDER_UUID=00000000-0000-0000-0000-000000000001
OCP_CLUSTER_ID=poc-test-cluster
OCP_CLUSTER_ALIAS=POC Test Cluster
OCP_YEAR=2025
OCP_MONTH=11
OCP_START_DATE=2025-11-01
OCP_END_DATE=2025-11-03

# Logging
LOG_LEVEL=INFO
```

### Update `config/config.yaml` for local development
```yaml
s3:
  endpoint: ${S3_ENDPOINT}
  bucket: ${S3_BUCKET}
  access_key: ${S3_ACCESS_KEY}
  secret_key: ${S3_SECRET_KEY}
  use_ssl: false  # Important for local MinIO
  verify_ssl: false  # Important for local MinIO
  region: us-east-1
  parquet_path: data/${ORG_ID}/${PROVIDER_TYPE}/year=${YEAR}/month=${MONTH}

postgresql:
  host: ${POSTGRES_HOST}
  port: 5432
  database: ${POSTGRES_DB}
  user: ${POSTGRES_USER}
  password: ${POSTGRES_PASSWORD}
  schema: ${POSTGRES_SCHEMA}
```

---

## Step 5: Generate Test Data with Nise

### Activate venv
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
source venv/bin/activate
```

### Generate CSV data
```bash
nise report ocp \
    --static-report-file config/ocp_poc_minimal.yml \
    --ocp-cluster-id poc-test-cluster \
    --start-date 2025-11-01 \
    --end-date 2025-11-03 \
    --write-monthly \
    --insights-upload /tmp/nise-poc-output

# Verify generated files
ls -lh /tmp/nise-poc-output/
```

---

## Step 6: Convert CSV to Parquet and Upload to MinIO

### Option A: Use Python Script (Simplified)
Create `scripts/csv_to_parquet_minio.py`:
```python
#!/usr/bin/env python3
"""Convert nise CSV to Parquet and upload to MinIO."""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
from pathlib import Path
import os

# Configuration
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET = "cost-management"
ORG_ID = "1234567"
PROVIDER_UUID = "00000000-0000-0000-0000-000000000001"

# CSV input
CSV_DIR = Path("/tmp/nise-poc-output")

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

# Find CSV files
csv_files = list(CSV_DIR.glob("*.csv"))
print(f"Found {len(csv_files)} CSV files")

for csv_file in csv_files:
    print(f"\nProcessing: {csv_file.name}")

    # Read CSV
    df = pd.read_csv(csv_file)
    print(f"  Rows: {len(df)}")

    # Extract date from filename or data
    # Assuming filename format: cluster_id_YYYY-MM-DD.csv
    # Or read from 'interval_start' column
    if 'interval_start' in df.columns:
        df['interval_start'] = pd.to_datetime(df['interval_start'])
        year = df['interval_start'].dt.year.iloc[0]
        month = df['interval_start'].dt.month.iloc[0]
        day = df['interval_start'].dt.day.iloc[0]
    else:
        year, month, day = 2025, 11, 1

    # S3 path (matching expected structure)
    s3_path = f"{BUCKET}/data/{ORG_ID}/OCP/source={PROVIDER_UUID}/year={year}/month={month:02d}/day={day:02d}/openshift_pod_usage_line_items/{csv_file.stem}.parquet"

    # Convert to Parquet
    table = pa.Table.from_pandas(df)

    # Write to MinIO
    with fs.open(s3_path, 'wb') as f:
        pq.write_table(table, f)

    print(f"  ✓ Uploaded to: s3://{s3_path}")

print("\n✓ All files converted and uploaded")
```

Run:
```bash
python scripts/csv_to_parquet_minio.py
```

### Option B: Use MASU's Existing Code
```bash
# TODO: Integrate with MASU's parquet_report_processor
# This requires more setup but uses production code
```

---

## Step 7: Run POC Validation

### Load environment
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/koku/poc-parquet-aggregator
source venv/bin/activate
export $(cat .env | xargs)
```

### Test connectivity
```bash
# Test MinIO
python3 -c "
import s3fs
fs = s3fs.S3FileSystem(
    key='minioadmin',
    secret='minioadmin',
    client_kwargs={'endpoint_url': 'http://localhost:9000'},
    use_ssl=False
)
print('MinIO buckets:', fs.ls(''))
"

# Test PostgreSQL
psql -h localhost -U koku -d koku -c "SELECT version();"
```

### Run POC aggregator
```bash
python3 -m src.main \
    --provider-uuid 00000000-0000-0000-0000-000000000001 \
    --year 2025 \
    --month 11 \
    --truncate
```

### Verify results
```bash
psql -h localhost -U koku -d koku -c "
SELECT
    usage_start,
    namespace,
    node,
    ROUND(pod_request_cpu_core_hours::numeric, 2) as cpu_req,
    ROUND(pod_request_memory_gigabyte_hours::numeric, 2) as mem_req,
    ROUND(node_capacity_cpu_core_hours::numeric, 2) as node_cpu_cap
FROM org1234567.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '00000000-0000-0000-0000-000000000001'
ORDER BY usage_start, namespace, node;
"
```

---

## Step 8: Compare Results

### Generate expected results
```bash
python3 -m src.expected_results config/ocp_poc_minimal.yml --print --output expected_results.csv
```

### Query actual results
```bash
psql -h localhost -U koku -d koku -c "
COPY (
    SELECT
        usage_start,
        namespace,
        node,
        pod_request_cpu_core_hours,
        pod_request_memory_gigabyte_hours,
        node_capacity_cpu_core_hours,
        node_capacity_memory_gigabyte_hours
    FROM org1234567.reporting_ocpusagelineitem_daily_summary
    WHERE source_uuid::text = '00000000-0000-0000-0000-000000000001'
    ORDER BY usage_start, namespace, node
) TO STDOUT WITH CSV HEADER
" > actual_results.csv
```

### Compare
```bash
python3 -c "
import pandas as pd
expected = pd.read_csv('expected_results.csv')
actual = pd.read_csv('actual_results.csv')

print('Expected rows:', len(expected))
print('Actual rows:', len(actual))

# Compare metrics
for col in ['pod_request_cpu_core_hours', 'pod_request_memory_gigabyte_hours']:
    exp_sum = expected[col].sum()
    act_sum = actual[col].sum()
    diff_pct = abs(exp_sum - act_sum) / exp_sum * 100 if exp_sum > 0 else 0
    print(f'{col}:')
    print(f'  Expected: {exp_sum:.2f}')
    print(f'  Actual: {act_sum:.2f}')
    print(f'  Diff: {diff_pct:.4f}%')
"
```

---

## Cleanup

### Stop services
```bash
# Using podman-compose
podman-compose down

# OR using podman directly
podman stop minio-poc postgres-poc
podman rm minio-poc postgres-poc
podman pod rm poc-pod

# Remove volumes (optional)
podman volume rm minio-data postgres-data
rm -rf /tmp/nise-poc-output
```

---

## Troubleshooting

### MinIO connection refused
- Check Podman: `podman ps | grep minio`
- Check port: `lsof -i :9000`
- Try: `curl http://localhost:9000/minio/health/live`
- Check logs: `podman logs minio-poc`

### PostgreSQL connection refused
- Check Podman: `podman ps | grep postgres`
- Check port: `lsof -i :5432`
- Try: `pg_isready -h localhost -U koku`
- Check logs: `podman logs postgres-poc`

### S3 SSL errors
- Ensure `use_ssl: false` in config
- Ensure `verify_ssl: false` in config
- Check endpoint: `http://` not `https://`

### Parquet files not found
- Verify S3 path structure matches POC expectations
- Check MinIO console: http://localhost:9001
- List files: `mc ls local/cost-management --recursive`

---

## Summary

✅ **No Kubernetes cluster required**
✅ **All services run locally with Podman**
✅ **Rootless containers (more secure)**
✅ **Full E2E validation possible**
✅ **Easy to reset and re-test**

**Total setup time**: ~15 minutes
**Total validation time**: ~5 minutes

This approach allows complete POC validation without any cluster dependencies!

