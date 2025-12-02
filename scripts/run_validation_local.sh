#!/bin/bash
#
# Core OCP-on-AWS Validation Script (Local Only - No Red Hat Intranet Required)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NISE_CMD="/Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin/iqe-venv/bin/nise"

# Configuration
TEST_OUTPUT_DIR="$POC_ROOT/validation-results"
WORK_DIR="/tmp/ocp-aws-validation"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="15432"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}=============================================="
echo "=== Core OCP-on-AWS Local Validation ==="
echo "=== (No Red Hat Intranet Required) ==="
echo -e "==============================================${NC}"
echo ""

# Cleanup
rm -rf "$TEST_OUTPUT_DIR" "$WORK_DIR"
mkdir -p "$TEST_OUTPUT_DIR" "$WORK_DIR"

echo -e "${BLUE}Test 1: Simple OCP + AWS Scenario${NC}"
echo "=========================================="

SCENARIO_DIR="$WORK_DIR/scenario1"
mkdir -p "$SCENARIO_DIR"

# Generate OCP data directly (no upload)
echo -e "${YELLOW}→ Generating OCP data...${NC}"
cd "$SCENARIO_DIR"

# Use nise without --insights-upload to generate local files only
"$NISE_CMD" report ocp \
  --ocp-cluster-id "test-cluster-001" \
  --start-date "2025-10-01" \
  --end-date "2025-10-03" \
  --static-report-data '{
    "generators": [
      {
        "OCPGenerator": {
          "start_date": "2025-10-01",
          "end_date": "2025-10-03",
          "nodes": [
            {
              "node": {
                "node_name": "ip-10-0-1-100.ec2.internal",
                "resource_id": "i-0abc123def456789a",
                "cpu_cores": 4,
                "memory_gig": 16,
                "namespaces": {
                  "backend": {
                    "pods": [
                      {
                        "pod": {
                          "pod_name": "api-server-1",
                          "cpu_request": 2,
                          "mem_request_gig": 4,
                          "cpu_limit": 4,
                          "mem_limit_gig": 8,
                          "pod_seconds": 86400,
                          "cpu_usage": {"full_period": 2},
                          "mem_usage_gig": {"full_period": 6}
                        }
                      }
                    ]
                  }
                }
              }
            }
          ]
        }
      }
    ]
  }' \
  2>&1 | tee "$TEST_OUTPUT_DIR/nise_ocp.log"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to generate OCP data${NC}"
    echo "Check log: $TEST_OUTPUT_DIR/nise_ocp.log"
    exit 1
fi

echo -e "${GREEN}✅ OCP data generated${NC}"

# Find generated OCP files
OCP_FILES=$(find . -name "*.csv" -type f | wc -l)
echo "Found $OCP_FILES OCP CSV files"

if [ "$OCP_FILES" -eq 0 ]; then
    echo -e "${RED}❌ No OCP CSV files generated${NC}"
    ls -la
    exit 1
fi

# Generate AWS data directly (no upload)
echo -e "${YELLOW}→ Generating AWS data...${NC}"

"$NISE_CMD" report aws \
  --aws-s3-bucket-name test-bucket \
  --aws-s3-report-name cost-report \
  --start-date "2025-10-01" \
  --end-date "2025-10-03" \
  --static-report-data '{
    "generators": [
      {
        "EC2Generator": {
          "start_date": "2025-10-01",
          "end_date": "2025-10-03",
          "resource_id": "i-0abc123def456789a",
          "amount": 72,
          "rate": 0.10,
          "tags": {
            "resourceTags/user:openshift_cluster": "test-cluster-001",
            "resourceTags/user:openshift_node": "ip-10-0-1-100.ec2.internal"
          }
        }
      }
    ]
  }' \
  2>&1 | tee "$TEST_OUTPUT_DIR/nise_aws.log"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to generate AWS data${NC}"
    echo "Check log: $TEST_OUTPUT_DIR/nise_aws.log"
    exit 1
fi

echo -e "${GREEN}✅ AWS data generated${NC}"

# Find all generated files
echo ""
echo "Generated files:"
find . -name "*.csv" -type f | head -20

AWS_FILES=$(find . -name "*aws*" -o -name "*cost*" | grep -v ".log" | wc -l)
echo "Found $AWS_FILES AWS-related files"

# Convert to Parquet
echo ""
echo -e "${YELLOW}→ Converting to Parquet and uploading to MinIO...${NC}"
cd "$POC_ROOT"
source venv/bin/activate

python scripts/csv_to_parquet_minio.py "$SCENARIO_DIR" \
  > "$TEST_OUTPUT_DIR/parquet_conversion.log" 2>&1

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Parquet conversion failed${NC}"
    tail -30 "$TEST_OUTPUT_DIR/parquet_conversion.log"
    exit 1
fi

echo -e "${GREEN}✅ Parquet files uploaded to MinIO${NC}"

# Clear database
echo -e "${YELLOW}→ Clearing PostgreSQL tables...${NC}"
podman exec postgres-poc psql -U koku -d koku -c "
    TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;
    TRUNCATE TABLE org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
" > /dev/null 2>&1 || true

# Run POC aggregation
echo -e "${YELLOW}→ Running POC aggregation...${NC}"

export POSTGRES_HOST="$POSTGRES_HOST"
export POSTGRES_PORT="$POSTGRES_PORT"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export POSTGRES_DB="koku"
export ORG_ID="org1234567"
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"

python -m src.main 2>&1 | tee "$TEST_OUTPUT_DIR/poc_run.log"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ POC aggregation failed${NC}"
    tail -50 "$TEST_OUTPUT_DIR/poc_run.log"
    exit 1
fi

echo -e "${GREEN}✅ POC aggregation complete${NC}"

# Validate results
echo ""
echo -e "${YELLOW}→ Validating results...${NC}"

RESULT_COUNT=$(podman exec postgres-poc psql -U koku -d koku -t -c "
    SELECT COUNT(*) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
" 2>/dev/null | tr -d ' ' || echo "0")

echo "Generated $RESULT_COUNT OCP-AWS summary rows"

if [ "$RESULT_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✅ Results validated!${NC}"

    # Show sample results
    echo ""
    echo "Sample results:"
    podman exec postgres-poc psql -U koku -d koku -c "
        SELECT
            usage_start,
            namespace,
            resource_id_matched,
            tag_matched,
            ROUND(unblended_cost::numeric, 4) as cost
        FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
        LIMIT 10;
    " 2>&1
else
    echo -e "${RED}❌ No results generated${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=============================================="
echo "✅ Core Validation Complete!"
echo "==============================================${NC}"
echo ""
echo "Results directory: $TEST_OUTPUT_DIR"
echo "OCP-AWS summary rows: $RESULT_COUNT"
echo ""

exit 0

