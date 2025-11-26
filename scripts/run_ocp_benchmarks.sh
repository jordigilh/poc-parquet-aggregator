#!/bin/bash
#
# OCP-Only Benchmark Script
# Runs performance benchmarks for OCP-only aggregation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

cd "$POC_DIR"

echo "=============================================================="
echo "OCP-Only Benchmarks"
echo "=============================================================="

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "ERROR: Virtual environment not found. Run: python -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# Check dependencies
echo ""
echo "=== Checking Infrastructure ==="

# Check MinIO
if ! curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "ERROR: MinIO not running. Run: podman-compose up -d"
    exit 1
fi
echo "✓ MinIO is running"

# Check PostgreSQL
if ! PGPASSWORD=koku123 psql -h localhost -p 15432 -U koku -d koku -c "SELECT 1" > /dev/null 2>&1; then
    echo "ERROR: PostgreSQL not running. Run: podman-compose up -d"
    exit 1
fi
echo "✓ PostgreSQL is running"

# Set environment for OCP-only mode (no AWS_PROVIDER_UUID)
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="koku"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="15432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export ORG_ID="org1234567"
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export OCP_CLUSTER_ID="benchmark-cluster"
export POC_YEAR="2024"
export POC_MONTH="01"

# Ensure no AWS mode
unset AWS_PROVIDER_UUID

echo ""
echo "=== Configuration ==="
echo "Provider UUID: $OCP_PROVIDER_UUID"
echo "Cluster ID: $OCP_CLUSTER_ID"
echo "Year/Month: $POC_YEAR/$POC_MONTH"
echo "Mode: OCP-only (in-memory)"

# Check if data exists
echo ""
echo "=== Checking Data ==="
DATA_PATH="data/$ORG_ID/OCP/source=$OCP_PROVIDER_UUID/year=$POC_YEAR/month=$POC_MONTH"
if mc ls local/$S3_BUCKET/$DATA_PATH > /dev/null 2>&1; then
    echo "✓ OCP data found in MinIO"
else
    echo "⚠ No OCP data found at: $DATA_PATH"
    echo ""
    echo "To generate test data:"
    echo "  1. Create a nise manifest (see test-manifests/ocp-only/)"
    echo "  2. Run: nise report ocp --static-report-file <manifest.yml>"
    echo "  3. Run: python scripts/csv_to_parquet_minio.py ./ocp"
    echo ""
    echo "Or use existing E2E test data:"
    echo "  ./scripts/run_ocp_aws_scenario_tests.sh --scenario 1"
    exit 1
fi

# Clear database
echo ""
echo "=== Preparing Database ==="
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB \
    -c "TRUNCATE TABLE ${ORG_ID}.reporting_ocpusagelineitem_daily_summary;" > /dev/null 2>&1 || true
echo "✓ Database cleared"

# Run benchmark
echo ""
echo "=== Running Benchmark ==="
echo "Starting at: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

START_TIME=$(date +%s.%N)

# Run aggregation and capture output
python -m src.main 2>&1 | tee /tmp/ocp_benchmark.log

END_TIME=$(date +%s.%N)
DURATION=$(echo "$END_TIME - $START_TIME" | bc)

# Get row count
ROW_COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB \
    -t -c "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary;" 2>/dev/null | tr -d ' ')

echo ""
echo "=============================================================="
echo "Benchmark Results"
echo "=============================================================="
echo "Mode:         OCP-only (in-memory)"
echo "Duration:     ${DURATION}s"
echo "Output rows:  ${ROW_COUNT:-0}"
if [ -n "$ROW_COUNT" ] && [ "$ROW_COUNT" -gt 0 ]; then
    THROUGHPUT=$(echo "scale=0; $ROW_COUNT / $DURATION" | bc)
    echo "Throughput:   ${THROUGHPUT} rows/sec"
fi
echo ""
echo "Full log: /tmp/ocp_benchmark.log"
echo "=============================================================="


