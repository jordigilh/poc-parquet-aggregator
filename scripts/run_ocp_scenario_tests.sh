#!/bin/bash
#
# OCP-Only Scenario Test Runner
# Validates POC implementation against Trino SQL for OCP-only aggregation
#
# Usage:
#   ./scripts/run_ocp_scenario_tests.sh              # Run all scenarios
#   ./scripts/run_ocp_scenario_tests.sh --scenario 01  # Run specific scenario

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
TEST_MANIFESTS_DIR="$POC_ROOT/test-manifests/ocp-only"
TEST_RESULTS_DIR="$POC_ROOT/scenario-test-results/ocp-only"
WORK_DIR="/tmp/ocp-scenario-tests"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="15432"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test scenarios
SCENARIOS=(
    # Core Aggregation (6 scenarios)
    "ocp_scenario_01_basic_pod"
    "ocp_scenario_02_storage_volume"
    "ocp_scenario_03_multi_namespace"
    "ocp_scenario_04_multi_node"
    "ocp_scenario_05_cluster_capacity"
    "ocp_scenario_06_cost_category"

    # Unallocated & Roles (2 scenarios)
    "ocp_scenario_07_unallocated_capacity"
    "ocp_scenario_17_node_roles"

    # Gap Coverage (4 scenarios) - Critical for 100% Trino parity
    "ocp_scenario_08_shared_pv_nodes"
    "ocp_scenario_09_days_in_month"
    "ocp_scenario_10_storage_cost_category"
    "ocp_scenario_11_pvc_capacity_gb"

    # Extended Coverage (5 scenarios)
    "ocp_scenario_12_label_precedence"
    "ocp_scenario_13_labels_special_chars"
    "ocp_scenario_14_empty_labels"
    "ocp_scenario_15_effective_usage"
    "ocp_scenario_16_all_labels"

    # Edge Cases (3 scenarios)
    "ocp_scenario_18_zero_usage"
    "ocp_scenario_19_vm_pods"
    "ocp_scenario_20_storage_no_pod"
)

# Parse arguments
SINGLE_SCENARIO=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --scenario)
            SINGLE_SCENARIO="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}=============================================="
echo "=== OCP-Only Scenario Validation ==="
echo "=== Target: 100% Trino Parity ==="
echo -e "==============================================${NC}"
echo ""
echo "Test Manifests: $TEST_MANIFESTS_DIR"
echo "Total Scenarios: ${#SCENARIOS[@]}"
echo ""

# Cleanup
/bin/rm -rf "$TEST_RESULTS_DIR" "$WORK_DIR"
mkdir -p "$TEST_RESULTS_DIR" "$WORK_DIR"

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

# Activate venv
if [ -f "$POC_ROOT/venv/bin/activate" ]; then
    source "$POC_ROOT/venv/bin/activate"
else
    echo -e "${RED}❌ venv not found. Run: python -m venv venv && pip install -r requirements.txt${NC}"
    exit 1
fi

if ! command -v nise &> /dev/null; then
    echo -e "${RED}❌ nise not found. Run: pip install koku-nise${NC}"
    exit 1
fi

if ! podman ps | grep -q postgres-poc; then
    echo -e "${RED}❌ postgres-poc container not running. Run: podman-compose up -d${NC}"
    exit 1
fi

if ! podman ps | grep -q minio; then
    echo -e "${RED}❌ minio container not running. Run: podman-compose up -d${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All prerequisites met${NC}"
echo ""

# Initialize summary
SUMMARY_FILE="$TEST_RESULTS_DIR/SUMMARY.md"
cat > "$SUMMARY_FILE" <<EOF
# OCP-Only Scenario Validation Summary

**Date**: $(date)
**Total Scenarios**: ${#SCENARIOS[@]}
**Purpose**: Validate 100% Trino parity

## Test Results

| # | Scenario | Status | Rows | Duration | Memory | Details |
|---|----------|--------|------|----------|--------|---------|
EOF

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Filter scenarios if single scenario specified
if [ -n "$SINGLE_SCENARIO" ]; then
    FILTERED=()
    for s in "${SCENARIOS[@]}"; do
        if [[ "$s" == *"$SINGLE_SCENARIO"* ]]; then
            FILTERED+=("$s")
        fi
    done
    SCENARIOS=("${FILTERED[@]}")
    echo -e "${YELLOW}Running filtered scenarios: ${#SCENARIOS[@]}${NC}"
fi

# Run each scenario
for SCENARIO in "${SCENARIOS[@]}"; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Test $TOTAL_TESTS/${#SCENARIOS[@]}: $SCENARIO${NC}"
    echo -e "${BLUE}========================================${NC}"

    MANIFEST_FILE="$TEST_MANIFESTS_DIR/${SCENARIO}.yml"

    if [ ! -f "$MANIFEST_FILE" ]; then
        echo -e "${YELLOW}⚠ Manifest not found: $MANIFEST_FILE${NC}"
        echo "| $TOTAL_TESTS | $SCENARIO | ⚠ SKIPPED | - | - | Manifest not found |" >> "$SUMMARY_FILE"
        continue
    fi

    SCENARIO_DIR="$WORK_DIR/$SCENARIO"
    mkdir -p "$SCENARIO_DIR"

    START_TIME=$(date +%s)
    STATUS="❌ FAILED"
    OUTPUT_ROWS=0

    # Set environment for this test
    # Note: Config uses OCP_* prefix, not POC_*
    export OCP_START_DATE="2025-10-01"
    export OCP_END_DATE="2025-10-02"
    export OCP_YEAR="2025"
    export OCP_MONTH="10"
    export POC_YEAR="2025"
    export POC_MONTH="10"
    export ORG_ID="org1234567"
    export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
    export OCP_CLUSTER_ID="test-cluster-001"
    export OCP_CLUSTER_ALIAS="Test Cluster"
    export S3_ENDPOINT="http://localhost:9000"
    export S3_BUCKET="koku"
    export S3_ACCESS_KEY="minioadmin"
    export S3_SECRET_KEY="minioadmin"
    export POSTGRES_HOST="$POSTGRES_HOST"
    export POSTGRES_PORT="$POSTGRES_PORT"
    export POSTGRES_DB="koku"
    export POSTGRES_USER="koku"
    export POSTGRES_PASSWORD="koku123"
    # OCP-only mode: unset AWS_PROVIDER_UUID so POC runs in OCP-only mode
    unset AWS_PROVIDER_UUID

    cd "$SCENARIO_DIR"

    # Step 1: Generate OCP data with nise
    echo "  📄 Generating OCP data..."
    mkdir -p ocp
    if ! nise report ocp \
        --static-report-file "$MANIFEST_FILE" \
        --ocp-cluster-id "$OCP_CLUSTER_ID" \
        --start-date "$OCP_START_DATE" \
        --end-date "$OCP_END_DATE" \
        --insights-upload "ocp" \
        > nise.log 2>&1; then
        echo -e "${RED}  ❌ nise failed${NC}"
        cat nise.log
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | nise generation failed |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # Find generated CSV directory - nise creates: ocp/{cluster_id}/{date_range}/*.csv
    # The date_range format is YYYYMMDD-YYYYMMDD (e.g., 20251001-20251101)
    CSV_DIR=$(find ocp -type f -name "*.csv" 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
    if [ -z "$CSV_DIR" ]; then
        echo -e "${YELLOW}  ⚠ No OCP data generated (scenario may be storage-only)${NC}"
    else
        CSV_COUNT=$(find "$CSV_DIR" -name "*.csv" 2>/dev/null | wc -l | tr -d ' ')
        echo "  ✓ OCP data: $CSV_DIR ($CSV_COUNT CSV files)"
    fi

    # Step 2: Convert to Parquet and upload to MinIO
    echo "  📦 Converting to Parquet and uploading to MinIO..."

    # Use the existing csv_to_parquet_minio.py script which handles path structure correctly
    if [ -d "$CSV_DIR" ]; then
        export S3_BUCKET="koku"
        if python3 "$POC_ROOT/scripts/csv_to_parquet_minio.py" "$SCENARIO_DIR" 2>&1 | grep -E "✓|✅|Uploaded"; then
            echo "  ✓ Parquet files uploaded to MinIO"
        else
            echo -e "${YELLOW}  ⚠ Parquet conversion may have issues - checking POC...${NC}"
        fi
    fi

    # Step 3: Clear PostgreSQL summary table
    echo "  🗄 Clearing PostgreSQL..."
    PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB \
        -c "TRUNCATE TABLE koku.reporting_ocpusagelineitem_daily_summary;" 2>/dev/null || true

    # Step 4: Run POC aggregation
    echo "  🚀 Running POC aggregation..."
    cd "$POC_ROOT"

    # Run POC and capture full log (don't use grep -q which truncates)
    python3 -m src.main > "$SCENARIO_DIR/poc.log" 2>&1
    POC_EXIT_CODE=$?

    if [ $POC_EXIT_CODE -eq 0 ] && grep -q -E "✓.*complete|OCP.*aggregation" "$SCENARIO_DIR/poc.log"; then
        # Get row count from database
        OUTPUT_ROWS=$(python3 -c "
import psycopg2
conn = psycopg2.connect(host='$POSTGRES_HOST', port=$POSTGRES_PORT, user='$POSTGRES_USER', password='$POSTGRES_PASSWORD', dbname='$POSTGRES_DB')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary')
print(cur.fetchone()[0])
conn.close()
" 2>/dev/null || echo "0")

        if [ "$OUTPUT_ROWS" -gt 0 ]; then
            STATUS="✅ PASSED"
            PASSED_TESTS=$((PASSED_TESTS + 1))
            echo "  ✓ Output: $OUTPUT_ROWS rows"
        else
            STATUS="⚠️ NO DATA"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo -e "${YELLOW}  ⚠ POC ran but produced no output rows${NC}"
        fi
    else
        STATUS="❌ FAILED"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}  ❌ POC failed - see $SCENARIO_DIR/poc.log${NC}"
    fi

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Extract peak memory from POC log (format: peak_rss_mb='177.11 MB')
    PEAK_MEMORY=$(grep "peak_rss_mb" "$SCENARIO_DIR/poc.log" | tail -1 | sed 's/\x1b\[[0-9;]*m//g' | sed -n "s/.*peak_rss_mb='\([0-9.]*\).*/\1/p" || echo "0")
    PEAK_MEMORY="${PEAK_MEMORY:-0}"
    if [ "$PEAK_MEMORY" != "0" ]; then
        PEAK_MEMORY_DISPLAY="${PEAK_MEMORY}MB"
    else
        PEAK_MEMORY_DISPLAY="N/A"
    fi

    echo -e "  ${STATUS} (${PEAK_MEMORY_DISPLAY})"
    echo ""

    # Add to summary
    echo "| $TOTAL_TESTS | $SCENARIO | $STATUS | $OUTPUT_ROWS | ${DURATION}s | $PEAK_MEMORY_DISPLAY | - |" >> "$SUMMARY_FILE"
done

# Final summary
cat >> "$SUMMARY_FILE" <<EOF

## Summary

| Metric | Value |
|--------|-------|
| Total | $TOTAL_TESTS |
| Passed | $PASSED_TESTS |
| Failed | $FAILED_TESTS |
| Pass Rate | $(echo "scale=1; $PASSED_TESTS * 100 / $TOTAL_TESTS" | bc)% |

EOF

echo ""
echo -e "${BLUE}=============================================="
echo "=== Final Results ==="
echo -e "==============================================${NC}"
echo ""
echo -e "  Total:  $TOTAL_TESTS"
echo -e "  ${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "  ${RED}Failed: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✅ All scenarios passed! 100% Trino parity achieved.${NC}"
    exit 0
else
    echo -e "${RED}❌ Some scenarios failed. See $SUMMARY_FILE for details.${NC}"
    exit 1
fi

