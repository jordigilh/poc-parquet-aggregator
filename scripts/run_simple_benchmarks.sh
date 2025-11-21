#!/bin/bash
#
# Run simple benchmarks for multiple scales
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="/tmp/benchmark_results_${TIMESTAMP}"

mkdir -p "${RESULTS_DIR}"

# Scales to test
SCALES="${SCALES:-small medium large}"

echo "================================================================================"
echo "Running Simple Benchmarks"
echo "================================================================================"
echo "Scales: ${SCALES}"
echo "Modes: non-streaming, streaming"
echo "Results: ${RESULTS_DIR}"
echo ""

# Create summary file
SUMMARY="${RESULTS_DIR}/SUMMARY.md"
cat > "${SUMMARY}" << 'EOF'
# Benchmark Results

**Date**: $(date)

## Results by Scale

EOF

for SCALE in ${SCALES}; do
    echo ""
    echo "================================================================================"
    echo "SCALE: ${SCALE}"
    echo "================================================================================"

    # Test non-streaming
    echo "Testing non-streaming..."
    OUTPUT_NS=$("${SCRIPT_DIR}/simple_scale_benchmark.sh" "${SCALE}" "non-streaming" 2>&1 | tail -1)
    cp "${OUTPUT_NS}" "${RESULTS_DIR}/${SCALE}_non-streaming.txt" 2>/dev/null || true

    # Test streaming
    echo "Testing streaming..."
    OUTPUT_S=$("${SCRIPT_DIR}/simple_scale_benchmark.sh" "${SCALE}" "streaming" 2>&1 | tail -1)
    cp "${OUTPUT_S}" "${RESULTS_DIR}/${SCALE}_streaming.txt" 2>/dev/null || true

    # Add to summary
    echo "" >> "${SUMMARY}"
    echo "### ${SCALE}" >> "${SUMMARY}"
    echo "" >> "${SUMMARY}"
    echo "#### Non-Streaming" >> "${SUMMARY}"
    echo '```' >> "${SUMMARY}"
    grep -E "(real|user|maximum resident|Output rows)" "${RESULTS_DIR}/${SCALE}_non-streaming.txt" >> "${SUMMARY}" 2>/dev/null || echo "No results" >> "${SUMMARY}"
    echo '```' >> "${SUMMARY}"
    echo "" >> "${SUMMARY}"
    echo "#### Streaming" >> "${SUMMARY}"
    echo '```' >> "${SUMMARY}"
    grep -E "(real|user|maximum resident|Output rows)" "${RESULTS_DIR}/${SCALE}_streaming.txt" >> "${SUMMARY}" 2>/dev/null || echo "No results" >> "${SUMMARY}"
    echo '```' >> "${SUMMARY}"
    echo "" >> "${SUMMARY}"
done

echo ""
echo "================================================================================"
echo "All Benchmarks Complete"
echo "================================================================================"
echo "Results directory: ${RESULTS_DIR}"
echo "Summary: ${SUMMARY}"
echo ""
cat "${SUMMARY}"

