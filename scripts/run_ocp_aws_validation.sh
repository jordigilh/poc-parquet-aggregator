#!/bin/bash
#
# Core OCP-on-AWS Validation Script
# Tests the POC against all Core OCP-on-AWS scenarios
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
Core_PLUGIN="/Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin"
NISE_CMD="$Core_PLUGIN/iqe-venv/bin/nise"

# Configuration
TEST_OUTPUT_DIR="$POC_ROOT/test-results-ocp-aws"
TEMP_DATA_DIR="$POC_ROOT/temp-test-data"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="15432"
POSTGRES_USER="koku"
POSTGRES_PASS="koku123"
POSTGRES_DB="koku"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test scenarios from Core
declare -a OCP_SCENARIOS=(
    "ocp_for_aws_report_basic_template"
    "ocp_for_aws_report_basic_daily_template"
    "ocp_for_aws_report_user_projects_0"
    "ocp_for_aws_report_user_projects_1"
    "ocp_for_aws_report_user_projects_2"
    "ocp_for_aws_report_multi_0_alpha"
    "ocp_for_aws_report_multi_1_bravo"
    "ocp_for_aws_report_multi_2_charlie"
)

declare -a AWS_SCENARIOS=(
    "aws_report_basic_template"
    "aws_report_basic_daily_template"
    "aws_report_user_projects"
    "aws_report_user_projects"
    "aws_report_user_projects"
    "aws_report_multi_0_alpha_template"
    "aws_report_multi_1_bravo_template"
    "aws_report_multi_2_charlie_template"
)

echo -e "${BLUE}=============================================="
echo "=== Core OCP-on-AWS Validation Suite ==="
echo -e "==============================================${NC}"
echo ""
echo "Test Output: $TEST_OUTPUT_DIR"
echo "Total Scenarios: ${#OCP_SCENARIOS[@]}"
echo ""

# Cleanup previous results
rm -rf "$TEST_OUTPUT_DIR" "$TEMP_DATA_DIR"
mkdir -p "$TEST_OUTPUT_DIR"
mkdir -p "$TEMP_DATA_DIR"

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if [ ! -f "$NISE_CMD" ]; then
    echo -e "${RED}❌ nise not found at $NISE_CMD${NC}"
    exit 1
fi

if ! podman ps | grep -q postgres-poc; then
    echo -e "${RED}❌ postgres-poc container not running${NC}"
    exit 1
fi

if ! podman ps | grep -q minio; then
    echo -e "${RED}❌ minio container not running${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All prerequisites met${NC}"
echo ""

# Initialize results summary
SUMMARY_FILE="$TEST_OUTPUT_DIR/SUMMARY.md"
cat > "$SUMMARY_FILE" <<EOF
# Core OCP-on-AWS Validation Summary

**Date**: $(date)
**Total Scenarios**: ${#OCP_SCENARIOS[@]}

## Test Results

| # | Scenario | Status | Input Rows | Output Rows | Time | Details |
|---|----------|--------|------------|-------------|------|---------|
EOF

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Run each scenario
for i in "${!OCP_SCENARIOS[@]}"; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    OCP_SCENARIO="${OCP_SCENARIOS[$i]}"
    AWS_SCENARIO="${AWS_SCENARIOS[$i]}"

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Test $((i+1))/${#OCP_SCENARIOS[@]}: $OCP_SCENARIO${NC}"
    echo -e "${BLUE}========================================${NC}"

    SCENARIO_DIR="$TEMP_DATA_DIR/scenario_$((i+1))"
    mkdir -p "$SCENARIO_DIR"

    START_TIME=$(date +%s)
    STATUS="❌ FAILED"
    INPUT_ROWS=0
    OUTPUT_ROWS=0
    ERROR_MSG=""

    # Step 1: Check if YAML files exist
    OCP_YAML="$Core_PLUGIN/iqe_cost_management/data/aws/openshift/${OCP_SCENARIO}.yml"
    AWS_YAML="$Core_PLUGIN/iqe_cost_management/data/aws/${AWS_SCENARIO}.yml"

    if [ ! -f "$OCP_YAML" ]; then
        echo -e "${RED}❌ OCP YAML not found: $OCP_YAML${NC}"
        ERROR_MSG="OCP YAML file not found"
        echo "| $((i+1)) | $OCP_SCENARIO | ❌ FAILED | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    if [ ! -f "$AWS_YAML" ]; then
        echo -e "${RED}❌ AWS YAML not found: $AWS_YAML${NC}"
        ERROR_MSG="AWS YAML file not found"
        echo "| $((i+1)) | $OCP_SCENARIO | ❌ FAILED | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # Step 2: Generate OCP data with nise
    echo -e "${YELLOW}→ Generating OCP data...${NC}"
    OCP_OUTPUT="$SCENARIO_DIR/ocp"
    mkdir -p "$OCP_OUTPUT"

    if ! "$NISE_CMD" report ocp \
        --static-report-file "$OCP_YAML" \
        --ocp-cluster-id "iqe-test-cluster-$((i+1))" \
        --start-date "2025-10-01" \
        --end-date "2025-10-07" \
        --insights-upload "$OCP_OUTPUT" \
        > "$TEST_OUTPUT_DIR/scenario_$((i+1))_ocp_nise.log" 2>&1; then
        echo -e "${RED}❌ Failed to generate OCP data${NC}"
        ERROR_MSG="OCP data generation failed"
        cat "$TEST_OUTPUT_DIR/scenario_$((i+1))_ocp_nise.log" | tail -20
        echo "| $((i+1)) | $OCP_SCENARIO | ❌ FAILED | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    echo -e "${GREEN}✅ OCP data generated${NC}"

    # Step 3: Generate AWS data with nise
    echo -e "${YELLOW}→ Generating AWS data...${NC}"
    AWS_OUTPUT="$SCENARIO_DIR/aws"
    mkdir -p "$AWS_OUTPUT"

    if ! "$NISE_CMD" report aws \
        --static-report-file "$AWS_YAML" \
        --aws-s3-bucket-name cost-usage-bucket \
        --aws-s3-report-name cost-report \
        --start-date "2025-10-01" \
        --end-date "2025-10-07" \
        --insights-upload "$AWS_OUTPUT" \
        > "$TEST_OUTPUT_DIR/scenario_$((i+1))_aws_nise.log" 2>&1; then
        echo -e "${RED}❌ Failed to generate AWS data${NC}"
        ERROR_MSG="AWS data generation failed"
        cat "$TEST_OUTPUT_DIR/scenario_$((i+1))_aws_nise.log" | tail -20
        echo "| $((i+1)) | $OCP_SCENARIO | ❌ FAILED | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    echo -e "${GREEN}✅ AWS data generated${NC}"

    # Step 4: Convert to Parquet and upload to MinIO
    echo -e "${YELLOW}→ Converting to Parquet and uploading to MinIO...${NC}"
    cd "$POC_ROOT"
    source venv/bin/activate

    if ! python scripts/csv_to_parquet_minio.py "$SCENARIO_DIR" \
        > "$TEST_OUTPUT_DIR/scenario_$((i+1))_parquet.log" 2>&1; then
        echo -e "${RED}❌ Failed to convert to Parquet${NC}"
        ERROR_MSG="Parquet conversion failed"
        cat "$TEST_OUTPUT_DIR/scenario_$((i+1))_parquet.log" | tail -20
        echo "| $((i+1)) | $OCP_SCENARIO | ❌ FAILED | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    echo -e "${GREEN}✅ Parquet files uploaded${NC}"

    # Step 5: Clear PostgreSQL tables
    echo -e "${YELLOW}→ Clearing PostgreSQL tables...${NC}"
    podman exec postgres-poc psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
        TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;
        TRUNCATE TABLE org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
    " > /dev/null 2>&1 || true

    # Step 6: Run POC aggregation
    echo -e "${YELLOW}→ Running POC aggregation...${NC}"

    # Count input rows
    INPUT_ROWS=$(find "$SCENARIO_DIR" -name "*.csv" -type f -exec wc -l {} + | tail -1 | awk '{print $1}')

    export POSTGRES_HOST="$POSTGRES_HOST"
    export POSTGRES_PORT="$POSTGRES_PORT"
    export POSTGRES_USER="$POSTGRES_USER"
    export POSTGRES_PASSWORD="$POSTGRES_PASS"
    export POSTGRES_DB="$POSTGRES_DB"
    export ORG_ID="org1234567"
    export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
    export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"

    if python -m src.main \
        > "$TEST_OUTPUT_DIR/scenario_$((i+1))_poc.log" 2>&1; then
        echo -e "${GREEN}✅ POC aggregation complete${NC}"

        # Step 7: Validate results
        echo -e "${YELLOW}→ Validating results...${NC}"

        # Count output rows
        OUTPUT_ROWS=$(podman exec postgres-poc psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "
            SELECT COUNT(*) FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
        " 2>/dev/null | tr -d ' ' || echo "0")

        if [ "$OUTPUT_ROWS" -gt 0 ]; then
            STATUS="✅ PASSED"
            PASSED_TESTS=$((PASSED_TESTS + 1))
            echo -e "${GREEN}✅ Scenario passed: $OUTPUT_ROWS output rows${NC}"

            # Save detailed results
            podman exec postgres-poc psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
                SELECT
                    usage_start,
                    namespace,
                    resource_id_matched,
                    tag_matched,
                    COUNT(*) as row_count,
                    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost
                FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
                GROUP BY usage_start, namespace, resource_id_matched, tag_matched
                ORDER BY usage_start, namespace;
            " > "$TEST_OUTPUT_DIR/scenario_$((i+1))_results.txt" 2>&1 || true
        else
            STATUS="❌ FAILED"
            ERROR_MSG="No output rows generated"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo -e "${RED}❌ Scenario failed: No output rows${NC}"
        fi
    else
        echo -e "${RED}❌ POC aggregation failed${NC}"
        ERROR_MSG="POC execution failed"
        cat "$TEST_OUTPUT_DIR/scenario_$((i+1))_poc.log" | tail -30
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Write to summary
    echo "| $((i+1)) | $OCP_SCENARIO | $STATUS | $INPUT_ROWS | $OUTPUT_ROWS | ${DURATION}s | $ERROR_MSG |" >> "$SUMMARY_FILE"

    echo ""
done

# Generate final summary
cat >> "$SUMMARY_FILE" <<EOF

---

## Overall Results

- **Total Tests**: $TOTAL_TESTS
- **Passed**: $PASSED_TESTS ($(( PASSED_TESTS * 100 / TOTAL_TESTS ))%)
- **Failed**: $FAILED_TESTS ($(( FAILED_TESTS * 100 / TOTAL_TESTS ))%)

EOF

if [ $FAILED_TESTS -eq 0 ]; then
    cat >> "$SUMMARY_FILE" <<EOF
### ✅ **ALL TESTS PASSED!**

The POC successfully processed all Core OCP-on-AWS test scenarios.
EOF
    echo -e "${GREEN}"
    echo "=============================================="
    echo "✅ ALL $TOTAL_TESTS TESTS PASSED!"
    echo "=============================================="
    echo -e "${NC}"
else
    cat >> "$SUMMARY_FILE" <<EOF
### ⚠️ **SOME TESTS FAILED**

Please review the individual test logs for details.
EOF
    echo -e "${RED}"
    echo "=============================================="
    echo "❌ $FAILED_TESTS of $TOTAL_TESTS TESTS FAILED"
    echo "=============================================="
    echo -e "${NC}"
fi

echo ""
echo "Full results: $SUMMARY_FILE"
echo ""

# Display summary
cat "$SUMMARY_FILE"

exit $FAILED_TESTS

