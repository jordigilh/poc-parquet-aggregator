#!/bin/bash
#
# Simple benchmark script with all environment variables set correctly
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

cd "$POC_DIR"
source venv/bin/activate

# Export ALL required environment variables
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="cost-management"

export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku123"
export POSTGRES_SCHEMA="org1234567"

export OCP_CLUSTER_ID="test-ocp-cluster"
export OCP_PROVIDER_UUID="99ea2209-6f66-4621-983f-9e811a72d350"
export OCP_YEAR="2025"
export OCP_MONTH="10"
export ORG_ID="1234567"

# Get mode from argument (streaming or non-streaming)
MODE="${1:-non-streaming}"

if [ "$MODE" == "streaming" ]; then
    STREAMING_BOOL="True"  # Python boolean
else
    STREAMING_BOOL="False"  # Python boolean
fi

echo "================================================================================"
echo "BENCHMARK: $MODE Mode"
echo "================================================================================"
echo "Provider UUID: $OCP_PROVIDER_UUID"
echo "Year/Month: $OCP_YEAR/$OCP_MONTH"
echo "Streaming: $STREAMING_BOOL"
echo ""

# Configure streaming mode
python3 << EOF
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = $STREAMING_BOOL
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print("✓ Configured use_streaming = $STREAMING_BOOL")
EOF

# Clear database
echo "Clearing database..."
podman exec postgres-poc psql -U koku -d koku -c "TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;" > /dev/null
echo "✓ Database cleared"
echo ""

# Run with metrics
echo "Starting aggregation at: $(date '+%H:%M:%S')"
echo ""

OUTPUT_FILE="/tmp/benchmark_${MODE}.txt"
/usr/bin/time -l python3 -m src.main 2>&1 | tee "$OUTPUT_FILE"

echo ""
echo "Completed at: $(date '+%H:%M:%S')"
echo ""
echo "================================================================================"
echo "METRICS SUMMARY"
echo "================================================================================"
grep -E "(real|user|sys|maximum resident)" "$OUTPUT_FILE" | tail -4
echo "================================================================================"
echo ""
echo "Full output saved to: $OUTPUT_FILE"

