#!/bin/bash
# POC Validation Script - End-to-End Test with Nise Static Data
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"
KOKU_ROOT="$(dirname "$POC_DIR")"

# Configuration
MODE="${1:-minimal}"  # minimal or full
NISE_YAML=""
PROVIDER_UUID="poc-test-provider-$(date +%s)"
CLUSTER_ID="poc-test-cluster"
START_DATE="2025-11-01"
END_DATE="2025-11-03"

case "$MODE" in
    "minimal")
        NISE_YAML="$POC_DIR/config/ocp_poc_minimal.yml"
        echo -e "${BLUE}Running POC validation in MINIMAL mode${NC}"
        ;;
    "full")
        NISE_YAML="$KOKU_ROOT/dev/scripts/nise_ymls/ocp_on_aws/ocp_static_data.yml"
        echo -e "${BLUE}Running POC validation in FULL mode${NC}"
        ;;
    *)
        echo -e "${RED}ERROR: Invalid mode '$MODE'${NC}"
        echo "Usage: $0 [minimal|full]"
        exit 1
        ;;
esac

# Check if nise is installed
if ! command -v nise &> /dev/null; then
    echo -e "${RED}ERROR: nise is not installed${NC}"
    echo "Install with: pip install koku-nise"
    exit 1
fi

# Check if YAML file exists
if [ ! -f "$NISE_YAML" ]; then
    echo -e "${RED}ERROR: YAML file not found: $NISE_YAML${NC}"
    exit 1
fi

# Check environment variables
REQUIRED_VARS=("S3_ENDPOINT" "S3_ACCESS_KEY" "S3_SECRET_KEY" "POSTGRES_HOST" "POSTGRES_PASSWORD" "POSTGRES_SCHEMA")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}ERROR: Environment variable $var is not set${NC}"
        echo "Please source your .env file or set required variables"
        exit 1
    fi
done

echo "========================================================================"
echo "POC VALIDATION TEST - Nise Static Data"
echo "========================================================================"
echo "Mode:          $MODE"
echo "YAML:          $NISE_YAML"
echo "Provider UUID: $PROVIDER_UUID"
echo "Cluster ID:    $CLUSTER_ID"
echo "Date Range:    $START_DATE to $END_DATE"
echo "========================================================================"
echo ""

# ============================================================================
# Step 1: Calculate expected results from YAML
# ============================================================================
echo -e "${BLUE}Step 1: Calculating expected results from YAML...${NC}"
python -m poc-parquet-aggregator.src.expected_results \
    "$NISE_YAML" \
    --print \
    --output "$POC_DIR/expected_results.csv"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Expected results calculated${NC}"
else
    echo -e "${RED}✗ Failed to calculate expected results${NC}"
    exit 1
fi

echo ""

# ============================================================================
# Step 2: Generate test data with nise
# ============================================================================
echo -e "${BLUE}Step 2: Generating test data with nise...${NC}"

# Create temporary directory for nise output
NISE_OUTPUT_DIR=$(mktemp -d)
echo "Output directory: $NISE_OUTPUT_DIR"

# Generate OCP data
nise report ocp \
    --static-report-file "$NISE_YAML" \
    --ocp-cluster-id "$CLUSTER_ID" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    --write-monthly \
    --insights-upload "$NISE_OUTPUT_DIR"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test data generated${NC}"
else
    echo -e "${RED}✗ Failed to generate test data${NC}"
    exit 1
fi

# List generated files
echo "Generated files:"
find "$NISE_OUTPUT_DIR" -type f -name "*.csv" | head -5

echo ""

# ============================================================================
# Step 3: Upload Parquet files to S3
# ============================================================================
echo -e "${BLUE}Step 3: Converting CSV to Parquet and uploading to S3...${NC}"

# For the POC, we assume the nise output has already been processed to Parquet
# In production, this would be done by MASU's CSV-to-Parquet conversion
# For now, we'll use MASU's existing conversion logic

echo -e "${YELLOW}NOTE: In production, MASU converts CSV to Parquet automatically${NC}"
echo -e "${YELLOW}For POC, ensure Parquet files exist in S3 for provider: $PROVIDER_UUID${NC}"

# TODO: Add actual CSV-to-Parquet conversion and S3 upload
# This would require calling MASU's parquet_report_processor

echo ""

# ============================================================================
# Step 4: Run POC aggregator
# ============================================================================
echo -e "${BLUE}Step 4: Running POC aggregator...${NC}"

# Set environment variables for POC
export OCP_PROVIDER_UUID="$PROVIDER_UUID"
export OCP_CLUSTER_ID="$CLUSTER_ID"
export OCP_YEAR="2025"
export OCP_MONTH="11"
export OCP_START_DATE="$START_DATE"
export OCP_END_DATE="$END_DATE"

# Run POC with validation
cd "$POC_DIR"
python -m src.main \
    --truncate \
    --validate-expected "$NISE_YAML"

POC_EXIT_CODE=$?

if [ $POC_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ POC aggregator completed successfully${NC}"
else
    echo -e "${RED}✗ POC aggregator failed${NC}"
    exit 1
fi

echo ""

# ============================================================================
# Step 5: Query PostgreSQL for verification
# ============================================================================
echo -e "${BLUE}Step 5: Querying PostgreSQL for verification...${NC}"

psql -h "$POSTGRES_HOST" -U "${POSTGRES_USER:-koku}" -d "${POSTGRES_DB:-koku}" -c "
SELECT 
    usage_start,
    namespace,
    node,
    ROUND(pod_request_cpu_core_hours::numeric, 2) as cpu_req,
    ROUND(pod_request_memory_gigabyte_hours::numeric, 2) as mem_req,
    ROUND(node_capacity_cpu_core_hours::numeric, 2) as node_cpu_cap,
    ROUND(node_capacity_memory_gigabyte_hours::numeric, 2) as node_mem_cap
FROM $POSTGRES_SCHEMA.reporting_ocpusagelineitem_daily_summary
WHERE source_uuid::text = '$PROVIDER_UUID'
  AND year = '2025'
  AND month = '11'
ORDER BY usage_start, namespace, node;
"

echo ""

# ============================================================================
# Summary
# ============================================================================
echo "========================================================================"
echo -e "${GREEN}POC VALIDATION TEST COMPLETED SUCCESSFULLY${NC}"
echo "========================================================================"
echo "Results:"
echo "  - Expected results CSV: $POC_DIR/expected_results.csv"
echo "  - Nise output directory: $NISE_OUTPUT_DIR"
echo "  - Provider UUID: $PROVIDER_UUID"
echo ""
echo "Next steps:"
echo "  1. Review validation results above"
echo "  2. Check expected vs actual comparison"
echo "  3. If all tests pass, proceed to full validation mode"
echo "  4. Run: $0 full"
echo "========================================================================"

# Cleanup
echo ""
read -p "Delete nise output directory? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$NISE_OUTPUT_DIR"
    echo "Cleaned up nise output"
fi

