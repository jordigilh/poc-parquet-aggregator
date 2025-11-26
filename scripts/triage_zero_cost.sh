#!/bin/bash
# Quick triage script to understand why costs are $0.00

set -e

echo "============================================================"
echo "Triaging $0.00 Cost Issue"
echo "============================================================"

cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator

# Setup environment
source venv/bin/activate
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="15432"
export POSTGRES_DB="cost_management"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export ORG_ID="1234567"

echo ""
echo "1. Checking AWS data in MinIO..."
echo "=================================================="
python3 -c "
import pyarrow.parquet as pq
import pyarrow.fs as fs
import os

s3_fs = fs.S3FileSystem(
    endpoint_override='localhost:9000',
    access_key='minioadmin',
    secret_key='minioadmin',
    scheme='http'
)

# Check for AWS data
try:
    aws_path = 'test-bucket/data/org1234567/AWS/source=00000000-0000-0000-0000-000000000002/year=2025/month=10'
    files = [f for f in s3_fs.get_file_info(fs.FileSelector(aws_path, recursive=True)) if f.path.endswith('.parquet')]
    print(f'✓ Found {len(files)} AWS Parquet files')
    
    if files:
        # Read first file to check columns
        table = pq.read_table(files[0].path, filesystem=s3_fs)
        print(f'✓ Columns: {len(table.column_names)}')
        
        # Check for cost columns
        cost_cols = [c for c in table.column_names if 'cost' in c.lower() or 'price' in c.lower()]
        print(f'✓ Cost columns found: {cost_cols[:5]}...')
        
        # Sample first row
        df = table.to_pandas()
        if 'lineitem_unblendedcost' in df.columns:
            print(f'✓ Sample unblended costs: {df[\"lineitem_unblendedcost\"].head(3).tolist()}')
        else:
            print(f'⚠️  lineitem_unblendedcost not found!')
            print(f'   Available cost columns: {cost_cols}')
except Exception as e:
    print(f'❌ Error reading AWS data: {e}')
"

echo ""
echo "2. Checking OCP data in MinIO..."
echo "=================================================="
python3 -c "
import pyarrow.parquet as pq
import pyarrow.fs as fs

s3_fs = fs.S3FileSystem(
    endpoint_override='localhost:9000',
    access_key='minioadmin',
    secret_key='minioadmin',
    scheme='http'
)

# Check for OCP data
try:
    ocp_path = 'test-bucket/data/org1234567/OCP/source=00000000-0000-0000-0000-000000000001/year=2025/month=10'
    files = [f for f in s3_fs.get_file_info(fs.FileSelector(ocp_path, recursive=True)) if f.path.endswith('.parquet')]
    print(f'✓ Found {len(files)} OCP Parquet files')
    
    # Check for resource_id in pod usage
    pod_files = [f for f in files if 'pod_usage' in f.path]
    if pod_files:
        table = pq.read_table(pod_files[0].path, filesystem=s3_fs)
        df = table.to_pandas()
        if 'resource_id' in df.columns:
            print(f'✓ Sample OCP resource_ids: {df[\"resource_id\"].head(3).tolist()}')
        else:
            print(f'⚠️  resource_id not found in OCP data!')
except Exception as e:
    print(f'❌ Error reading OCP data: {e}')
"

echo ""
echo "3. Checking POC database results..."
echo "=================================================="
psql "postgresql://koku:koku123@localhost:15432/cost_management" -c "
SELECT 
    COUNT(*) as total_rows,
    SUM(unblended_cost) as total_cost,
    SUM(CASE WHEN resource_id_matched THEN 1 ELSE 0 END) as resource_matched_rows,
    SUM(CASE WHEN tag_matched THEN 1 ELSE 0 END) as tag_matched_rows,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
" 2>/dev/null || echo "❌ Could not query database"

echo ""
echo "4. Checking for matching issues..."
echo "=================================================="
psql "postgresql://koku:koku123@localhost:15432/cost_management" -c "
SELECT 
    resource_id_matched,
    tag_matched,
    COUNT(*) as row_count,
    SUM(unblended_cost) as total_cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY resource_id_matched, tag_matched
ORDER BY row_count DESC;
" 2>/dev/null || echo "❌ Could not query database"

echo ""
echo "============================================================"
echo "Triage Complete"
echo "============================================================"

