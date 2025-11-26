#!/bin/bash
# Benchmark Suite: Fill Missing Performance Data
#
# This script runs benchmarks for:
# 1. IN-MEMORY scalability (22K, 100K, 250K, 500K rows)
# 2. Core scaling (8, 11 cores with parallel streaming)
#
# Results are used for capacity planning and production sizing

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BENCHMARK_DIR="/Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator/benchmarks"
RESULTS_FILE="$BENCHMARK_DIR/benchmark_results_$(date +%Y%m%d_%H%M%S).md"

echo "================================================================"
echo "BENCHMARK SUITE: Performance Data Collection"
echo "================================================================"
echo ""
echo "Results will be saved to: $RESULTS_FILE"
echo ""

# Initialize results file
cat > "$RESULTS_FILE" << 'EOF'
# Benchmark Results

**Date**: $(date '+%Y-%m-%d %H:%M:%S')
**Host**: $(hostname)
**Cores**: $(sysctl -n hw.ncpu)
**Memory**: $(sysctl -n hw.memsize | awk '{print $1/1024/1024/1024 "GB"}')

---

## IN-MEMORY Benchmarks

| Rows | Duration | Peak Memory | Throughput | Memory/Row |
|------|----------|-------------|------------|------------|
EOF

# Function to run a single benchmark
run_benchmark() {
    local MODE=$1
    local WORKERS=$2
    local ROW_TARGET=$3
    local MANIFEST=$4

    echo -e "${YELLOW}→ Running benchmark: $MODE mode, $WORKERS workers, target $ROW_TARGET rows${NC}"

    # Generate data
    echo "  Generating nise data..."
    cd "$(dirname $MANIFEST)"
    nise report ocp --ocp-cluster-id benchmark-cluster \
        --insights-upload /tmp/benchmark-data \
        --static-report-file "$(basename $MANIFEST)" \
        --start-date 2025-10-01 \
        --end-date 2025-10-02 > /dev/null 2>&1

    # Upload to MinIO
    echo "  Uploading to MinIO..."
    # TODO: Upload logic

    # Run POC
    echo "  Running POC aggregation..."
    START_TIME=$(date +%s)

    export POC_MODE=$MODE
    export POC_WORKERS=$WORKERS
    export OCP_CLUSTER_ID="benchmark-cluster"
    export POC_YEAR="2025"
    export POC_MONTH="10"

    python -m src.main > /tmp/benchmark_${MODE}_${WORKERS}_${ROW_TARGET}.log 2>&1

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    # Extract metrics from log
    PEAK_MEMORY=$(grep "peak_rss_mb" /tmp/benchmark_${MODE}_${WORKERS}_${ROW_TARGET}.log | \
                  sed 's/.*peak_rss_mb=.\([0-9.]*\).*/\1/' || echo "0")

    # Calculate throughput
    THROUGHPUT=$(echo "scale=2; $ROW_TARGET / $DURATION" | bc)

    # Calculate memory per row
    MEMORY_PER_ROW=$(echo "scale=2; $PEAK_MEMORY / $ROW_TARGET * 1000" | bc)  # KB per row

    echo -e "${GREEN}  ✓ Complete: ${DURATION}s, ${PEAK_MEMORY}MB, ${THROUGHPUT} rows/s${NC}"

    # Append to results
    echo "| $ROW_TARGET | ${DURATION}s | ${PEAK_MEMORY}MB | ${THROUGHPUT} rows/s | ${MEMORY_PER_ROW}KB |" >> "$RESULTS_FILE"
}

# ============================================================================
# Phase 1: IN-MEMORY Scalability
# ============================================================================

echo ""
echo "================================================================"
echo "PHASE 1: IN-MEMORY Scalability"
echo "================================================================"
echo ""

# 22K rows
if [ ! -f "$BENCHMARK_DIR/ocp-only/manifest_22k.yml" ]; then
    echo -e "${YELLOW}Creating manifest for 22K rows...${NC}"
    # TODO: Create scaled-down manifest
fi

# 100K rows
if [ ! -f "$BENCHMARK_DIR/ocp-only/manifest_100k.yml" ]; then
    echo -e "${YELLOW}Creating manifest for 100K rows...${NC}"
    # TODO: Create manifest
fi

# 250K rows
if [ ! -f "$BENCHMARK_DIR/ocp-only/manifest_250k.yml" ]; then
    echo -e "${YELLOW}Creating manifest for 250K rows...${NC}"
    # TODO: Create manifest
fi

# 500K rows
if [ ! -f "$BENCHMARK_DIR/ocp-only/manifest_500k.yml" ]; then
    echo -e "${YELLOW}Creating manifest for 500K rows...${NC}"
    # TODO: Create manifest
fi

# Run benchmarks
# run_benchmark "in-memory" 1 22000 "$BENCHMARK_DIR/ocp-only/manifest_22k.yml"
# run_benchmark "in-memory" 1 100000 "$BENCHMARK_DIR/ocp-only/manifest_100k.yml"
# run_benchmark "in-memory" 1 250000 "$BENCHMARK_DIR/ocp-only/manifest_250k.yml"
# run_benchmark "in-memory" 1 500000 "$BENCHMARK_DIR/ocp-only/manifest_500k.yml"

echo ""
echo "================================================================"
echo "PHASE 2: Core Scaling"
echo "================================================================"
echo ""

cat >> "$RESULTS_FILE" << 'EOF'

---

## Core Scaling Benchmarks (744K rows)

| Cores | Duration | Peak Memory | Throughput | Speedup vs 4 cores |
|-------|----------|-------------|------------|-------------------|
| 4 | 4m 30s | 1.18 GB | 2,755 rows/s | 1.0x (baseline) |
EOF

# Run core scaling benchmarks
# run_benchmark "parallel" 8 744000 "$BENCHMARK_DIR/ocp-only/manifest_744k.yml"
# run_benchmark "parallel" 11 744000 "$BENCHMARK_DIR/ocp-only/manifest_744k.yml"

echo ""
echo "================================================================"
echo "BENCHMARK SUITE COMPLETE"
echo "================================================================"
echo ""
echo "Results saved to: $RESULTS_FILE"
echo ""
echo "Next steps:"
echo "1. Review results in $RESULTS_FILE"
echo "2. Update benchmarks/ocp-only/README.md"
echo "3. Create capacity planning formula"
echo ""

