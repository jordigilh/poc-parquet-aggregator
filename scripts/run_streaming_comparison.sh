#!/bin/bash
# Compare streaming vs in-memory performance across multiple scales

# FAIL-FAST: Exit immediately on any error
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

cd "${POC_DIR}"

# Enable error tracing
trap 'echo "❌ ERROR on line $LINENO. Exit code: $?" >&2' ERR

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Parse arguments
SCALES=("$@")
if [ ${#SCALES[@]} -eq 0 ]; then
    echo "Usage: $0 <scale1> [scale2] [scale3] ..."
    echo ""
    echo "Available scales:"
    echo "  small             - ~1K rows, ~10 MB"
    echo "  medium            - ~10K rows, ~100 MB"
    echo "  large             - ~50K rows, ~500 MB"
    echo "  xlarge            - ~100K rows, ~1 GB"
    echo "  xxlarge           - ~250K rows, ~2.5 GB"
    echo "  production-small  - ~500K rows, ~5 GB"
    echo "  production-medium - ~1M rows, ~10 GB"
    echo ""
    echo "Example:"
    echo "  $0 small medium large"
    exit 1
fi

# Create results directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="benchmark_results/streaming_comparison_${TIMESTAMP}"
mkdir -p "${RESULTS_DIR}"

# Export environment variables
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

echo "================================================================================"
echo "STREAMING VS IN-MEMORY PERFORMANCE COMPARISON"
echo "================================================================================"
echo "Scales to test: ${SCALES[*]}"
echo "Results directory: ${RESULTS_DIR}"
echo "Timestamp: ${TIMESTAMP}"
echo ""

# Create summary file
SUMMARY_FILE="${RESULTS_DIR}/SUMMARY.csv"
echo "scale,mode,status,duration_seconds,peak_memory_mb,input_rows,output_rows,validation_status" > "${SUMMARY_FILE}"

for scale in "${SCALES[@]}"; do
    echo ""
    echo "================================================================================"
    echo "SCALE: ${scale}"
    echo "================================================================================"

    # Step 1: Generate test data
    echo ""
    echo "1️⃣  Generating nise data..."
    DATA_DIR="/tmp/nise-${scale}-${TIMESTAMP}"
    ./scripts/generate_nise_benchmark_data.sh "${scale}" "${DATA_DIR}"

    # Extract the generated cluster ID and provider UUID from JSON metadata
    METADATA_FILE="${DATA_DIR}/metadata_${scale}.json"

    if [ ! -f "${METADATA_FILE}" ]; then
        echo "❌ ERROR: Metadata file not found: ${METADATA_FILE}"
        echo "   Available files:"
        ls -la "${DATA_DIR}/"
        exit 1
    fi

    export OCP_CLUSTER_ID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['cluster_id'])")
    export OCP_PROVIDER_UUID=$(python3 -c "import json; print(json.load(open('${METADATA_FILE}'))['provider_uuid'])")

    # Step 2: Upload to MinIO
    echo ""
    echo "2️⃣  Uploading to MinIO..."
    python3 scripts/csv_to_parquet_minio.py "${DATA_DIR}"

    if [ -z "${OCP_CLUSTER_ID}" ] || [ -z "${OCP_PROVIDER_UUID}" ]; then
        echo "❌ ERROR: Failed to extract cluster ID or provider UUID from metadata"
        echo "   Metadata file: ${METADATA_FILE}"
        echo "   Cluster ID: '${OCP_CLUSTER_ID}'"
        echo "   Provider UUID: '${OCP_PROVIDER_UUID}'"
        cat "${METADATA_FILE}"
        exit 1
    fi

    echo "   Cluster ID: ${OCP_CLUSTER_ID}"
    echo "   Provider UUID: ${OCP_PROVIDER_UUID}"

    # CRITICAL: Set month and year to match nise-generated data
    # Nise generates data for "last_month" which is October (month=10)
    export POC_MONTH='10'
    export POC_YEAR='2025'

    echo "   Month: ${POC_MONTH}"
    echo "   Year: ${POC_YEAR}"

    # Step 3: Test IN-MEMORY mode
    echo ""
    echo "3️⃣  Testing IN-MEMORY mode..."
    echo "   Configuring..."

    # Configure for in-memory
    python3 -c "
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = False
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print('✓ In-memory mode configured')
"

    echo "   Running benchmark..."
    START_TIME=$(date +%s)

    # FAIL-FAST: Run without timeout wrapper to see actual errors
    if /usr/bin/time -l python3 -m src.main --truncate \
        > "${RESULTS_DIR}/${scale}_in-memory.log" 2>&1; then
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))

        # Extract metrics from log
        PEAK_MEM=$(grep "maximum resident set size" "${RESULTS_DIR}/${scale}_in-memory.log" | awk '{print $1/1024/1024}' || echo "0")
        INPUT_ROWS=$(grep "input_rows=" "${RESULTS_DIR}/${scale}_in-memory.log" | tail -1 | sed 's/.*input_rows=\([0-9]*\).*/\1/' || echo "0")
        OUTPUT_ROWS=$(grep "output_rows=" "${RESULTS_DIR}/${scale}_in-memory.log" | tail -1 | sed 's/.*output_rows=\([0-9]*\).*/\1/' || echo "0")

        echo "   ✅ POC completed (${DURATION}s, ${PEAK_MEM} MB peak)"

        # CORRECTNESS VALIDATION
        echo "   🔍 Validating correctness..."
        if python3 scripts/validate_benchmark_correctness.py "${DATA_DIR}" "${OCP_CLUSTER_ID}" "${POC_YEAR}" "${POC_MONTH}" \
            > "${RESULTS_DIR}/${scale}_in-memory_validation.log" 2>&1; then
            echo "   ✅ CORRECTNESS VALIDATED"
            VALIDATION_STATUS="PASS"
        else
            echo "   ❌ CORRECTNESS VALIDATION FAILED"
            echo "   Last 30 lines of validation log:"
            tail -30 "${RESULTS_DIR}/${scale}_in-memory_validation.log"
            echo ""
            echo "❌ FAIL-FAST: Aggregation produced incorrect results"
            echo "   Full validation log: ${RESULTS_DIR}/${scale}_in-memory_validation.log"
            exit 1
        fi

        echo "${scale},in-memory,SUCCESS,${DURATION},${PEAK_MEM},${INPUT_ROWS},${OUTPUT_ROWS},${VALIDATION_STATUS}" >> "${SUMMARY_FILE}"

        echo "   ✅ COMPLETE (functional + correctness validated)"
    else
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))
        EXIT_CODE=$?

        echo "   ❌ FAILED with exit code ${EXIT_CODE}"
        echo "   Last 20 lines of log:"
        tail -20 "${RESULTS_DIR}/${scale}_in-memory.log"
        echo ""
        echo "❌ FAIL-FAST: Stopping benchmark run due to error in ${scale} in-memory mode"
        echo "   Full log: ${RESULTS_DIR}/${scale}_in-memory.log"
        exit 1
    fi

    # Step 4: Test STREAMING mode
    echo ""
    echo "4️⃣  Testing STREAMING mode..."
    echo "   Configuring..."

    # Configure for streaming
    python3 -c "
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = True
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print('✓ Streaming mode configured')
"

    echo "   Running benchmark..."
    START_TIME=$(date +%s)

    # FAIL-FAST: Run without timeout wrapper to see actual errors
    if /usr/bin/time -l python3 -m src.main --truncate \
        > "${RESULTS_DIR}/${scale}_streaming.log" 2>&1; then
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))

        # Extract metrics from log
        PEAK_MEM=$(grep "maximum resident set size" "${RESULTS_DIR}/${scale}_streaming.log" | awk '{print $1/1024/1024}' || echo "0")
        INPUT_ROWS=$(grep "Loaded.*rows" "${RESULTS_DIR}/${scale}_streaming.log" | head -1 | grep -o '[0-9,]*' | tr -d ',' || echo "0")
        OUTPUT_ROWS=$(grep "Generated.*summary rows" "${RESULTS_DIR}/${scale}_streaming.log" | grep -o '[0-9,]*' | tr -d ',' || echo "0")

        echo "   ✅ POC completed (${DURATION}s, ${PEAK_MEM} MB peak)"

        # CORRECTNESS VALIDATION
        echo "   🔍 Validating correctness..."
        if python3 scripts/validate_benchmark_correctness.py "${DATA_DIR}" "${OCP_CLUSTER_ID}" "${POC_YEAR}" "${POC_MONTH}" \
            > "${RESULTS_DIR}/${scale}_streaming_validation.log" 2>&1; then
            echo "   ✅ CORRECTNESS VALIDATED"
            VALIDATION_STATUS="PASS"
        else
            echo "   ❌ CORRECTNESS VALIDATION FAILED"
            echo "   Last 30 lines of validation log:"
            tail -30 "${RESULTS_DIR}/${scale}_streaming_validation.log"
            echo ""
            echo "❌ FAIL-FAST: Aggregation produced incorrect results"
            echo "   Full validation log: ${RESULTS_DIR}/${scale}_streaming_validation.log"
            exit 1
        fi

        echo "${scale},streaming,SUCCESS,${DURATION},${PEAK_MEM},${INPUT_ROWS},${OUTPUT_ROWS},${VALIDATION_STATUS}" >> "${SUMMARY_FILE}"

        echo "   ✅ COMPLETE (functional + correctness validated)"
    else
        END_TIME=$(date +%s)
        DURATION=$((END_TIME - START_TIME))
        EXIT_CODE=$?

        echo "   ❌ FAILED with exit code ${EXIT_CODE}"
        echo "   Last 20 lines of log:"
        tail -20 "${RESULTS_DIR}/${scale}_streaming.log"
        echo ""
        echo "❌ FAIL-FAST: Stopping benchmark run due to error in ${scale} streaming mode"
        echo "   Full log: ${RESULTS_DIR}/${scale}_streaming.log"
        exit 1
    fi

    echo ""
    echo "✅ Completed: ${scale}"

    # Cleanup temp data
    rm -rf "${DATA_DIR}"
done

# Generate comparison report
echo ""
echo "================================================================================"
echo "GENERATING COMPARISON REPORT"
echo "================================================================================"

python3 - "${SUMMARY_FILE}" "$(date)" << 'EOFPYTHON'
import csv
import sys

if len(sys.argv) < 3:
    print("Error: Missing arguments")
    sys.exit(1)

summary_file = sys.argv[1]
timestamp = sys.argv[2]

# Read summary
results = []
try:
    with open(summary_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(row)
except Exception as e:
    print(f"Error reading summary file: {e}")
    sys.exit(1)

# Generate markdown report
report_file = summary_file.replace('SUMMARY.csv', 'COMPARISON_REPORT.md')
with open(report_file, 'w') as f:
    f.write('# Streaming vs In-Memory Performance Comparison\n\n')
    f.write(f'**Generated**: {timestamp}\n\n')
    f.write('---\n\n')
    f.write('## Results Summary\n\n')
    f.write('| Scale | Mode | Status | Duration | Peak Memory | Input Rows | Output Rows | Speedup |\n')
    f.write('|-------|------|--------|----------|-------------|------------|-------------|----------|\n')

    # Group by scale
    scales = {}
    for r in results:
        scale = r['scale']
        if scale not in scales:
            scales[scale] = {}
        scales[scale][r['mode']] = r

    for scale, modes in scales.items():
        in_mem = modes.get('in-memory', {})
        stream = modes.get('streaming', {})

        # In-memory row
        speedup = '-'
        if in_mem:
            f.write(f"| {scale} | in-memory | {in_mem.get('status', 'N/A')} | {in_mem.get('duration_seconds', '0')}s | {in_mem.get('peak_memory_mb', '0')} MB | {in_mem.get('input_rows', '0')} | {in_mem.get('output_rows', '0')} | baseline |\n")

        # Streaming row with speedup
        if stream and in_mem:
            try:
                in_time = float(in_mem.get('duration_seconds', 0))
                st_time = float(stream.get('duration_seconds', 0))
                if st_time > 0 and in_time > 0:
                    speedup = f"{in_time/st_time:.2f}x"
            except:
                pass

        if stream:
            f.write(f"| {scale} | streaming | {stream.get('status', 'N/A')} | {stream.get('duration_seconds', '0')}s | {stream.get('peak_memory_mb', '0')} MB | {stream.get('input_rows', '0')} | {stream.get('output_rows', '0')} | {speedup} |\n")

    f.write('\n---\n\n')
    f.write('## Analysis\n\n')
    f.write('### Key Findings\n\n')

    # Calculate crossover point
    crossover_found = False
    for scale, modes in scales.items():
        in_mem = modes.get('in-memory', {})
        stream = modes.get('streaming', {})

        if in_mem.get('status') == 'SUCCESS' and stream.get('status') == 'SUCCESS':
            try:
                in_time = float(in_mem['duration_seconds'])
                st_time = float(stream['duration_seconds'])
                in_mem_mb = float(in_mem['peak_memory_mb'])
                st_mem_mb = float(stream['peak_memory_mb'])

                if st_time < in_time or in_mem.get('status') == 'FAILED':
                    f.write(f"- **{scale}**: Streaming wins (time: {st_time}s vs {in_time}s, memory: {st_mem_mb} MB vs {in_mem_mb} MB)\n")
                    crossover_found = True
                elif in_time < st_time * 1.2:  # Within 20%
                    f.write(f"- **{scale}**: Competitive (streaming: {st_time}s @ {st_mem_mb} MB, in-memory: {in_time}s @ {in_mem_mb} MB)\n")
                else:
                    f.write(f"- **{scale}**: In-memory faster ({in_time}s vs {st_time}s)\n")
            except:
                pass

    f.write('\n### Recommendation\n\n')
    if crossover_found:
        f.write('Based on these results, **enable streaming mode** for datasets above the crossover point.\n\n')
    else:
        f.write('For all tested scales, **in-memory mode is optimal** for speed. Enable streaming only when memory is constrained.\n\n')

    f.write('### Memory vs Speed Trade-off\n\n')
    f.write('- **In-memory**: Faster but requires memory proportional to data size\n')
    f.write('- **Streaming**: Constant memory (~20-50 MB) but 10-20% slower due to chunking overhead\n\n')

    print(f'✅ Report generated: {report_file}')

EOFPYTHON

echo ""
echo "================================================================================"
echo "✅ ALL BENCHMARKS COMPLETE"
echo "================================================================================"
echo "Results: ${RESULTS_DIR}"
echo "Summary: ${RESULTS_DIR}/SUMMARY.csv"
echo "Report: ${RESULTS_DIR}/COMPARISON_REPORT.md"
echo ""
cat "${SUMMARY_FILE}"
echo ""
echo "View full report: cat ${RESULTS_DIR}/COMPARISON_REPORT.md"

