#!/bin/bash
#
# Development Environment Setup Script
#
# This script sets up a complete development environment for the POC.
# Run this once after cloning the repository.
#
# Usage:
#   ./scripts/setup_dev_environment.sh
#

set -e  # Exit on error

POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$POC_DIR"

echo "================================================================================"
echo "=== OCP Parquet Aggregator POC - Development Environment Setup ==="
echo "================================================================================"
echo ""

# Step 1: Check Python version
echo "Step 1: Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

echo "  Found: Python $PYTHON_VERSION"

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo "  ❌ ERROR: Python 3.9+ required"
    exit 1
fi
echo "  ✅ Python version OK"
echo ""

# Step 2: Create virtual environment
echo "Step 2: Creating virtual environment..."
if [ -L "venv" ] || [ -d "venv" ]; then
    echo "  ⚠️  venv already exists, removing..."
    rm -rf venv
fi

python3 -m venv venv
echo "  ✅ Virtual environment created"
echo ""

# Step 3: Upgrade pip
echo "Step 3: Upgrading pip..."
./venv/bin/pip install --upgrade pip --quiet
echo "  ✅ pip upgraded"
echo ""

# Step 4: Install dependencies
echo "Step 4: Installing dependencies..."
echo "  This may take a few minutes..."
./venv/bin/pip install -r requirements.txt --quiet
if [ $? -eq 0 ]; then
    echo "  ✅ All dependencies installed"
else
    echo "  ❌ ERROR: Failed to install dependencies"
    exit 1
fi
echo ""

# Step 5: Validate environment
echo "Step 5: Validating environment..."
./venv/bin/python3 scripts/validate_environment.py
VALIDATION_EXIT=$?

if [ $VALIDATION_EXIT -eq 0 ]; then
    echo ""
    echo "================================================================================"
    echo "=== Setup Complete! ==="
    echo "================================================================================"
    echo ""
    echo "✅ Virtual environment created at: ./venv"
    echo "✅ All dependencies installed and validated"
    echo ""
    echo "Next steps:"
    echo ""
    echo "  1. Activate the virtual environment:"
    echo "       source venv/bin/activate"
    echo ""
    echo "  2. Configure environment variables:"
    echo "       cp env.example .env"
    echo "       # Edit .env with your settings"
    echo ""
    echo "  3. Start required services (MinIO, PostgreSQL):"
    echo "       # See README.md for instructions"
    echo ""
    echo "  4. Run the POC:"
    echo "       python3 -m src.main"
    echo ""
    echo "  5. Run tests:"
    echo "       pytest"
    echo ""
    echo "  6. Run Trino validation:"
    echo "       python3 scripts/validate_against_trino.py <cluster_id> <provider_uuid> <year> <month>"
    echo ""
    echo "================================================================================"
    echo ""
    echo "🎉 Happy coding!"
    echo ""
    exit 0
else
    echo ""
    echo "================================================================================"
    echo "=== Setup Failed ==="
    echo "================================================================================"
    echo ""
    echo "❌ Environment validation failed"
    echo ""
    echo "Please check the errors above and try:"
    echo "  ./venv/bin/pip install -r requirements.txt"
    echo ""
    exit 1
fi

