#!/bin/bash
# Run comprehensive empirical benchmarks at multiple scales

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${POC_DIR}/benchmark_results"

# Test scales
SCALES=(
    "1000:Small dataset (1K rows)"
    "10000:Medium dataset (10K rows)"
    "50000:Large dataset (50K rows)"
    "100000:Very large dataset (100K rows)"
)

echo "========================================================================"
echo "COMPREHENSIVE EMPIRICAL BENCHMARKING"
echo "========================================================================"
echo "Scales: ${#SCALES[@]}"
echo "Output: ${OUTPUT_DIR}"
echo ""

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Set environment variables
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="cost-management"
export POSTGRES_HOST="localhost"
export POSTGRES_PASSWORD="koku123"
export POSTGRES_SCHEMA="org1234567"
export ORG_ID="org1234567"
export OCP_CLUSTER_ID="benchmark-cluster"
export POC_YEAR="2025"
export POC_MONTH="10"

# Check local environment
echo "Checking local environment..."
if ! podman ps | grep -q postgres-cost-mgmt; then
    echo "Starting local environment..."
    "${SCRIPT_DIR}/start-local-env.sh"
    sleep 5
fi

# Results file
RESULTS_FILE="${OUTPUT_DIR}/comprehensive_benchmark_$(date +%Y%m%d_%H%M%S).md"

echo "# Comprehensive Empirical Benchmark Results" > "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Date**: $(date '+%Y-%m-%d %H:%M:%S')" >> "${RESULTS_FILE}"
echo "**Machine**: $(uname -m) $(uname -s)" >> "${RESULTS_FILE}"
echo "**Python**: $(python3 --version)" >> "${RESULTS_FILE}"
echo "**CPU**: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Unknown')" >> "${RESULTS_FILE}"
echo "**Memory**: $(sysctl -n hw.memsize 2>/dev/null | awk '{print $1/1024/1024/1024 " GB"}' || echo 'Unknown')" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "---" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"

PASSED=0
FAILED=0

for SCALE_INFO in "${SCALES[@]}"; do
    ROWS=$(echo $SCALE_INFO | cut -d: -f1)
    DESCRIPTION=$(echo $SCALE_INFO | cut -d: -f2)
    
    echo "========================================================================"
    echo "Benchmarking: ${DESCRIPTION}"
    echo "========================================================================"
    
    # Generate unique UUID for this test
    PROVIDER_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    export OCP_PROVIDER_UUID="${PROVIDER_UUID}"
    
    # Step 1: Generate synthetic data
    echo "Step 1: Generating ${ROWS} rows of synthetic data..."
    python3 "${SCRIPT_DIR}/generate_synthetic_data.py" \
        --rows ${ROWS} \
        --days 1 \
        --provider-uuid "${PROVIDER_UUID}" \
        --year "${POC_YEAR}" \
        --month "${POC_MONTH}" \
        --upload || {
        echo "❌ Failed to generate data for ${ROWS} rows"
        FAILED=$((FAILED + 1))
        continue
    }
    
    # Step 2: Initialize database (truncate)
    echo "Step 2: Initializing database..."
    python3 << EOF
import psycopg2
conn = psycopg2.connect(
    host='localhost',
    database='koku',
    user='koku',
    password='koku123'
)
cur = conn.cursor()
cur.execute("TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary")
conn.commit()
conn.close()
print("✓ Database truncated")
EOF
    
    # Step 3: Run benchmark
    echo "Step 3: Running benchmark..."
    BENCHMARK_OUTPUT="${OUTPUT_DIR}/benchmark_${ROWS}_rows_$(date +%Y%m%d_%H%M%S).json"
    
    python3 "${SCRIPT_DIR}/benchmark_performance.py" \
        --provider-uuid "${PROVIDER_UUID}" \
        --year "${POC_YEAR}" \
        --month "${POC_MONTH}" \
        --output "${BENCHMARK_OUTPUT}" 2>&1 | tee "${OUTPUT_DIR}/benchmark_${ROWS}_rows.log"
    
    if [ $? -eq 0 ] && [ -f "${BENCHMARK_OUTPUT}" ]; then
        echo "✅ Benchmark completed: ${ROWS} rows"
        PASSED=$((PASSED + 1))
        
        # Extract metrics and add to summary
        echo "## ${DESCRIPTION}" >> "${RESULTS_FILE}"
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

print(f"**Input rows**: {data['input_rows_daily']:,}")
print(f"**Output rows**: {data['output_rows']:,}")
print(f"**Compression**: {data['compression_ratio']:.1f}x")
print(f"**Duration**: {data['total_duration_seconds']:.2f}s")
print(f"**CPU time**: {data['total_cpu_seconds']:.2f}s")
print(f"**Peak memory**: {format_bytes(data['peak_memory_bytes'])}")
print(f"**Final memory**: {format_bytes(data['final_memory_bytes'])}")
print(f"**Memory per 1K input rows**: {format_bytes(data['memory_per_1k_input_rows_bytes'])}")
print(f"**Processing rate**: {data['rows_per_second']:,.0f} rows/sec")
print("")

# Phase breakdown
print("### Phase Breakdown")
print("")
print("| Phase | Duration | Memory Used | CPU Time |")
print("|-------|----------|-------------|----------|")
for phase in data['phases']:
    duration = f"{phase['duration_seconds']:.2f}s"
    mem_used = format_bytes(abs(phase['memory_used_bytes']))
    cpu = f"{phase['cpu_total_seconds']:.2f}s"
    print(f"| {phase['phase']} | {duration} | {mem_used} | {cpu} |")

print("")
EOF
        echo "---" >> "${RESULTS_FILE}"
        echo "" >> "${RESULTS_FILE}"
    else
        echo "❌ Benchmark failed: ${ROWS} rows"
        FAILED=$((FAILED + 1))
    fi
    
    echo ""
done

# Generate comparison table
echo "## Scaling Analysis" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "| Rows | Peak Memory | Memory/1K Rows | Duration | Rate (rows/sec) | CPU Time |" >> "${RESULTS_FILE}"
echo "|------|-------------|----------------|----------|-----------------|----------|" >> "${RESULTS_FILE}"

for SCALE_INFO in "${SCALES[@]}"; do
    ROWS=$(echo $SCALE_INFO | cut -d: -f1)
    JSON_FILE=$(ls -t "${OUTPUT_DIR}/benchmark_${ROWS}_rows_"*.json 2>/dev/null | head -1)
    
    if [ -f "${JSON_FILE}" ]; then
        python3 << EOF >> "${RESULTS_FILE}"
import json

with open('${JSON_FILE}', 'r') as f:
    data = json.load(f)

def format_bytes(b):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

rows = data['input_rows_daily']
peak_mem = format_bytes(data['peak_memory_bytes'])
mem_per_1k = format_bytes(data['memory_per_1k_input_rows_bytes'])
duration = f"{data['total_duration_seconds']:.2f}s"
rate = f"{data['rows_per_second']:,.0f}"
cpu = f"{data['total_cpu_seconds']:.2f}s"

print(f"| {rows:,} | {peak_mem} | {mem_per_1k} | {duration} | {rate} | {cpu} |")
EOF
    fi
done

echo "" >> "${RESULTS_FILE}"
echo "---" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"

# Summary
echo "## Summary" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Total scenarios**: ${#SCALES[@]}" >> "${RESULTS_FILE}"
echo "**Passed**: ${PASSED}" >> "${RESULTS_FILE}"
echo "**Failed**: ${FAILED}" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"

# Calculate average memory per 1K rows
AVG_MEM=$(python3 << EOF
import json
import glob

files = glob.glob('${OUTPUT_DIR}/benchmark_*_rows_*.json')
if files:
    total = 0
    count = 0
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                total += data['memory_per_1k_input_rows_bytes']
                count += 1
        except:
            pass
    if count > 0:
        avg = total / count
        print(f"{avg / 1024 / 1024:.1f} MB")
    else:
        print("N/A")
else:
    print("N/A")
EOF
)

echo "**Average memory per 1K rows**: ${AVG_MEM}" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "---" >> "${RESULTS_FILE}"
echo "" >> "${RESULTS_FILE}"
echo "**Generated**: $(date '+%Y-%m-%d %H:%M:%S')" >> "${RESULTS_FILE}"

# Final summary
echo "========================================================================"
echo "BENCHMARK SUMMARY"
echo "========================================================================"
echo "Passed: ${PASSED}/${#SCALES[@]}"
echo "Failed: ${FAILED}/${#SCALES[@]}"
echo ""
echo "Results saved to: ${RESULTS_FILE}"
echo "Individual benchmarks: ${OUTPUT_DIR}/benchmark_*_rows_*.json"
echo "========================================================================"

if [ ${FAILED} -eq 0 ]; then
    echo "✅ All benchmarks passed!"
    exit 0
else
    echo "⚠️  Some benchmarks failed"
    exit 1
fi

