#!/bin/bash
#
# OCP-Only Test Script
# Runs unit tests and a basic integration test for OCP-only aggregation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

cd "$POC_DIR"

echo "=============================================================="
echo "OCP-Only Tests"
echo "=============================================================="

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "ERROR: Virtual environment not found. Run: python -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# Run unit tests (components that don't require infrastructure)
echo ""
echo "=== Running Unit Tests ==="
pytest tests/test_cost_attributor.py tests/test_resource_matcher.py tests/test_tag_matcher.py tests/test_network_cost_handler.py tests/test_json_format.py -v --tb=short

# Run integration test if infrastructure is available
echo ""
echo "=== Checking Infrastructure ==="

# Check MinIO
if curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "✓ MinIO is running"
    MINIO_OK=true
else
    echo "✗ MinIO not running (run: podman-compose up -d)"
    MINIO_OK=false
fi

# Check PostgreSQL
if PGPASSWORD=koku123 psql -h localhost -p 15432 -U koku -d koku -c "SELECT 1" > /dev/null 2>&1; then
    echo "✓ PostgreSQL is running"
    POSTGRES_OK=true
else
    echo "✗ PostgreSQL not running (run: podman-compose up -d)"
    POSTGRES_OK=false
fi

if [ "$MINIO_OK" = true ] && [ "$POSTGRES_OK" = true ]; then
    echo ""
    echo "=== Running Integration Test ==="

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
    export OCP_CLUSTER_ID="test-cluster"

    # Run storage integration tests
    pytest tests/test_storage_integration.py -v --tb=short

    echo ""
    echo "✓ All OCP-only tests passed!"
else
    echo ""
    echo "⚠ Skipping integration tests (infrastructure not available)"
    echo "  Run 'podman-compose up -d' to start MinIO and PostgreSQL"
fi

echo ""
echo "=============================================================="
echo "Test Summary"
echo "=============================================================="
echo "Unit tests: PASSED"
if [ "$MINIO_OK" = true ] && [ "$POSTGRES_OK" = true ]; then
    echo "Integration tests: PASSED"
else
    echo "Integration tests: SKIPPED (no infrastructure)"
fi

