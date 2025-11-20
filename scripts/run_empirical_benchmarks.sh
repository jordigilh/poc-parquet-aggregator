#!/bin/bash
# Run empirical performance benchmarks against IQE test scenarios

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"
IQE_PLUGIN_DIR="${IQE_PLUGIN_DIR:-../../iqe-cost-management-plugin}"
OUTPUT_DIR="${POC_DIR}/benchmark_results"

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Test scenarios to benchmark
SCENARIOS=(
    "ocp_report_1.yml"           # Small dataset
    "ocp_report_ros_0.yml"       # Medium dataset
    "ocp_report_0_template.yml"  # Large dataset
)

echo "========================================================================"
echo "EMPIRICAL PERFORMANCE BENCHMARKING"
echo "========================================================================"
echo "Output directory: ${OUTPUT_DIR}"
echo "Scenarios: ${#SCENARIOS[@]}"
echo ""

# Activate virtual environment
if [ -d "${POC_DIR}/venv" ]; then
    source "${POC_DIR}/venv/bin/activate"
fi

# Start local environment if not running
echo "Checking local environment..."
if ! podman ps | grep -q postgres-cost-mgmt; then
    echo "Starting local environment..."
    "${SCRIPT_DIR}/start-local-env.sh"
    sleep 5
fi

# Install psutil if not present
pip install -q psutil 2>/dev/null || true

PASSED=0
FAILED=0
RESULTS_FILE="${OUTPUT_DIR}/benchmark_summary_$(date +%Y%m%d_%H%M%S).md"

echo "# Empirical Performance Benchmark Results" > "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Date**: $(date '+%Y-%m-%d %H:%M:%S')" >> "${RESULTS_FILE}"
echo "**Machine**: $(uname -m) $(uname -s)" >> "${RESULTS_FILE}"
echo "**Python**: $(python3 --version)" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "---" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"

for IQE_YAML in "${SCENARIOS[@]}"; do
    echo "========================================================================"
    echo "Benchmarking: ${IQE_YAML}"
    echo "========================================================================"

    # Generate unique UUID for this test
    export OCP_PROVIDER_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    export CLUSTER_ID="iqe-test-cluster"

    # Step 1: Generate nise data
    echo "Step 1: Generating nise data..."
    "${SCRIPT_DIR}/generate_iqe_test_data.sh" "${IQE_YAML}" || {
        echo "❌ Failed to generate nise data for ${IQE_YAML}"
        FAILED=$((FAILED + 1))
        continue
    }

    # Step 2: Convert to Parquet and upload to MinIO
    echo "Step 2: Converting to Parquet..."
    python3 "${SCRIPT_DIR}/csv_to_parquet_minio.py" "/tmp/nise-iqe-data" || {
        echo "❌ Failed to convert to Parquet for ${IQE_YAML}"
        FAILED=$((FAILED + 1))
        continue
    }

    # Step 3: Detect which months have data
    echo "Step 3: Detecting data months..."
    MONTHS_TO_PROCESS=$(python3 -c "
import s3fs
import os
provider_uuid = os.getenv('OCP_PROVIDER_UUID', '')
try:
    fs = s3fs.S3FileSystem(key='minioadmin', secret='minioadmin', client_kwargs={'endpoint_url': 'http://localhost:9000'})
    months_with_data = []
    for month in range(1, 13):
        month_str = f'{month:02d}'
        files = fs.glob(f'cost-management/data/*/OCP/source={provider_uuid}/year=2025/month={month_str}/**/*.parquet')
        if len(files) > 0:
            months_with_data.append(month_str)

    if months_with_data:
        print(months_with_data[0])  # Use first month for benchmark
    else:
        print('11')
except Exception as e:
    print('11')
" 2>&1)

    export POC_YEAR=2025
    export POC_MONTH=${MONTHS_TO_PROCESS}

    echo "  Provider UUID: ${OCP_PROVIDER_UUID}"
    echo "  Year/Month: ${POC_YEAR}-${POC_MONTH}"

    # Step 4: Run benchmark
    echo "Step 4: Running benchmark..."
    BENCHMARK_OUTPUT="${OUTPUT_DIR}/benchmark_${IQE_YAML%.yml}_$(date +%Y%m%d_%H%M%S).json"

    python3 "${SCRIPT_DIR}/benchmark_performance.py" \
        --provider-uuid "${OCP_PROVIDER_UUID}" \
        --year "${POC_YEAR}" \
        --month "${POC_MONTH}" \
        --output "${BENCHMARK_OUTPUT}" 2>&1 | tee "${OUTPUT_DIR}/benchmark_${IQE_YAML%.yml}.log"

    if [ $? -eq 0 ]; then
        echo "✅ Benchmark completed: ${IQE_YAML}"
        PASSED=$((PASSED + 1))

        # Extract key metrics and add to summary
        echo "## ${IQE_YAML}" >> "${RESULTS_FILE}"
        echo "" >> "${RESULTS_FILE}"
        python3 << EOF >> "${RESULTS_FILE}"
import json
with open('${BENCHMARK_OUTPUT}', 'r') as f:
    data = json.load(f)

def format_bytes(b):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

print(f"**Input rows (daily)**: {data['input_rows_daily']:,}")
print(f"**Output rows**: {data['output_rows']:,}")
print(f"**Compression**: {data['compression_ratio']:.1f}x")
print(f"**Duration**: {data['total_duration_seconds']:.2f}s")
print(f"**CPU time**: {data['total_cpu_seconds']:.2f}s")
print(f"**Peak memory**: {format_bytes(data['peak_memory_bytes'])}")
print(f"**Memory per 1K input rows**: {format_bytes(data['memory_per_1k_input_rows_bytes'])}")
print(f"**Processing rate**: {data['rows_per_second']:,.0f} rows/sec")
print("")
EOF
        echo "---" >> "${RESULTS_FILE}"
        echo "" >> "${RESULTS_FILE}"
    else
        echo "❌ Benchmark failed: ${IQE_YAML}"
        FAILED=$((FAILED + 1))
    fi

    echo ""
done

# Summary
echo "========================================================================"
echo "BENCHMARK SUMMARY"
echo "========================================================================"
echo "Passed: ${PASSED}/${#SCENARIOS[@]}"
echo "Failed: ${FAILED}/${#SCENARIOS[@]}"
echo ""
echo "Results saved to: ${RESULTS_FILE}"
echo "Individual benchmarks: ${OUTPUT_DIR}/benchmark_*.json"
echo "========================================================================"

# Add summary to results file
echo "## Summary" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Total scenarios**: ${#SCENARIOS[@]}" >> "${RESULTS_FILE}"
echo "**Passed**: ${PASSED}" >> "${RESULTS_FILE}"
echo "**Failed**: ${FAILED}" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "---" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Generated**: $(date '+%Y-%m-%d %H:%M:%S')" >> "${RESULTS_FILE}"

if [ ${FAILED} -eq 0 ]; then
    echo "✅ All benchmarks passed!"
    exit 0
else
    echo "⚠️  Some benchmarks failed"
    exit 1
fi

