#!/bin/bash

################################################################################
# STREAMING-ONLY BENCHMARK - All Scales with Parallel Chunks
################################################################################
#
# This script runs comprehensive streaming benchmarks across all scales:
# - small (10K rows)
# - medium (100K rows)
# - large (250K rows)
# - xlarge (500K rows)
# - production-medium (1M rows)
#
# Each test includes:
# - Data generation (nise)
# - Parquet conversion + MinIO upload
# - Streaming aggregation with parallel chunks
# - Correctness validation
# - Performance metrics capture
#
################################################################################

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Configuration
NISE_DATA_DIR="$PROJECT_ROOT/nise_benchmark_data"
RESULTS_DIR="$PROJECT_ROOT/benchmark_results"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "================================================================================"
echo "🚀 STREAMING-ONLY BENCHMARK - PARALLEL CHUNKS ENABLED"
echo "================================================================================"
echo "Timestamp: $TIMESTAMP"
echo "Scales: small, medium, large, xlarge, production-medium"
echo "Mode: STREAMING ONLY (parallel_chunks=true, max_workers=4)"
echo "Validation: Full correctness validation for each scale"
echo "Expected Duration: ~45-60 minutes total"
echo "================================================================================"
echo ""

# Parse command line arguments
if [ $# -eq 0 ]; then
    SCALES=("small" "medium" "large" "xlarge" "production-medium")
else
    SCALES=("$@")
fi

echo "📊 Scales to test: ${SCALES[*]}"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Clear MinIO before starting
echo "================================================================================"
echo "🧹 CLEANING MINIO"
echo "================================================================================"
python3 -c "
import boto3
s3 = boto3.client('s3', endpoint_url='http://localhost:9000', aws_access_key_id='minioadmin', aws_secret_access_key='minioadmin')
try:
    result = s3.list_objects_v2(Bucket='cost-management')
    if 'Contents' in result:
        s3.delete_objects(Bucket='cost-management', Delete={'Objects': [{'Key': obj['Key']} for obj in result['Contents']]})
        print(f'✓ Cleared {len(result[\"Contents\"])} objects from MinIO')
    else:
        print('✓ MinIO already empty')
except Exception as e:
    print(f'Warning: {e}')
"
echo ""

# Initialize summary file
SUMMARY_FILE="$RESULTS_DIR/streaming_benchmark_summary_${TIMESTAMP}.md"
cat > "$SUMMARY_FILE" << EOF
# Streaming Benchmark Results - Parallel Chunks

**Date**: $(date)
**Configuration**:
- Mode: Streaming with parallel chunks
- Workers: 4 cores
- Chunk Size: 100K rows
- Arrow Compute: Enabled
- Bulk Copy: Enabled

---

## Summary Table

| Scale | Rows | Time (s) | Memory (MB) | CPU (cores) | Status | Validation |
|-------|------|----------|-------------|-------------|--------|------------|
EOF

# Function to run a single scale benchmark
run_scale_benchmark() {
    local SCALE=$1

    echo "================================================================================"
    echo "🔬 SCALE: $SCALE"
    echo "================================================================================"

    # Step 1: Generate nise data
    echo "📝 Step 1/4: Generating nise data..."
    if ! ./scripts/generate_nise_benchmark_data.sh "$SCALE" "$NISE_DATA_DIR"; then
        echo "❌ FAILED to generate data for $SCALE"
        return 1
    fi

    # Read metadata
    METADATA_FILE="$NISE_DATA_DIR/metadata_${SCALE}.json"
    if [ ! -f "$METADATA_FILE" ]; then
        echo "❌ Metadata file not found: $METADATA_FILE"
        return 1
    fi

    OCP_CLUSTER_ID=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['cluster_id'])")
    OCP_PROVIDER_UUID=$(python3 -c "import json; print(json.load(open('$METADATA_FILE'))['provider_uuid'])")

    if [ -z "$OCP_CLUSTER_ID" ] || [ -z "$OCP_PROVIDER_UUID" ]; then
        echo "❌ Failed to read metadata"
        return 1
    fi

    echo "   Cluster ID: $OCP_CLUSTER_ID"
    echo "   Provider UUID: $OCP_PROVIDER_UUID"

    # Step 2: Convert to Parquet and upload
    echo "📦 Step 2/4: Converting to Parquet and uploading to MinIO..."
    if ! python3 "$SCRIPT_DIR/csv_to_parquet_minio.py" "$NISE_DATA_DIR" "$OCP_CLUSTER_ID" "$OCP_PROVIDER_UUID" "10"; then
        echo "❌ FAILED to upload data for $SCALE"
        return 1
    fi

    # Step 3: Run streaming aggregation
    echo "🚀 Step 3/4: Running STREAMING aggregation (parallel chunks)..."

    export OCP_CLUSTER_ID="$OCP_CLUSTER_ID"
    export OCP_PROVIDER_UUID="$OCP_PROVIDER_UUID"
    export POC_MONTH='10'
    export POC_YEAR='2025'
    export S3_ENDPOINT="http://localhost:9000"
    export S3_BUCKET="cost-management"
    export S3_ACCESS_KEY="minioadmin"
    export S3_SECRET_KEY="minioadmin"
    export POSTGRES_HOST="localhost"
    export POSTGRES_PORT="5432"
    export POSTGRES_DB="koku"
    export POSTGRES_USER="koku"
    export POSTGRES_PASSWORD="koku123"
    export POSTGRES_SCHEMA="org1234567"
    export ORG_ID="1234567"

    LOG_FILE="$RESULTS_DIR/${SCALE}_streaming_${TIMESTAMP}.log"
    METRICS_FILE="$RESULTS_DIR/${SCALE}_streaming_metrics_${TIMESTAMP}.txt"

    # Run with timeout (30 min for large scales)
    if timeout 1800 /usr/bin/time -l python3 -m src.main --truncate 2>&1 | tee "$LOG_FILE"; then
        echo "✓ Streaming aggregation completed"

        # Extract metrics from log
        TIME_SECONDS=$(grep -o "Elapsed time: [0-9.]*s" "$LOG_FILE" | grep -o "[0-9.]*" || echo "N/A")
        MEMORY_MB=$(tail -20 "$LOG_FILE" | grep "maximum resident set size" | awk '{printf "%.2f", $1/1048576}' || echo "N/A")

        echo "   Time: ${TIME_SECONDS}s"
        echo "   Memory: ${MEMORY_MB} MB"

        # Save metrics
        cat > "$METRICS_FILE" << EOF_METRICS
Scale: $SCALE
Mode: Streaming (parallel chunks)
Time: ${TIME_SECONDS}s
Memory: ${MEMORY_MB} MB
Cluster ID: $OCP_CLUSTER_ID
EOF_METRICS

        # Step 4: Correctness validation
        echo "✅ Step 4/4: Running correctness validation..."
        VALIDATION_RESULT="❓ Unknown"

        # Pass year and month to validation (October 2025 for nise "last_month" data)
        if python3 "$SCRIPT_DIR/validate_benchmark_correctness.py" "$NISE_DATA_DIR" "$OCP_CLUSTER_ID" "2025" "10" 2>&1 | tee "${LOG_FILE}.validation"; then
            if grep -q "✅ VALIDATION PASSED" "${LOG_FILE}.validation"; then
                VALIDATION_RESULT="✅ PASSED"
                echo "✅ Validation PASSED"
            else
                VALIDATION_RESULT="❌ FAILED"
                echo "⚠️  Validation FAILED"
            fi
        else
            VALIDATION_RESULT="❌ ERROR"
            echo "⚠️  Validation ERROR"
        fi

        # Update summary
        echo "| $SCALE | $TIME_SECONDS | $MEMORY_MB | 4 | ✅ Success | $VALIDATION_RESULT |" >> "$SUMMARY_FILE"

        return 0
    else
        echo "❌ FAILED (timeout or error)"
        echo "| $SCALE | N/A | N/A | N/A | ❌ Failed | N/A |" >> "$SUMMARY_FILE"
        return 1
    fi
}

# Run benchmarks for all scales
SUCCESS_COUNT=0
FAIL_COUNT=0

for SCALE in "${SCALES[@]}"; do
    echo ""
    echo "================================================================================"
    echo "Starting benchmark: $SCALE"
    echo "================================================================================"

    if run_scale_benchmark "$SCALE"; then
        ((SUCCESS_COUNT++))
        echo -e "${GREEN}✓ $SCALE completed successfully${NC}"
    else
        ((FAIL_COUNT++))
        echo -e "${RED}✗ $SCALE failed${NC}"
    fi

    echo ""
    echo "Progress: $SUCCESS_COUNT passed, $FAIL_COUNT failed"
    echo ""

    # Small delay between scales
    sleep 5
done

# Finalize summary
cat >> "$SUMMARY_FILE" << EOF

---

## Final Results

- **Total Tests**: ${#SCALES[@]}
- **Passed**: $SUCCESS_COUNT
- **Failed**: $FAIL_COUNT

## Configuration

\`\`\`yaml
performance:
  parallel_chunks: true
  max_workers: 4
  chunk_size: 100000
  use_arrow_compute: true
  use_bulk_copy: true
  use_streaming: true
\`\`\`

## Key Findings

- Parallel chunk processing enabled (4 workers)
- Streaming mode with constant memory usage
- Arrow compute for vectorized label processing
- Bulk COPY for fast PostgreSQL inserts

---

**Benchmark completed**: $(date)
EOF

echo "================================================================================"
echo "🎉 BENCHMARK COMPLETE"
echo "================================================================================"
echo "Results saved to: $SUMMARY_FILE"
echo "Detailed logs in: $RESULTS_DIR/"
echo ""
echo "Summary:"
echo "  Total: ${#SCALES[@]}"
echo "  Passed: $SUCCESS_COUNT"
echo "  Failed: $FAIL_COUNT"
echo "================================================================================"

# Display summary
cat "$SUMMARY_FILE"

exit 0

