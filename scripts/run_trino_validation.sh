#!/bin/bash
#
# Quick Trino Validation Script
#
# This script runs the complete validation flow:
# 1. Check prerequisites
# 2. Upload test data to MinIO (if needed)
# 3. Run POC aggregation
# 4. Validate against Trino
#
# Usage:
#   ./scripts/run_trino_validation.sh
#

set -e  # Exit on error

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$POC_DIR"

echo "=============================================="
echo "=== Trino Validation - Complete Flow ==="
echo "=============================================="
echo ""

# Check if we're using existing data or need to specify
if [ -z "$OCP_CLUSTER_ID" ]; then
    echo "⚠️  OCP_CLUSTER_ID not set"
    echo ""
    echo "Please set the following environment variables:"
    echo ""
    echo "  export OCP_CLUSTER_ID='your-cluster-id'"
    echo "  export OCP_PROVIDER_UUID='your-provider-uuid'"
    echo "  export OCP_YEAR='2025'"
    echo "  export OCP_MONTH='10'"
    echo "  export POSTGRES_PASSWORD='your-password'"
    echo ""
    echo "Available test data:"
    ls -1 October-2025-*-ocp_*.csv 2>/dev/null | head -5 || echo "  (no CSV files found)"
    echo ""
    echo "To use existing Core test data:"
    echo "  export OCP_CLUSTER_ID='iqe-test-cluster'"
    echo ""
    exit 1
fi

echo "Configuration:"
echo "  Cluster ID:    $OCP_CLUSTER_ID"
echo "  Provider UUID: $OCP_PROVIDER_UUID"
echo "  Year:          $OCP_YEAR"
echo "  Month:         $OCP_MONTH"
echo "  Schema:        ${POSTGRES_SCHEMA:-org1234567}"
echo ""

# Step 1: Check prerequisites
echo "=============================================="
echo "Step 1: Checking Prerequisites"
echo "=============================================="

# Check Python packages
echo "Checking Python packages..."
python3 -c "import trino" 2>/dev/null || {
    echo "❌ trino module not installed"
    echo "Install with: pip install trino"
    exit 1
}
echo "✅ trino module installed"

python3 -c "import psycopg2" 2>/dev/null || {
    echo "❌ psycopg2 module not installed"
    echo "Install with: pip install psycopg2-binary"
    exit 1
}
echo "✅ psycopg2 module installed"

python3 -c "import pandas" 2>/dev/null || {
    echo "❌ pandas module not installed"
    echo "Install with: pip install pandas"
    exit 1
}
echo "✅ pandas module installed"

# Check PostgreSQL connectivity
echo ""
echo "Checking PostgreSQL connectivity..."
export PGPASSWORD="${POSTGRES_PASSWORD}"
psql -h "${POSTGRES_HOST:-postgresql.cost-management.svc.cluster.local}" \
     -U "${POSTGRES_USER:-koku}" \
     -d "${POSTGRES_DB:-koku}" \
     -c "SELECT 1;" > /dev/null 2>&1 || {
    echo "❌ Cannot connect to PostgreSQL"
    echo "   Host: ${POSTGRES_HOST:-postgresql.cost-management.svc.cluster.local}"
    echo ""
    echo "If running locally, you may need port-forward:"
    echo "  oc port-forward -n cost-mgmt svc/postgresql 5432:5432"
    exit 1
}
echo "✅ PostgreSQL accessible"

# Check if data exists
echo ""
echo "Checking for existing data..."
EXISTING_ROWS=$(psql -h "${POSTGRES_HOST:-postgresql.cost-management.svc.cluster.local}" \
     -U "${POSTGRES_USER:-koku}" \
     -d "${POSTGRES_DB:-koku}" \
     -t -c "SELECT COUNT(*) FROM ${POSTGRES_SCHEMA:-org1234567}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$OCP_CLUSTER_ID' AND EXTRACT(YEAR FROM usage_start) = $OCP_YEAR AND EXTRACT(MONTH FROM usage_start) = $OCP_MONTH;" 2>/dev/null | xargs)

if [ "$EXISTING_ROWS" -gt 0 ]; then
    echo "⚠️  Found $EXISTING_ROWS existing rows for this cluster/period"
    echo ""
    read -p "Do you want to re-run POC (will truncate existing data)? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping POC run, using existing data..."
        SKIP_POC=true
    else
        SKIP_POC=false
    fi
else
    echo "✅ No existing data found (will run POC)"
    SKIP_POC=false
fi

# Step 2: Run POC (if needed)
if [ "$SKIP_POC" = false ]; then
    echo ""
    echo "=============================================="
    echo "Step 2: Running POC Aggregation"
    echo "=============================================="
    echo ""
    echo "This will:"
    echo "  1. Read Parquet files from MinIO"
    echo "  2. Aggregate Pod + Storage data"
    echo "  3. Write to PostgreSQL"
    echo ""

    # Check if data is in MinIO (optional check)
    echo "Running POC..."
    python3 -m src.main --truncate 2>&1 | tee /tmp/poc_validation_run.log

    if grep -q "POC COMPLETED SUCCESSFULLY" /tmp/poc_validation_run.log; then
        echo ""
        echo "✅ POC completed successfully"

        # Extract row counts from log
        POD_ROWS=$(grep "pod summary rows" /tmp/poc_validation_run.log | grep -oP '\d+' || echo "?")
        STORAGE_ROWS=$(grep "storage summary rows" /tmp/poc_validation_run.log | grep -oP '\d+' || echo "?")
        TOTAL_ROWS=$(grep "total rows" /tmp/poc_validation_run.log | grep -oP '\d+' | head -1 || echo "?")

        echo "  Pod rows:     $POD_ROWS"
        echo "  Storage rows: $STORAGE_ROWS"
        echo "  Total rows:   $TOTAL_ROWS"
    else
        echo ""
        echo "❌ POC failed"
        echo "Check log: /tmp/poc_validation_run.log"
        exit 1
    fi
else
    echo ""
    echo "=============================================="
    echo "Step 2: Using Existing POC Data"
    echo "=============================================="
    echo "  Existing rows: $EXISTING_ROWS"
fi

# Step 3: Validate against Trino
echo ""
echo "=============================================="
echo "Step 3: Validating Against Trino"
echo "=============================================="
echo ""

# Check Trino connectivity first
echo "Checking Trino connectivity..."
python3 -c "
import trino
import os
try:
    conn = trino.dbapi.connect(
        host=os.getenv('TRINO_HOST', 'trino-coordinator.cost-management.svc.cluster.local'),
        port=int(os.getenv('TRINO_PORT', 8080)),
        user=os.getenv('TRINO_USER', 'koku'),
        catalog='hive',
        schema=os.getenv('POSTGRES_SCHEMA', 'org1234567')
    )
    cursor = conn.cursor()
    cursor.execute('SELECT 1')
    cursor.fetchall()
    print('✅ Trino accessible')
except Exception as e:
    print(f'❌ Cannot connect to Trino: {e}')
    print('')
    print('If running locally, you may need port-forward:')
    print('  oc port-forward -n cost-mgmt svc/trino-coordinator 8080:8080')
    exit(1)
"

if [ $? -ne 0 ]; then
    exit 1
fi

echo ""
echo "Running validation..."
python3 scripts/validate_against_trino.py \
    "$OCP_CLUSTER_ID" \
    "$OCP_PROVIDER_UUID" \
    "$OCP_YEAR" \
    "$OCP_MONTH" \
    2>&1 | tee /tmp/trino_validation_results.log

VALIDATION_EXIT_CODE=$?

echo ""
echo "=============================================="
echo "=== Validation Complete ==="
echo "=============================================="
echo ""
echo "Logs saved to:"
echo "  POC run:    /tmp/poc_validation_run.log"
echo "  Validation: /tmp/trino_validation_results.log"
echo ""

if [ $VALIDATION_EXIT_CODE -eq 0 ]; then
    echo "✅✅✅ SUCCESS ✅✅✅"
    echo ""
    echo "POC matches Trino 1:1!"
    echo "Ready to proceed with OCP-in-AWS implementation."
    echo ""
else
    echo "❌ VALIDATION FAILED"
    echo ""
    echo "Review the differences above and investigate."
    echo "Check /tmp/trino_validation_results.log for details."
    echo ""
    exit 1
fi

