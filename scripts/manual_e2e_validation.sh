#!/bin/bash
#
# Manual E2E Validation for OCP-on-AWS POC
# Purpose: Prove the POC works end-to-end without complex automation
#
# Prerequisites:
# - MinIO running (localhost:9000)
# - PostgreSQL running (localhost:15432)
# - Test data already uploaded to MinIO (from previous test runs)
#

set -e

POC_ROOT="/Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator"
cd "$POC_ROOT"

echo "========================================"
echo "Manual E2E Validation"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
export POC_YEAR="2025"
export POC_MONTH="10"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="15432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export MINIO_ENDPOINT="http://localhost:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"
export S3_BUCKET="test-bucket"
export ORG_ID="org1234567"
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"
export OCP_CLUSTER_ID="test-cluster-001"

echo "Step 1: Check prerequisites..."
echo "→ Checking MinIO..."
if ! curl -s http://localhost:9000/minio/health/live > /dev/null; then
    echo -e "${RED}❌ MinIO not running${NC}"
    exit 1
fi
echo -e "${GREEN}✅ MinIO running${NC}"

echo "→ Checking PostgreSQL..."
if ! podman exec postgres-poc psql -U koku -d koku -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${RED}❌ PostgreSQL not running${NC}"
    exit 1
fi
echo -e "${GREEN}✅ PostgreSQL running${NC}"

echo "→ Checking for test data in MinIO..."
source venv/bin/activate
python3 -c "
import boto3
import os

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('MINIO_ENDPOINT'),
    aws_access_key_id=os.getenv('MINIO_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('MINIO_SECRET_KEY')
)

bucket = os.getenv('S3_BUCKET')
prefix = f\"data/{os.getenv('ORG_ID')}/OCP/source={os.getenv('OCP_PROVIDER_UUID')}/year={os.getenv('POC_YEAR')}/month={os.getenv('POC_MONTH')}/\"

try:
    result = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    if 'Contents' in result:
        print('✅ OCP test data found in MinIO')
    else:
        print('❌ No OCP test data found in MinIO')
        print(f'   Searched: {bucket}/{prefix}')
        exit(1)
except Exception as e:
    print(f'❌ Error accessing MinIO: {e}')
    exit(1)
" || exit 1

echo ""
echo "Step 2: Clear database..."
podman exec postgres-poc psql -U koku -d koku -c "
  TRUNCATE TABLE ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;
" > /dev/null 2>&1
echo -e "${GREEN}✅ Database cleared${NC}"

echo ""
echo "Step 3: Run POC aggregation..."
echo "→ This may take 1-2 minutes..."

# Capture start time
START_TIME=$(date +%s)

# Run POC
if python3 -m src.main --truncate > /tmp/manual_e2e_poc.log 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo -e "${GREEN}✅ POC aggregation complete (${DURATION}s)${NC}"
else
    echo -e "${RED}❌ POC aggregation failed${NC}"
    echo "Last 50 lines of log:"
    tail -50 /tmp/manual_e2e_poc.log
    exit 1
fi

echo ""
echo "Step 4: Validate results..."

# Query results
RESULTS=$(podman exec postgres-poc psql -U koku -d koku -t -c "
  SELECT
    COUNT(*) as total_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT cluster_id) as clusters,
    COUNT(DISTINCT namespace) as namespaces,
    COUNT(CASE WHEN resource_id_matched = true THEN 1 END) as resource_matched,
    COUNT(CASE WHEN tag_matched = true THEN 1 END) as tag_matched
  FROM ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;
" | tr -d ' ' | tr '|' ',')

# Parse results
IFS=',' read -r TOTAL_ROWS TOTAL_COST CLUSTERS NAMESPACES RESOURCE_MATCHED TAG_MATCHED <<< "$RESULTS"

echo "========================================"
echo "VALIDATION RESULTS"
echo "========================================"
echo "Total rows:        $TOTAL_ROWS"
echo "Total cost:        \$$TOTAL_COST"
echo "Clusters:          $CLUSTERS"
echo "Namespaces:        $NAMESPACES"
echo "Resource matched:  $RESOURCE_MATCHED rows"
echo "Tag matched:       $TAG_MATCHED rows"
echo ""

# Validation checks
VALIDATION_PASSED=true

echo "Step 5: Validation checks..."

# Check 1: Reasonable row count (no Cartesian product)
echo -n "→ Row count reasonable (< 100K): "
if [ "$TOTAL_ROWS" -lt 100000 ]; then
    echo -e "${GREEN}✅ PASS ($TOTAL_ROWS rows)${NC}"
else
    echo -e "${RED}❌ FAIL ($TOTAL_ROWS rows - possible Cartesian product)${NC}"
    VALIDATION_PASSED=false
fi

# Check 2: Non-zero costs
echo -n "→ Costs attributed (> \$0): "
if [ "$TOTAL_COST" != "0.00" ] && [ "$TOTAL_COST" != ".00" ] && [ -n "$TOTAL_COST" ]; then
    echo -e "${GREEN}✅ PASS (\$$TOTAL_COST)${NC}"
else
    echo -e "${RED}❌ FAIL (\$$TOTAL_COST)${NC}"
    VALIDATION_PASSED=false
fi

# Check 3: At least one cluster
echo -n "→ Clusters found (> 0): "
if [ "$CLUSTERS" -gt 0 ]; then
    echo -e "${GREEN}✅ PASS ($CLUSTERS cluster(s))${NC}"
else
    echo -e "${RED}❌ FAIL ($CLUSTERS clusters)${NC}"
    VALIDATION_PASSED=false
fi

# Check 4: Namespaces found
echo -n "→ Namespaces found (> 0): "
if [ "$NAMESPACES" -gt 0 ]; then
    echo -e "${GREEN}✅ PASS ($NAMESPACES namespace(s))${NC}"
else
    echo -e "${RED}❌ FAIL ($NAMESPACES namespaces)${NC}"
    VALIDATION_PASSED=false
fi

# Check 5: Matching worked (at least one match)
echo -n "→ Matching worked (resource or tag): "
TOTAL_MATCHED=$((RESOURCE_MATCHED + TAG_MATCHED))
if [ "$TOTAL_MATCHED" -gt 0 ]; then
    echo -e "${GREEN}✅ PASS ($RESOURCE_MATCHED resource, $TAG_MATCHED tag)${NC}"
else
    echo -e "${RED}❌ FAIL (0 matches - check align_test_data.py)${NC}"
    VALIDATION_PASSED=false
fi

echo ""
echo "Step 6: Sample data check..."
echo "→ Top 5 rows by cost:"
podman exec postgres-poc psql -U koku -d koku -c "
  SELECT
    usage_start,
    cluster_id,
    namespace,
    node,
    resource_id_matched,
    tag_matched,
    ROUND(unblended_cost::numeric, 2) as cost,
    ROUND(pod_usage_cpu_core_hours::numeric, 2) as cpu_hours,
    ROUND(pod_usage_memory_gigabyte_hours::numeric, 2) as mem_gb_hours
  FROM ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p
  WHERE unblended_cost > 0
  ORDER BY unblended_cost DESC
  LIMIT 5;
" 2>/dev/null || echo "  (No data or query failed)"

echo ""
echo "========================================"
echo "FINAL RESULT"
echo "========================================"

if $VALIDATION_PASSED; then
    echo -e "${GREEN}✅ VALIDATION PASSED${NC}"
    echo ""
    echo "Summary:"
    echo "  • POC executed successfully"
    echo "  • $TOTAL_ROWS rows generated (reasonable)"
    echo "  • \$$TOTAL_COST attributed (non-zero)"
    echo "  • $TOTAL_MATCHED resources matched"
    echo "  • $NAMESPACES namespaces with costs"
    echo ""
    echo "✅ POC is working correctly!"
    echo "✅ Ready for deployment and Trino comparison"
    exit 0
else
    echo -e "${RED}❌ VALIDATION FAILED${NC}"
    echo ""
    echo "Issues found:"
    if [ "$TOTAL_ROWS" -ge 100000 ]; then
        echo "  • Cartesian product (too many rows)"
    fi
    if [ "$TOTAL_COST" == "0.00" ] || [ -z "$TOTAL_COST" ]; then
        echo "  • Zero costs (cost attribution broken)"
    fi
    if [ "$TOTAL_MATCHED" -eq 0 ]; then
        echo "  • Zero matches (matching logic broken)"
    fi
    echo ""
    echo "Check logs: /tmp/manual_e2e_poc.log"
    exit 1
fi

