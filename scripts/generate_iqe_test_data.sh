#!/bin/bash
# Generate nise data from IQE YAML configuration

set -e

# Configuration
IQE_PLUGIN_DIR="${IQE_PLUGIN_DIR:-../iqe-cost-management-plugin}"
IQE_YAML="${IQE_YAML:-ocp_report_advanced.yml}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/nise-iqe-data}"
CLUSTER_ID="${OCP_CLUSTER_ID:-iqe-test-cluster}"

echo "========================================"
echo "Generate IQE Test Data with Nise"
echo "========================================"
echo "IQE Plugin Dir: ${IQE_PLUGIN_DIR}"
echo "IQE YAML: ${IQE_YAML}"
echo "Output Dir: ${OUTPUT_DIR}"
echo "Cluster ID: ${CLUSTER_ID}"
echo "========================================"

# Step 1: Copy/Render IQE YAML to POC config directory
IQE_YAML_PATH="${IQE_PLUGIN_DIR}/iqe_cost_management/data/openshift/${IQE_YAML}"

if [ ! -f "${IQE_YAML_PATH}" ]; then
    echo "❌ IQE YAML not found: ${IQE_YAML_PATH}"
    echo "Available YAML files:"
    ls -1 "${IQE_PLUGIN_DIR}/iqe_cost_management/data/openshift/"*.yml 2>/dev/null || echo "  (none found)"
    exit 1
fi

echo "Step 1: Preparing IQE YAML..."
mkdir -p config

# Check if this is a template file (contains {{ }})
if grep -q "{{" "${IQE_YAML_PATH}"; then
    echo "  Detected template file, rendering with Jinja2..."
    python3 scripts/render_template.py "${IQE_YAML_PATH}" "config/${IQE_YAML}"
    echo "✓ Rendered template to config/${IQE_YAML}"
else
    cp "${IQE_YAML_PATH}" "config/${IQE_YAML}"
    echo "✓ Copied to config/${IQE_YAML}"
fi

# Step 2: Clean output directory
echo "Step 2: Cleaning output directory..."
rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
echo "✓ Output directory ready: ${OUTPUT_DIR}"

# Step 3: Generate data with nise
echo "Step 3: Generating data with nise..."

# Check if nise is available
if ! command -v nise &> /dev/null; then
    echo "❌ nise is not installed"
    echo "Install with: pip install koku-nise"
    exit 1
fi

# Generate data
nise report ocp \
    --static-report-file "config/${IQE_YAML}" \
    --ocp-cluster-id "${CLUSTER_ID}" \
    --insights-upload "${OUTPUT_DIR}" \
    --write-monthly

echo "✓ Nise data generated"

# Step 4: List generated files
echo "Step 4: Generated files:"
find "${OUTPUT_DIR}" -name "*.csv" -exec echo "  {}" \;

CSV_COUNT=$(find "${OUTPUT_DIR}" -name "*.csv" | wc -l | tr -d ' ')
echo "✓ Generated ${CSV_COUNT} CSV files"

echo "========================================"
echo "Next steps:"
echo "  1. Convert to Parquet: python3 scripts/csv_to_parquet_minio.py --csv-dir ${OUTPUT_DIR}"
echo "  2. Run POC: python3 -m src.main --truncate"
echo "  3. Validate: python3 scripts/validate_against_iqe.py"
echo "========================================"

