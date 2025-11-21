#!/bin/bash
#
# Simple benchmark script - one scale at a time
# Usage: ./simple_scale_benchmark.sh small streaming
#        ./simple_scale_benchmark.sh medium non-streaming
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

# Arguments
SCALE="${1:-medium}"
MODE="${2:-streaming}"

echo "================================================================================"
echo "Simple Benchmark: ${SCALE} - ${MODE}"
echo "================================================================================"

# Step 1: Generate data
echo "Step 1: Generating data..."
DATA_DIR="/tmp/benchmark-${SCALE}-${MODE}-$(date +%s)"
"${SCRIPT_DIR}/generate_nise_benchmark_data.sh" "${SCALE}" "${DATA_DIR}"

# Step 2: Get UUID from metadata
PROVIDER_UUID=$(grep -o '"provider_uuid": "[^"]*"' "${DATA_DIR}/metadata_${SCALE}.json" | cut -d'"' -f4)
echo "  Provider UUID: ${PROVIDER_UUID}"

# Step 3: Export ALL environment variables
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="cost-management"
export POSTGRES_HOST="localhost"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export POSTGRES_SCHEMA="org1234567"
export OCP_PROVIDER_UUID="${PROVIDER_UUID}"
export OCP_CLUSTER_ID="benchmark-${SCALE}"
export OCP_CLUSTER_ALIAS="Benchmark Cluster"
export OCP_YEAR="2025"
export OCP_MONTH="10"
export POC_YEAR="2025"
export POC_MONTH="10"
export ORG_ID="1234567"

# Step 4: Convert to Parquet
echo "Step 2: Converting to Parquet..."
python3 "${SCRIPT_DIR}/csv_to_parquet_minio.py" "${DATA_DIR}"

# Step 5: Configure streaming mode
echo "Step 3: Configuring ${MODE} mode..."
cd "${POC_DIR}"
source venv/bin/activate

if [ "${MODE}" = "streaming" ]; then
    STREAMING_VALUE="True"
else
    STREAMING_VALUE="False"
fi

# Backup config
cp config/config.yaml config/config.yaml.bak

# Update config
python3 << EOF
import yaml

with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

config['performance']['use_streaming'] = ${STREAMING_VALUE}

with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)

print("✓ Set use_streaming = ${STREAMING_VALUE}")
EOF

# Step 6: Clear database
echo "Step 4: Clearing database..."
psql -h localhost -U koku -d koku -c "TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;" > /dev/null 2>&1

# Step 7: Run with metrics
echo "Step 5: Running aggregation with metrics..."
OUTPUT_FILE="/tmp/benchmark_${SCALE}_${MODE}_$(date +%Y%m%d_%H%M%S).txt"

echo "=== Benchmark: ${SCALE} - ${MODE} ===" > "${OUTPUT_FILE}"
echo "Started: $(date)" >> "${OUTPUT_FILE}"
echo "" >> "${OUTPUT_FILE}"

# Run with time command
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    /usr/bin/time -l python3 -m src.main 2>&1 | tee -a "${OUTPUT_FILE}"
else
    # Linux
    /usr/bin/time -v python3 -m src.main 2>&1 | tee -a "${OUTPUT_FILE}"
fi

echo "" >> "${OUTPUT_FILE}"
echo "Completed: $(date)" >> "${OUTPUT_FILE}"

# Step 8: Get row counts
echo "Step 6: Collecting results..."
ROW_COUNT=$(psql -h localhost -U koku -d koku -t -c "SELECT COUNT(*) FROM org1234567.reporting_ocpusagelineitem_daily_summary;" 2>/dev/null | tr -d ' ')

# Step 9: Extract metrics
echo "" >> "${OUTPUT_FILE}"
echo "=== Summary ===" >> "${OUTPUT_FILE}"
echo "Scale: ${SCALE}" >> "${OUTPUT_FILE}"
echo "Mode: ${MODE}" >> "${OUTPUT_FILE}"
echo "Output rows: ${ROW_COUNT}" >> "${OUTPUT_FILE}"

# Step 10: Restore config
mv config/config.yaml.bak config/config.yaml

echo ""
echo "================================================================================"
echo "✅ Benchmark Complete"
echo "================================================================================"
echo "Results saved to: ${OUTPUT_FILE}"
echo ""
echo "Key metrics:"
cat "${OUTPUT_FILE}" | grep -E "(real|user|sys|maximum resident|Output rows)"
echo ""

# Return output file path
echo "${OUTPUT_FILE}"

