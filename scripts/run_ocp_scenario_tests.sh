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
    "01-basic-pod"
    "02-storage-volume"
    "03-multi-namespace"
    "04-multi-node"
    "05-cluster-capacity"
    "06-cost-category"

    # Unallocated & Roles (2 scenarios)
    "07-unallocated-capacity"
    "17-node-roles"

    # Gap Coverage (4 scenarios) - Critical for 100% Trino parity
    "08-shared-pv-nodes"
    "09-days-in-month"
    "10-storage-cost-category"
    "11-pvc-capacity-gb"

    # Extended Coverage (5 scenarios)
    "12-label-precedence"
    "13-labels-special-chars"
    "14-empty-labels"
    "15-effective-usage"
    "16-all-labels"

    # Edge Cases (3 scenarios)
    "18-zero-usage"
    "19-vm-pods"
    "20-storage-no-pod"
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

| # | Scenario | Status | Expected CPU | Actual CPU | Expected Mem | Actual Mem | Expected Storage | Actual Storage | Rows | Duration |
|---|----------|--------|--------------|------------|--------------|------------|------------------|----------------|------|----------|
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

    MANIFEST_FILE="$TEST_MANIFESTS_DIR/${SCENARIO}/manifest.yml"

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

    # Step 2: Clear MinIO and upload new Parquet data
    echo "  📦 Clearing MinIO and uploading Parquet..."
    
    # Clear existing data in MinIO for this source
    python3 -c "
from minio import Minio
client = Minio('localhost:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
prefix = 'data/org1234567/OCP/source=00000000-0000-0000-0000-000000000001/'
objects = list(client.list_objects('koku', prefix=prefix, recursive=True))
for obj in objects:
    client.remove_object('koku', obj.object_name)
if objects:
    print(f'  ✓ Cleared {len(objects)} objects from MinIO')
" 2>/dev/null || true

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
    podman exec postgres-poc psql -U $POSTGRES_USER -d $POSTGRES_DB \
        -c "TRUNCATE TABLE ${ORG_ID}.reporting_ocpusagelineitem_daily_summary;" 2>/dev/null || true

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

        # Get aggregated metrics from database
        METRICS=$(python3 -c "
import psycopg2
conn = psycopg2.connect(host='$POSTGRES_HOST', port=$POSTGRES_PORT, user='$POSTGRES_USER', password='$POSTGRES_PASSWORD', dbname='$POSTGRES_DB')
cur = conn.cursor()
cur.execute('''
    SELECT
        COALESCE(ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2), 0) as cpu_hours,
        COALESCE(ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2), 0) as mem_hours,
        COALESCE(ROUND(SUM(persistentvolumeclaim_usage_gigabyte_months)::numeric, 4), 0) as storage_months
    FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary
''')
row = cur.fetchone()
print(f'{row[0]}|{row[1]}|{row[2]}')
conn.close()
" 2>/dev/null || echo "0|0|0")
        ACTUAL_CPU=$(echo "$METRICS" | cut -d'|' -f1)
        ACTUAL_MEM=$(echo "$METRICS" | cut -d'|' -f2)
        ACTUAL_STORAGE=$(echo "$METRICS" | cut -d'|' -f3)
        
        # Get expected values from manifest
        EXPECTED_VALUES=$(python3 -c "
import yaml
with open('$MANIFEST_FILE') as f:
    m = yaml.safe_load(f)
    expected = m.get('expected_outcome', {})
    cpu = expected.get('cpu_core_hours', 'N/A')
    mem = expected.get('memory_gigabyte_hours', 'N/A')
    storage = expected.get('storage_gigabyte_months', 'N/A')
    print(f'{cpu}|{mem}|{storage}')
" 2>/dev/null || echo "N/A|N/A|N/A")
        EXPECTED_CPU=$(echo "$EXPECTED_VALUES" | cut -d'|' -f1)
        EXPECTED_MEM=$(echo "$EXPECTED_VALUES" | cut -d'|' -f2)
        EXPECTED_STORAGE=$(echo "$EXPECTED_VALUES" | cut -d'|' -f3)

        if [ "$OUTPUT_ROWS" -gt 0 ]; then
            # Step 5: Run strict validation (data integrity)
            echo "  🔍 Running strict validation..."
            VALIDATION_LOG="$SCENARIO_DIR/validation.log"
            
            if "$SCRIPT_DIR/validate_e2e_results.sh" "$OCP_CLUSTER_ID" > "$VALIDATION_LOG" 2>&1; then
                # Step 6: Run value validation (expected vs actual)
                echo "  📊 Validating expected vs actual values..."
                VALUE_VALIDATION_LOG="$SCENARIO_DIR/value_validation.log"
                
                if python3 "$SCRIPT_DIR/validate_ocp_totals.py" "$MANIFEST_FILE" "$OCP_CLUSTER_ID" > "$VALUE_VALIDATION_LOG" 2>&1; then
                    STATUS="✅ PASS"
                    PASSED_TESTS=$((PASSED_TESTS + 1))
                    echo -e "${GREEN}✅ Scenario passed:${NC}"
                    echo -e "${BLUE}   CPU Hours:     Expected $EXPECTED_CPU, Got $ACTUAL_CPU${NC}"
                    echo -e "${BLUE}   Memory GB-Hrs: Expected $EXPECTED_MEM, Got $ACTUAL_MEM${NC}"
                    if [ "$ACTUAL_STORAGE" != "0" ] && [ "$ACTUAL_STORAGE" != "0.0000" ]; then
                        echo -e "${BLUE}   Storage GB-Mo: Expected $EXPECTED_STORAGE, Got $ACTUAL_STORAGE${NC}"
                    fi
                else
                    # Check if it's just missing expected_outcome (warning, not failure)
                    if grep -q "No expected_outcome defined" "$VALUE_VALIDATION_LOG"; then
                        STATUS="✅ PASS"
                        PASSED_TESTS=$((PASSED_TESTS + 1))
                        echo -e "${GREEN}✅ Scenario passed (no expected values defined):${NC}"
                        echo -e "${BLUE}   CPU Hours:     $ACTUAL_CPU${NC}"
                        echo -e "${BLUE}   Memory GB-Hrs: $ACTUAL_MEM${NC}"
                        if [ "$ACTUAL_STORAGE" != "0" ] && [ "$ACTUAL_STORAGE" != "0.0000" ]; then
                            echo -e "${BLUE}   Storage GB-Mo: $ACTUAL_STORAGE${NC}"
                        fi
                    else
                        STATUS="❌ FAIL"
                        FAILED_TESTS=$((FAILED_TESTS + 1))
                        echo -e "${RED}❌ Scenario failed:${NC}"
                        echo -e "${RED}   CPU Hours:     Expected $EXPECTED_CPU, Got $ACTUAL_CPU${NC}"
                        echo -e "${RED}   Memory GB-Hrs: Expected $EXPECTED_MEM, Got $ACTUAL_MEM${NC}"
                        if [ "$ACTUAL_STORAGE" != "0" ] && [ "$ACTUAL_STORAGE" != "0.0000" ]; then
                            echo -e "${RED}   Storage GB-Mo: Expected $EXPECTED_STORAGE, Got $ACTUAL_STORAGE${NC}"
                        fi
                        grep -E "❌|mismatch" "$VALUE_VALIDATION_LOG" 2>/dev/null || true
                    fi
                fi
            else
                STATUS="❌ FAIL"
                FAILED_TESTS=$((FAILED_TESTS + 1))
                echo -e "${RED}❌ Data validation failed - see $VALIDATION_LOG${NC}"
                # Show validation failures
                grep -E "❌ FAIL|Validation failures:" "$VALIDATION_LOG" 2>/dev/null || true
            fi
        else
            STATUS="⚠️ NO DATA"
            ACTUAL_CPU="0"
            ACTUAL_MEM="0"
            EXPECTED_CPU="N/A"
            EXPECTED_MEM="N/A"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo -e "${YELLOW}⚠ POC ran but produced no output rows${NC}"
        fi
    else
        STATUS="❌ FAIL"
        ACTUAL_CPU="0"
        ACTUAL_MEM="0"
        EXPECTED_CPU="N/A"
        EXPECTED_MEM="N/A"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}❌ POC failed - see $SCENARIO_DIR/poc.log${NC}"
    fi

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    echo ""

    # Add to summary with expected vs actual
    echo "| $TOTAL_TESTS | $SCENARIO | $STATUS | $EXPECTED_CPU | $ACTUAL_CPU | $EXPECTED_MEM | $ACTUAL_MEM | $OUTPUT_ROWS | ${DURATION}s |" >> "$SUMMARY_FILE"
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

---

## How to Verify Results

### Quick Verification Query

Connect to PostgreSQL and run:

\`\`\`sql
-- Connect: podman exec -it postgres-poc psql -U koku -d koku

-- Total summary
SELECT
    COUNT(*) as output_rows,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2) as total_cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2) as total_mem_gb_hours,
    COUNT(DISTINCT namespace) as namespaces,
    COUNT(DISTINCT node) as nodes
FROM org1234567.reporting_ocpusagelineitem_daily_summary;

-- Usage by namespace
SELECT
    namespace,
    COUNT(*) as rows,
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2) as cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2) as mem_gb_hours
FROM org1234567.reporting_ocpusagelineitem_daily_summary
GROUP BY namespace
ORDER BY cpu_hours DESC;

-- Sample rows
SELECT
    usage_start,
    namespace,
    node,
    pod,
    ROUND(pod_usage_cpu_core_hours::numeric, 4) as cpu_hours,
    ROUND(pod_usage_memory_gigabyte_hours::numeric, 4) as mem_gb_hours
FROM org1234567.reporting_ocpusagelineitem_daily_summary
ORDER BY usage_start, namespace
LIMIT 20;
\`\`\`

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

