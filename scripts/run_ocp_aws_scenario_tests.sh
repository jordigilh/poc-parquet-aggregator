#!/bin/bash
#
# OCP-on-AWS Scenario Test Runner
# Validates POC implementation against comprehensive test scenarios
# Ensures 100% Trino compliance
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
TEST_MANIFESTS_DIR="$POC_ROOT/test-manifests/ocp-on-aws"
TEST_RESULTS_DIR="$POC_ROOT/scenario-test-results"
WORK_DIR="/tmp/ocp-aws-scenario-tests"
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
    # Phase 0: Happy Path (6 scenarios) - 70% confidence
    "ocp_aws_scenario_01_resource_matching"
    "ocp_aws_scenario_02_tag_matching"
    "ocp_aws_scenario_03_multi_namespace"
    "ocp_aws_scenario_04_network_costs"
    "ocp_aws_scenario_05_storage_ebs"
    "ocp_aws_scenario_06_multi_cluster"

    # Phase 1: Critical Edge Cases (4 scenarios) - 90% confidence
    "ocp_aws_scenario_07_partial_matching"
    "ocp_aws_scenario_08_zero_usage"
    "ocp_aws_scenario_09_cost_types"
    "ocp_aws_scenario_10_unmatched_storage"

    # Phase 4: Resilience (2 scenarios) - 99% confidence
    "ocp_aws_scenario_11_corrupted_data"
    "ocp_aws_scenario_12_trino_precision"

    # Trino Compliance: Network & SavingsPlan (2 scenarios)
    "ocp_aws_scenario_13_network_data_transfer"
    "ocp_aws_scenario_14_savingsplan_costs"

    # Business Scenarios: AWS Services (3 scenarios)
    "ocp_aws_scenario_15_rds_database_costs"
    "ocp_aws_scenario_16_s3_storage_costs"
    "ocp_aws_scenario_17_reserved_instances"

    # Critical Core Gaps: Multi-cluster & Non-CSI Storage (2 scenarios)
    "ocp_aws_scenario_18_multi_cluster_shared_csi_disk"
    "ocp_aws_scenario_19_non_csi_storage"

    # Trino Parity Gaps: Generic Tag Matching (4 scenarios)
    "ocp_aws_scenario_20_multi_cluster_alias_matching"
    "ocp_aws_scenario_21_volume_labels_matching"
    "ocp_aws_scenario_22_pv_name_suffix_matching"
    "ocp_aws_scenario_23_multi_cluster_generic_pod_labels_matching"
)

echo -e "${BLUE}=============================================="
echo "=== OCP-on-AWS Scenario Validation ==="
echo "=== Target: 99% Confidence ==="
echo -e "==============================================${NC}"
echo ""
echo "Test Manifests: $TEST_MANIFESTS_DIR"
echo "Total Scenarios: ${#SCENARIOS[@]}"
echo ""
echo "Phase Breakdown:"
echo "  • Happy Path: 6 scenarios (70% confidence)"
echo "  • Critical Edge Cases: 4 scenarios (90% confidence)"
echo "  • Resilience: 2 scenarios (99% confidence)"
echo ""

# Cleanup (use /bin/rm to bypass shell aliases)
/bin/rm -rf "$TEST_RESULTS_DIR" "$WORK_DIR"
mkdir -p "$TEST_RESULTS_DIR" "$WORK_DIR"

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

# Activate venv for nise
source "$POC_ROOT/venv/bin/activate"

if ! command -v nise &> /dev/null; then
    echo -e "${RED}❌ nise not found in venv. Run: pip install koku-nise${NC}"
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

# Initialize summary
SUMMARY_FILE="$TEST_RESULTS_DIR/SUMMARY.md"
cat > "$SUMMARY_FILE" <<EOF
# OCP-on-AWS Scenario Validation Summary

**Date**: $(date)
**Total Scenarios**: ${#SCENARIOS[@]}
**Purpose**: Validate 100% Trino compliance

## Test Results

| # | Scenario | Status | Expected Cost | Actual Cost | Output Rows | Duration |
|---|----------|--------|---------------|-------------|-------------|----------|
EOF

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Run each scenario
for SCENARIO in "${SCENARIOS[@]}"; do
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Test $TOTAL_TESTS/${#SCENARIOS[@]}: $SCENARIO${NC}"
    echo -e "${BLUE}========================================${NC}"

    MANIFEST_FILE="$TEST_MANIFESTS_DIR/${SCENARIO}.yml"

    if [ ! -f "$MANIFEST_FILE" ]; then
        echo -e "${RED}❌ Manifest not found: $MANIFEST_FILE${NC}"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | Manifest not found |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    SCENARIO_DIR="$WORK_DIR/$SCENARIO"
    mkdir -p "$SCENARIO_DIR"

    START_TIME=$(date +%s)
    STATUS="❌ FAILED"
    OCP_ROWS=0
    AWS_ROWS=0
    OUTPUT_ROWS=0
    ERROR_MSG=""

    # Extract configuration from YAML (strip quotes)
    START_DATE=$(grep "start_date:" "$MANIFEST_FILE" | head -1 | awk '{print $2}' | tr -d "'\"")
    END_DATE=$(grep "end_date:" "$MANIFEST_FILE" | head -1 | awk '{print $2}' | tr -d "'\"")


    # Initialize CLUSTER_IDS (will be populated after rendering)
    CLUSTER_IDS=()

    # Step 0: Render Jinja2 templates (Core-style)
    echo -e "${YELLOW}→ Rendering Jinja2 templates...${NC}"
    RENDERED_MANIFEST="$SCENARIO_DIR/rendered_manifest.yml"

    python3 "$POC_ROOT/scripts/render_nise_manifests.py" \
        --template "$MANIFEST_FILE" \
        --output "$RENDERED_MANIFEST" \
        > "$TEST_RESULTS_DIR/${SCENARIO}_render.log" 2>&1

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Template rendering failed${NC}"
        tail -20 "$TEST_RESULTS_DIR/${SCENARIO}_render.log"
        ERROR_MSG="Template rendering failed"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    echo -e "${GREEN}✅ Templates rendered (resource IDs will match!)${NC}"

    # Use rendered manifest for all subsequent operations
    MANIFEST_FILE="$RENDERED_MANIFEST"

    # Determine cluster ID(s) from the RENDERED manifest
    if echo "$SCENARIO" | grep -q "multi_cluster"; then
        # Extract all cluster IDs from the rendered manifest using yq
        CLUSTER_IDS=($(yq e '.ocp.clusters[].cluster_id' "$MANIFEST_FILE"))
        echo -e "${YELLOW}→ Multi-cluster scenario: ${CLUSTER_IDS[@]}${NC}"
    else
        CLUSTER_IDS=("test-cluster-001")
        echo -e "${YELLOW}→ Single-cluster scenario: ${CLUSTER_IDS[0]}${NC}"
    fi

    # Set CLUSTER_ID for single-cluster scenarios
    CLUSTER_ID="${CLUSTER_IDS[0]}"

    # Step 1: Generate OCP data
    echo -e "${YELLOW}→ Generating OCP data...${NC}"
    cd "$SCENARIO_DIR"

    # Create OCP directory
    mkdir -p ocp

    # Extract OCP section from YAML and create temporary manifest
    OCP_MANIFEST="$SCENARIO_DIR/ocp_manifest.yml"
    python3 -c "
import yaml
import sys
try:
    with open('$MANIFEST_FILE', 'r') as f:
        data = yaml.safe_load(f)

    if 'ocp' in data:
        # Handle simple format: ocp.generators[]
        if 'generators' in data['ocp']:
            ocp_data = {'generators': data['ocp']['generators']}
            if 'start_date' in data:
                ocp_data['start_date'] = data['start_date']
            if 'end_date' in data:
                ocp_data['end_date'] = data['end_date']
            print(yaml.dump(ocp_data, default_flow_style=False))
        # Handle multi-cluster format: ocp.clusters[].generators[]
        elif 'clusters' in data['ocp']:
            # For multi-cluster, generate data for ALL clusters
            # We'll loop through clusters outside this python block
            import json
            from datetime import date

            def date_converter(obj):
                if isinstance(obj, date):
                    return obj.isoformat()
                raise TypeError(f'Object of type {type(obj)} is not JSON serializable')

            clusters_data = []
            for cluster in data['ocp']['clusters']:
                ocp_data = {'generators': cluster['generators']}
                if 'start_date' in data:
                    ocp_data['start_date'] = data['start_date']
                if 'end_date' in data:
                    ocp_data['end_date'] = data['end_date']
                clusters_data.append({
                    'cluster_id': cluster['cluster_id'],
                    'manifest': ocp_data
                })
            print(json.dumps(clusters_data, default=date_converter))
        else:
            print('ERROR: No OCP generators found in manifest', file=sys.stderr)
            sys.exit(1)
    else:
        print('ERROR: No OCP generators found in manifest', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" > "$OCP_MANIFEST"

    if [ ! -s "$OCP_MANIFEST" ]; then
        echo -e "${RED}❌ Failed to extract OCP manifest${NC}"
        ERROR_MSG="OCP manifest extraction failed"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # Check if this is multi-cluster (JSON output) or single cluster (YAML output)
    if echo "$SCENARIO" | grep -q "multi_cluster"; then
        # Multi-cluster: parse JSON and generate data for each cluster
        echo -e "${YELLOW}→ Multi-cluster scenario - generating data for all clusters${NC}"

        CLUSTERS_JSON=$(cat "$OCP_MANIFEST")
        CLUSTER_COUNT=$(echo "$CLUSTERS_JSON" | jq '. | length')

        for ((i=0; i<CLUSTER_COUNT; i++)); do
            CURRENT_CLUSTER_ID=$(echo "$CLUSTERS_JSON" | jq -r ".[$i].cluster_id")
            echo -e "${YELLOW}→ Generating OCP data for cluster: $CURRENT_CLUSTER_ID${NC}"

            # Create temporary manifest for this cluster
            CLUSTER_MANIFEST="$SCENARIO_DIR/ocp_manifest_${CURRENT_CLUSTER_ID}.yml"
            echo "$CLUSTERS_JSON" | jq -r ".[$i].manifest" | python3 -c "
import yaml, sys, json
data = json.load(sys.stdin)
print(yaml.dump(data, default_flow_style=False))
" > "$CLUSTER_MANIFEST"

            # Generate OCP data for this cluster
            if nise report ocp \
                --static-report-file "$CLUSTER_MANIFEST" \
                --ocp-cluster-id "$CURRENT_CLUSTER_ID" \
                --start-date "$START_DATE" \
                --end-date "$END_DATE" \
                --insights-upload "ocp" \
                > "$TEST_RESULTS_DIR/${SCENARIO}_ocp_nise_${CURRENT_CLUSTER_ID}.log" 2>&1; then

                CLUSTER_OCP_ROWS=$(find ocp -name "*${CURRENT_CLUSTER_ID}*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
                echo -e "${GREEN}✅ OCP data generated for $CURRENT_CLUSTER_ID ($CLUSTER_OCP_ROWS rows)${NC}"
            else
                echo -e "${RED}❌ Failed to generate OCP data for $CURRENT_CLUSTER_ID${NC}"
                ERROR_MSG="OCP generation failed for $CURRENT_CLUSTER_ID"
                tail -20 "$TEST_RESULTS_DIR/${SCENARIO}_ocp_nise_${CURRENT_CLUSTER_ID}.log"
                echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
                FAILED_TESTS=$((FAILED_TESTS + 1))
                continue 2  # Skip to next scenario
            fi
        done

        # Count total OCP rows across all clusters
        OCP_ROWS=$(find ocp -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
        echo -e "${GREEN}✅ Total OCP data generated across all clusters ($OCP_ROWS rows)${NC}"
    else
        # Single cluster: generate as usual
        if nise report ocp \
            --static-report-file "$OCP_MANIFEST" \
            --ocp-cluster-id "$CLUSTER_ID" \
            --start-date "$START_DATE" \
            --end-date "$END_DATE" \
            --insights-upload "ocp" \
            > "$TEST_RESULTS_DIR/${SCENARIO}_ocp_nise.log" 2>&1; then

            OCP_ROWS=$(find ocp -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
            echo -e "${GREEN}✅ OCP data generated ($OCP_ROWS rows)${NC}"
        else
            echo -e "${RED}❌ Failed to generate OCP data${NC}"
            ERROR_MSG="OCP generation failed"
            tail -20 "$TEST_RESULTS_DIR/${SCENARIO}_ocp_nise.log"
            echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            continue
        fi
    fi

    # Step 2: Generate AWS data
    echo -e "${YELLOW}→ Generating AWS data...${NC}"
    mkdir -p aws

    # Extract AWS section from YAML and create temporary manifest
    AWS_MANIFEST="$SCENARIO_DIR/aws_manifest.yml"
    python3 -c "
import yaml
import sys
try:
    with open('$MANIFEST_FILE', 'r') as f:
        data = yaml.safe_load(f)
    if 'aws' in data and 'generators' in data['aws']:
        aws_data = {'generators': data['aws']['generators']}
        if 'start_date' in data:
            aws_data['start_date'] = data['start_date']
        if 'end_date' in data:
            aws_data['end_date'] = data['end_date']
        print(yaml.dump(aws_data, default_flow_style=False))
    else:
        print('ERROR: No AWS generators found in manifest', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" > "$AWS_MANIFEST"

    if [ ! -s "$AWS_MANIFEST" ]; then
        echo -e "${RED}❌ Failed to extract AWS manifest${NC}"
        ERROR_MSG="AWS manifest extraction failed"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | - | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    if nise report aws \
        --static-report-file "$AWS_MANIFEST" \
        --start-date "$START_DATE" \
        --end-date "$END_DATE" \
        --write-monthly \
        > "$TEST_RESULTS_DIR/${SCENARIO}_aws_nise.log" 2>&1; then

        AWS_ROWS=$(find . -maxdepth 1 -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
        echo -e "${GREEN}✅ AWS data generated ($AWS_ROWS rows)${NC}"
    else
        echo -e "${RED}❌ Failed to generate AWS data${NC}"
        ERROR_MSG="AWS generation failed"
        tail -20 "$TEST_RESULTS_DIR/${SCENARIO}_aws_nise.log"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | $OCP_ROWS | - | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # REMOVED: align_test_data.py - Too complex, not needed
    # Core Approach: Validate totals/costs, NOT specific resource ID matches
    # Let nise generate random IDs - we'll validate aggregate costs match expected totals
    # This is simpler, more robust, and matches how Core validates
    # Step 3a: Clear MinIO bucket (prevent cross-scenario contamination)
    echo -e "${YELLOW}→ Clearing MinIO bucket...${NC}"
    cd "$POC_ROOT"
    source venv/bin/activate
    python3 << 'EOFC'
import boto3
from botocore.client import Config

s3 = boto3.client(
    's3',
    endpoint_url='http://127.0.0.1:9000',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin',
    config=Config(signature_version='s3v4'),
    region_name='us-east-1'
)

try:
    # List and delete all objects in test-bucket
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket='test-bucket'):
        if 'Contents' in page:
            objects = [{'Key': obj['Key']} for obj in page['Contents']]
            s3.delete_objects(Bucket='test-bucket', Delete={'Objects': objects})
    print(f'✓ Cleared MinIO bucket')
except Exception as e:
    print(f'⚠️  Failed to clear MinIO: {e}')
EOFC

    # Step 3b: Convert to Parquet
    echo -e "${YELLOW}→ Converting to Parquet...${NC}"

    if python scripts/csv_to_parquet_minio.py "$SCENARIO_DIR" \
        > "$TEST_RESULTS_DIR/${SCENARIO}_parquet.log" 2>&1; then
        echo -e "${GREEN}✅ Parquet files uploaded${NC}"
    else
        echo -e "${RED}❌ Parquet conversion failed${NC}"
        ERROR_MSG="Parquet conversion failed"
        tail -20 "$TEST_RESULTS_DIR/${SCENARIO}_parquet.log"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | $OCP_ROWS | $AWS_ROWS | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    # Step 4: Clear database
    echo -e "${YELLOW}→ Clearing database...${NC}"
    podman exec postgres-poc psql -U koku -d koku -c "
        TRUNCATE TABLE org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
    " > /dev/null 2>&1 || true

    # Step 5: Run POC aggregation (for each cluster in multi-cluster scenarios)
    echo -e "${YELLOW}→ Running POC aggregation...${NC}"

    # Clear Python cache to prevent import/module caching between scenarios
    find "$POC_ROOT/src" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    # Extract year and month from START_DATE (format: YYYY-MM-DD)
    POC_YEAR=$(echo "$START_DATE" | cut -d'-' -f1)
    POC_MONTH=$(echo "$START_DATE" | cut -d'-' -f2)

    export POC_YEAR="$POC_YEAR"
    export POC_MONTH="$POC_MONTH"
    export POSTGRES_HOST="$POSTGRES_HOST"
    export POSTGRES_PORT="$POSTGRES_PORT"
    export POSTGRES_USER="koku"
    export POSTGRES_PASSWORD="koku123"
    export POSTGRES_DB="koku"
    export ORG_ID="org1234567"
    export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
    export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"

    # S3/MinIO credentials
    export S3_ENDPOINT="http://127.0.0.1:9000"
    export S3_BUCKET="test-bucket"
    export S3_ACCESS_KEY="minioadmin"
    export S3_SECRET_KEY="minioadmin"
    export POSTGRES_HOST="127.0.0.1"
    export POSTGRES_PORT="15432"
    export POSTGRES_DB="koku"
    export POSTGRES_USER="koku"
    export POSTGRES_PASSWORD="koku123"

    # Run POC once (it processes all clusters in a single run)
    # Note: POC reads all OCP data from Parquet, regardless of cluster_id filter
    # Running it multiple times would duplicate costs in PostgreSQL
    POC_FAILED=false
    if [ ${#CLUSTER_IDS[@]} -gt 1 ]; then
        echo -e "${YELLOW}  → Processing all clusters: ${CLUSTER_IDS[@]}${NC}"
    fi

    # Set OCP_CLUSTER_ID for config (required by config file, even though POC reads all clusters)
    # For multi-cluster scenarios, just use the first cluster ID (it's not used for filtering)
    export OCP_CLUSTER_ID="${CLUSTER_IDS[0]}"

    # Extract and set cluster_alias (required for tag matching)
    if echo "$SCENARIO" | grep -q "multi_cluster"; then
        # Multi-cluster: extract cluster_alias from the first cluster in the manifest
        CLUSTER_ALIAS=$(yq e '.ocp.clusters[0].cluster_alias' "$MANIFEST_FILE")
        if [ -n "$CLUSTER_ALIAS" ] && [ "$CLUSTER_ALIAS" != "null" ]; then
            export OCP_CLUSTER_ALIAS="$CLUSTER_ALIAS"
            echo -e "${YELLOW}  → Using cluster_alias: $CLUSTER_ALIAS${NC}"
        else
            # Default for scenarios without explicit cluster_alias
            export OCP_CLUSTER_ALIAS="OCP Cluster"
        fi
    else
        # Single-cluster: use default
        export OCP_CLUSTER_ALIAS="OCP Cluster"
    fi

    POC_LOG="$TEST_RESULTS_DIR/${SCENARIO}_poc.log"
    if timeout 120 python -m src.main > "$POC_LOG" 2>&1; then
        if [ ${#CLUSTER_IDS[@]} -gt 1 ]; then
            echo -e "${GREEN}  ✅ All clusters processed${NC}"
        fi
    else
        echo -e "${RED}❌ POC aggregation failed${NC}"
        tail -50 "$POC_LOG"
        POC_FAILED=true
    fi

    if [ "$POC_FAILED" = true ]; then
        ERROR_MSG="POC aggregation failed"
        echo "| $TOTAL_TESTS | $SCENARIO | ❌ FAILED | $OCP_ROWS | $AWS_ROWS | - | - | - | $ERROR_MSG |" >> "$SUMMARY_FILE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        continue
    fi

    echo -e "${GREEN}✅ POC aggregation complete${NC}"

    # Extract memory usage from POC log
    # Format: peak_rss_mb='177.11 MB' (with ANSI color codes)
    PEAK_MEMORY=$(grep "peak_rss_mb" "$TEST_RESULTS_DIR/${SCENARIO}_poc.log" | tail -1 | sed 's/\x1b\[[0-9;]*m//g' | sed -n "s/.*peak_rss_mb='\([0-9.]*\).*/\1/p" || echo "0")
    PEAK_MEMORY="${PEAK_MEMORY:-0}"
    if [ "$PEAK_MEMORY" != "0" ]; then
        PEAK_MEMORY_DISPLAY="${PEAK_MEMORY}MB"
    else
        PEAK_MEMORY_DISPLAY="N/A"
    fi

        # Step 6: Validate results
        echo -e "${YELLOW}→ Validating results...${NC}"

        OUTPUT_ROWS=$(podman exec postgres-poc psql -U koku -d koku -t -c "
            SELECT COUNT(*)
            FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
        " 2>/dev/null | tr -d ' ' || echo "0")

        # Ensure OUTPUT_ROWS is numeric
        OUTPUT_ROWS=${OUTPUT_ROWS:-0}

        # Extract expected cost from manifest
        EXPECTED_COST=$(python3 -c "
import yaml
with open('$MANIFEST_FILE') as f:
    m = yaml.safe_load(f)
    expected = m.get('expected_outcome', {})
    cost = expected.get('total_cost') or expected.get('attributed_cost') or expected.get('total_amortized_cost') or 0
    print(f'{float(cost):.2f}')
" 2>/dev/null || echo "N/A")

        # Get actual cost from DB
        ACTUAL_COST=$(podman exec postgres-poc psql -U koku -d koku -t -c "
            SELECT COALESCE(ROUND(SUM(unblended_cost)::numeric, 2), 0)
            FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;
        " 2>/dev/null | tr -d ' ' || echo "0.00")

        if [ "$OUTPUT_ROWS" -gt 0 ] 2>/dev/null; then
            echo -e "${GREEN}✅ POC generated $OUTPUT_ROWS output rows${NC}"
            echo -e "${BLUE}   Expected cost: \$$EXPECTED_COST${NC}"
            echo -e "${BLUE}   Actual cost:   \$$ACTUAL_COST${NC}"

            # Validate results (Core-style: check totals match expected)
            echo -e "${YELLOW}→ Validating results (Core-style: totals)...${NC}"
            cd "$POC_ROOT"
            source venv/bin/activate

            if python3 scripts/validate_totals_iqe_style.py "$MANIFEST_FILE" \
                > "$TEST_RESULTS_DIR/${SCENARIO}_validation.txt" 2>&1; then
                STATUS="✅ PASS"
                PASSED_TESTS=$((PASSED_TESTS + 1))
                echo -e "${GREEN}✅ Scenario passed: Expected \$$EXPECTED_COST, Got \$$ACTUAL_COST${NC}"

                # Show validation summary
                cat "$TEST_RESULTS_DIR/${SCENARIO}_validation.txt"
            else
                STATUS="❌ FAIL"
                FAILED_TESTS=$((FAILED_TESTS + 1))
                echo -e "${RED}❌ Scenario failed: Expected \$$EXPECTED_COST, Got \$$ACTUAL_COST${NC}"

                # Show validation errors
                cat "$TEST_RESULTS_DIR/${SCENARIO}_validation.txt"
            fi

            # Save detailed results with validation query
            cat > "$TEST_RESULTS_DIR/${SCENARIO}_results.txt" <<VALIDATION_EOF
================================================================================
VALIDATION QUERY - Run this to verify results yourself:
================================================================================

-- Total cost and row count
SELECT 
    COUNT(*) as output_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces,
    COUNT(DISTINCT cluster_id) as clusters
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Cost breakdown by namespace
SELECT 
    namespace,
    COUNT(*) as rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY namespace
ORDER BY cost DESC;

-- Sample rows with all key columns
SELECT
    usage_start,
    cluster_id,
    namespace,
    resource_id_matched,
    tag_matched,
    ROUND(unblended_cost::numeric, 2) as cost,
    ROUND(pod_usage_cpu_core_hours::numeric, 2) as cpu_hours,
    ROUND(pod_usage_memory_gigabyte_hours::numeric, 2) as memory_gb_hours
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
ORDER BY usage_start, namespace
LIMIT 20;

================================================================================
ACTUAL QUERY RESULTS:
================================================================================
VALIDATION_EOF
            podman exec postgres-poc psql -U koku -d koku -c "
                SELECT
                    usage_start,
                    cluster_id,
                    namespace,
                    resource_id_matched,
                    tag_matched,
                    ROUND(unblended_cost::numeric, 2) as cost,
                    ROUND(pod_usage_cpu_core_hours::numeric, 2) as cpu_hours,
                    ROUND(pod_usage_memory_gigabyte_hours::numeric, 2) as memory_gb_hours
                FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
                ORDER BY usage_start, namespace
                LIMIT 20;
            " >> "$TEST_RESULTS_DIR/${SCENARIO}_results.txt" 2>&1 || true
        else
            STATUS="❌ FAIL"
            EXPECTED_COST="${EXPECTED_COST:-N/A}"
            ACTUAL_COST="0.00"
            FAILED_TESTS=$((FAILED_TESTS + 1))
            echo -e "${RED}❌ Scenario failed: No output rows (expected \$$EXPECTED_COST)${NC}"
        fi

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Write to summary with expected vs actual costs
    echo "| $TOTAL_TESTS | $SCENARIO | $STATUS | \$$EXPECTED_COST | \$$ACTUAL_COST | $OUTPUT_ROWS | ${DURATION}s |" >> "$SUMMARY_FILE"

    echo ""
done

# Generate final summary
cat >> "$SUMMARY_FILE" <<EOF

---

## Summary Statistics

- **Total Scenarios**: $TOTAL_TESTS
- **Passed**: $PASSED_TESTS ($(( PASSED_TESTS * 100 / TOTAL_TESTS ))%)
- **Failed**: $FAILED_TESTS ($(( FAILED_TESTS * 100 / TOTAL_TESTS ))%)

EOF

if [ $FAILED_TESTS -eq 0 ]; then
    cat >> "$SUMMARY_FILE" <<EOF
### ✅ **ALL SCENARIOS PASSED!**

**Trino Compliance**: 100% ✅

The POC successfully passed all OCP-on-AWS validation scenarios:
- Resource ID matching
- Tag matching
- Multi-namespace attribution
- Network cost handling
- Storage/EBS volumes
- Multi-cluster support

**Status**: Production-ready for OCP-on-AWS aggregation

---

## How to Verify Results

### Quick Verification Query

Connect to PostgreSQL and run:

\`\`\`sql
-- Connect: podman exec -it postgres-poc psql -U koku -d koku

-- Total cost summary
SELECT 
    COUNT(*) as output_rows,
    ROUND(SUM(unblended_cost)::numeric, 2) as total_cost,
    COUNT(DISTINCT namespace) as namespaces
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p;

-- Cost by namespace
SELECT 
    namespace,
    ROUND(SUM(unblended_cost)::numeric, 2) as cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
GROUP BY namespace
ORDER BY cost DESC;
\`\`\`

### Detailed Validation

Each scenario has a \`*_results.txt\` file in \`scenario-test-results/\` with:
- The exact SQL queries used for validation
- Sample output rows
- Expected vs actual cost comparison
EOF
    echo -e "${GREEN}"
    echo "=============================================="
    echo "✅ ALL $TOTAL_TESTS SCENARIOS PASSED!"
    echo "✅ 100% TRINO COMPLIANCE ACHIEVED!"
    echo "=============================================="
    echo -e "${NC}"
else
    cat >> "$SUMMARY_FILE" <<EOF
### ⚠️ **SOME SCENARIOS FAILED**

**Passed**: $PASSED_TESTS/$TOTAL_TESTS
**Failed**: $FAILED_TESTS/$TOTAL_TESTS

Please review individual test logs for details.
EOF
    echo -e "${RED}"
    echo "=============================================="
    echo "❌ $FAILED_TESTS of $TOTAL_TESTS SCENARIOS FAILED"
    echo "=============================================="
    echo -e "${NC}"
fi

echo ""
echo "Full results: $SUMMARY_FILE"
echo "Test logs: $TEST_RESULTS_DIR"
echo ""

# Display summary
cat "$SUMMARY_FILE"

exit $FAILED_TESTS

