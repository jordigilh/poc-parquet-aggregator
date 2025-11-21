#!/bin/bash
#
# Preflight checks for manual benchmarking
#

set -e

echo "================================================================================"
echo "PREFLIGHT CHECKS"
echo "================================================================================"
echo ""

FAILED=0
WARNINGS=0

# Check 1: Podman is running
echo "✓ Check 1: Podman service"
if command -v podman &> /dev/null; then
    echo "  ✅ Podman installed"
else
    echo "  ❌ Podman not found"
    FAILED=$((FAILED + 1))
fi

# Check 2: PostgreSQL container
echo ""
echo "✓ Check 2: PostgreSQL container"
if podman ps --format "{{.Names}}" | grep -q "postgres-poc"; then
    echo "  ✅ PostgreSQL container running"

    # Test connection
    if podman exec postgres-poc psql -U koku -d koku -c "SELECT 1;" > /dev/null 2>&1; then
        echo "  ✅ PostgreSQL connection successful"
    else
        echo "  ⚠️  PostgreSQL connection failed (but container is running)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "  ❌ PostgreSQL container not running"
    echo "     Run: ./scripts/start-local-env.sh"
    FAILED=$((FAILED + 1))
fi

# Check 3: MinIO container
echo ""
echo "✓ Check 3: MinIO container"
if podman ps --format "{{.Names}}" | grep -q "minio-poc"; then
    echo "  ✅ MinIO container running"

    # Test connection
    if curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        echo "  ✅ MinIO health check passed"
    else
        echo "  ⚠️  MinIO health check failed (but container is running)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "  ❌ MinIO container not running"
    echo "     Run: ./scripts/start-local-env.sh"
    FAILED=$((FAILED + 1))
fi

# Check 4: Python virtual environment
echo ""
echo "✓ Check 4: Python environment"
if [ -d "venv" ]; then
    echo "  ✅ Virtual environment exists"

    if [ -f "venv/bin/python3" ]; then
        echo "  ✅ Python executable found"
        PYTHON_VERSION=$(venv/bin/python3 --version)
        echo "     $PYTHON_VERSION"
    else
        echo "  ❌ Python executable not found in venv"
        FAILED=$((FAILED + 1))
    fi
else
    echo "  ❌ Virtual environment not found"
    echo "     Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    FAILED=$((FAILED + 1))
fi

# Check 5: Required Python packages
echo ""
echo "✓ Check 5: Python dependencies"
if [ -f "venv/bin/python3" ]; then
    REQUIRED_PACKAGES=("pandas" "pyarrow" "s3fs" "psycopg2" "yaml")
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        if ./venv/bin/python3 -c "import $pkg" 2>/dev/null; then
            echo "  ✅ $pkg"
        else
            echo "  ❌ $pkg not installed"
            FAILED=$((FAILED + 1))
        fi
    done
fi

# Check 6: nise tool
echo ""
echo "✓ Check 6: nise tool"
if command -v nise &> /dev/null; then
    echo "  ✅ nise installed"
    NISE_VERSION=$(nise --version 2>&1 | head -1)
    echo "     $NISE_VERSION"
else
    echo "  ❌ nise not found"
    echo "     Run: pip install koku-nise"
    FAILED=$((FAILED + 1))
fi

# Check 7: Database schema
echo ""
echo "✓ Check 7: Database schema"
if podman exec postgres-poc psql -U koku -d koku -c "\dt org1234567.reporting_ocpusagelineitem_daily_summary" > /dev/null 2>&1; then
    echo "  ✅ Summary table exists"

    # Check row count
    ROW_COUNT=$(podman exec postgres-poc psql -U koku -d koku -t -c "SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary;" 2>/dev/null | tr -d ' ')
    echo "     Current rows: $ROW_COUNT"
else
    echo "  ⚠️  Summary table not found (will be created on first run)"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 8: MinIO bucket
echo ""
echo "✓ Check 8: MinIO bucket"
if [ -f "venv/bin/python3" ]; then
    source venv/bin/activate
    BUCKET_CHECK=$(python3 << 'EOF'
import s3fs
try:
    fs = s3fs.S3FileSystem(
        key='minioadmin',
        secret='minioadmin',
        client_kwargs={'endpoint_url': 'http://localhost:9000'}
    )
    if fs.exists('cost-management'):
        print("EXISTS")
    else:
        print("MISSING")
except Exception as e:
    print(f"ERROR: {e}")
EOF
)
    if [ "$BUCKET_CHECK" = "EXISTS" ]; then
        echo "  ✅ cost-management bucket exists"
    elif [ "$BUCKET_CHECK" = "MISSING" ]; then
        echo "  ⚠️  cost-management bucket not found (will be created)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "  ❌ Cannot connect to MinIO"
        echo "     $BUCKET_CHECK"
        FAILED=$((FAILED + 1))
    fi
fi

# Check 9: Disk space
echo ""
echo "✓ Check 9: Disk space"
AVAILABLE=$(df -h . | tail -1 | awk '{print $4}')
echo "  ℹ️  Available space: $AVAILABLE"
if df -h . | tail -1 | awk '{print $4}' | grep -qE "[0-9]+G"; then
    echo "  ✅ Sufficient disk space"
else
    echo "  ⚠️  Low disk space - benchmarks may fail"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 10: Config file
echo ""
echo "✓ Check 10: Configuration file"
if [ -f "config/config.yaml" ]; then
    echo "  ✅ config.yaml exists"

    # Check streaming setting
    STREAMING=$(grep "use_streaming:" config/config.yaml | awk '{print $2}')
    echo "     use_streaming: $STREAMING"

    if [ -f "config/config.yaml.bak" ]; then
        echo "  ⚠️  Backup config exists (previous run may have failed)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "  ❌ config.yaml not found"
    FAILED=$((FAILED + 1))
fi

# Summary
echo ""
echo "================================================================================"
echo "PREFLIGHT SUMMARY"
echo "================================================================================"

if [ $FAILED -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "✅ All checks passed - Ready for benchmarking!"
    echo ""
    exit 0
elif [ $FAILED -eq 0 ]; then
    echo "⚠️  Passed with $WARNINGS warning(s) - Proceed with caution"
    echo ""
    exit 0
else
    echo "❌ $FAILED critical check(s) failed"
    echo ""
    echo "Please fix the issues above before running benchmarks."
    echo ""
    exit 1
fi

