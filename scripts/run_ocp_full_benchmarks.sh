#!/bin/bash

# =============================================================================
# OCP-Only Benchmark Runner (Industry Standard)
# =============================================================================
# Runs benchmarks at various scales with proper statistical methodology.
#
# METHODOLOGY:
#   - 3 runs per scale (report median ± stddev)
#   - Continuous memory sampling (100ms interval)
#   - Warmup run (discarded)
#   - Correctness validation
#
# PHASES (per scale):
#   Stage 1: Generate nise data (CSV) - ONCE per scale
#   Stage 2: Transform CSV to Parquet + upload - ONCE per scale
#   Stage 3: Aggregation - 3 TIMES (for statistical validity)
#
# Usage:
#   ./scripts/run_ocp_full_benchmarks.sh              # Run all scales
#   ./scripts/run_ocp_full_benchmarks.sh 100k         # Single scale
#   ./scripts/run_ocp_full_benchmarks.sh --no-warmup  # Skip warmup
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project paths
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFESTS_DIR="$PROJECT_ROOT/test-manifests/ocp-benchmarks"
RESULTS_DIR="$PROJECT_ROOT/benchmark_results/ocp_$(date +%Y%m%d_%H%M%S)"
TEMP_DIR="/tmp/ocp-benchmarks"
RESULTS_CSV="$RESULTS_DIR/RESULTS.csv"
RAW_CSV="$RESULTS_DIR/raw_runs.csv"
PHASE_CSV="$RESULTS_DIR/phase_breakdown.csv"

# PostgreSQL connection (from podman-compose)
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-15432}"
POSTGRES_USER="${POSTGRES_USER:-koku}"
# Force correct password for local development (docker-compose uses koku123)
POSTGRES_PASSWORD="koku123"
POSTGRES_DB="${POSTGRES_DB:-koku}"

# Benchmark settings
SCALES=("20k" "50k" "100k" "250k" "500k" "1m" "1.5m" "2m")
RUNS_PER_SCALE=3  # Industry standard: minimum 3 runs
DO_WARMUP=true

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }

check_dependencies() {
    log_info "Checking dependencies..."

    local missing=()

    # Required - nise can be run via `python3 -m nise` if not in PATH
    (command -v nise >/dev/null 2>&1 || python3 -m nise --version >/dev/null 2>&1) || missing+=("nise")
    command -v podman-compose >/dev/null 2>&1 || missing+=("podman-compose")
    command -v python3 >/dev/null 2>&1 || missing+=("python3")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing[*]}"
    exit 1
fi

    log_success "Required dependencies found"
}

document_versions() {
log_info "Documenting software versions..."

    local versions_file="$RESULTS_DIR/versions.txt"

    echo "=== Software Versions ===" > "$versions_file"
    echo "Date: $(date)" >> "$versions_file"
    echo "Host: $(hostname)" >> "$versions_file"
    echo "" >> "$versions_file"

    echo "Python: $(python3 --version 2>&1)" >> "$versions_file"
    echo "pandas: $(pip show pandas 2>/dev/null | grep Version || echo 'not found')" >> "$versions_file"
    echo "pyarrow: $(pip show pyarrow 2>/dev/null | grep Version || echo 'not found')" >> "$versions_file"
    echo "psycopg2: $(pip show psycopg2-binary 2>/dev/null | grep Version || echo 'not found')" >> "$versions_file"
    echo "nise: $(pip show nise 2>/dev/null | grep Version || echo 'not found')" >> "$versions_file"
    echo "" >> "$versions_file"
    echo "Disk free: $(df -h . | tail -1 | awk '{print $4}')" >> "$versions_file"

    log_success "Versions documented in $versions_file"
}

setup_environment() {
    log_info "Setting up environment..."

    mkdir -p "$RESULTS_DIR"
    mkdir -p "$TEMP_DIR"

    # Export required environment variables
    export POC_YEAR=2025
    export POC_MONTH=10
    export POSTGRES_HOST=$POSTGRES_HOST
    export POSTGRES_PORT=$POSTGRES_PORT
    export POSTGRES_USER=$POSTGRES_USER
    export POSTGRES_PASSWORD=$POSTGRES_PASSWORD
    export POSTGRES_DB=$POSTGRES_DB
    export ORG_ID="org1234567"
    export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export S3_ENDPOINT="http://localhost:9000"
    export S3_BUCKET="koku"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export OCP_CLUSTER_ID="benchmark-cluster"
export OCP_CLUSTER_ALIAS="Benchmark Cluster"
    export OCP_YEAR=2025
    export OCP_MONTH=10
    # Ensure OCP-only mode (no AWS)
unset AWS_PROVIDER_UUID

    # Initialize CSV files with headers
    echo "scale,output_rows,time_median,time_stddev,memory_median,memory_stddev,throughput" > "$RESULTS_CSV"
    echo "scale,run,output_rows,time_sec,memory_mb,throughput" > "$RAW_CSV"
    echo "scale,phase,time_sec,memory_mb,exit_code" > "$PHASE_CSV"

    # Check services
    if ! curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        log_warn "MinIO not responding. Starting services..."
        cd "$PROJECT_ROOT" && podman-compose up -d
        sleep 5
    fi

    if ! podman exec postgres-poc psql -U koku -d koku -c "SELECT 1" > /dev/null 2>&1; then
        log_warn "PostgreSQL not responding. Starting services..."
        cd "$PROJECT_ROOT" && podman-compose up -d
        sleep 5
    fi

    document_versions
    log_success "Environment ready"
}

# Stage 1: Generate nise data (CSV)
generate_nise_data() {
    local scale=$1
    local manifest="$MANIFESTS_DIR/benchmark_ocp_${scale}.yml"
    local output_dir="$TEMP_DIR/$scale"

    log_info "Stage 1: Generating nise data for $scale..."

    if [[ ! -f "$manifest" ]]; then
        log_error "Manifest not found: $manifest"
        return 1
    fi

    mkdir -p "$output_dir/ocp"
    cd "$output_dir"
    rm -rf ocp/* 2>/dev/null || true

    # Extract dates from manifest
    local start_date=$(grep "start_date:" "$manifest" | head -1 | awk '{print $2}' | tr -d "'\"")
    local end_date=$(grep "end_date:" "$manifest" | head -1 | awk '{print $2}' | tr -d "'\"")

    [[ -z "$start_date" ]] && start_date="2025-10-01"
    [[ -z "$end_date" ]] && end_date="2025-10-02"

    # Run nise with memory tracking (100ms sampling)
    local mem_log="$RESULTS_DIR/${scale}_nise_mem.log"
    python3 << WRAPPER_NISE > "$mem_log"
import subprocess
import psutil
import time

import shutil
nise_cmd = ['nise'] if shutil.which('nise') else ['python3', '-m', 'nise']
proc = subprocess.Popen(
    nise_cmd + ['report', 'ocp',
     '--static-report-file', '$manifest',
     '--ocp-cluster-id', '$OCP_CLUSTER_ID',
     '--start-date', '$start_date', '--end-date', '$end_date',
     '--insights-upload', 'ocp'],
    stdout=open('$RESULTS_DIR/${scale}_nise.log', 'w'),
    stderr=subprocess.STDOUT
)

peak_mb = 0
start = time.time()
while proc.poll() is None:
    try:
        p = psutil.Process(proc.pid)
        rss = p.memory_info().rss / (1024**2)
        for c in p.children(recursive=True):
            try: rss += c.memory_info().rss / (1024**2)
            except: pass
        peak_mb = max(peak_mb, rss)
    except: pass
    time.sleep(0.1)  # 100ms sampling

elapsed = time.time() - start
print(f"TIME={elapsed:.2f}")
print(f"PEAK_MB={peak_mb:.0f}")
print(f"EXIT={proc.returncode or 0}")
WRAPPER_NISE

    local nise_time=$(grep "TIME=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local nise_mem=$(grep "PEAK_MB=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local nise_exit=$(grep "EXIT=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local input_rows=$(find ocp -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")

    echo "$scale,nise_generation,$nise_time,$nise_mem,$nise_exit" >> "$PHASE_CSV"

    log_success "Nise data: $input_rows CSV rows, time=${nise_time}s, peak_mem=${nise_mem}MB"

    cd "$PROJECT_ROOT"
}

# Stage 2: Transform CSV to Parquet and upload
transform_and_upload() {
    local scale=$1
    local data_dir="$TEMP_DIR/$scale"
    local mem_log="$RESULTS_DIR/${scale}_parquet_mem.log"

    log_info "Stage 2: Transforming to Parquet and uploading for $scale..."

    cd "$data_dir"
    [[ -f "$PROJECT_ROOT/venv/bin/activate" ]] && source "$PROJECT_ROOT/venv/bin/activate"

    # Clear MinIO first
    python3 << EOFCLEAR
import boto3
from botocore.client import Config
import os

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT'),
    aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
    config=Config(signature_version='s3v4'),
    region_name='us-east-1'
)

bucket = os.getenv('S3_BUCKET')
try:
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        if 'Contents' in page:
            objects = [{'Key': obj['Key']} for obj in page['Contents']]
            s3.delete_objects(Bucket=bucket, Delete={'Objects': objects})
    print('✓ MinIO cleared')
except Exception as e:
    print(f'⚠️ {e}')
EOFCLEAR

    # Run parquet transform with memory tracking (100ms sampling)
    python3 << WRAPPER_PARQUET > "$mem_log"
import subprocess
import psutil
import time
import sys

proc = subprocess.Popen(
    [sys.executable, '$PROJECT_ROOT/scripts/csv_to_parquet_minio.py', '$data_dir'],
    stdout=open('$RESULTS_DIR/${scale}_upload.log', 'w'),
    stderr=subprocess.STDOUT
)

peak_mb = 0
start = time.time()
while proc.poll() is None:
    try:
        p = psutil.Process(proc.pid)
        rss = p.memory_info().rss / (1024**2)
        for c in p.children(recursive=True):
            try: rss += c.memory_info().rss / (1024**2)
            except: pass
        peak_mb = max(peak_mb, rss)
    except: pass
    time.sleep(0.1)  # 100ms sampling

elapsed = time.time() - start
print(f"TIME={elapsed:.2f}")
print(f"PEAK_MB={peak_mb:.0f}")
print(f"EXIT={proc.returncode or 0}")
WRAPPER_PARQUET

    local transform_time=$(grep "TIME=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local transform_mem=$(grep "PEAK_MB=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local transform_exit=$(grep "EXIT=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")

    echo "$scale,parquet_transform,$transform_time,$transform_mem,$transform_exit" >> "$PHASE_CSV"

    log_success "Parquet transform: time=${transform_time}s, peak_mem=${transform_mem}MB"

    cd "$PROJECT_ROOT"
}

# Stage 3: Run single aggregation with continuous memory monitoring
run_single_aggregation() {
    local scale=$1
    local run_num=$2
    local log_file="$RESULTS_DIR/${scale}_run${run_num}.log"
    local mem_log="$RESULTS_DIR/${scale}_run${run_num}_memory.log"
    local result_file="$RESULTS_DIR/${scale}_run${run_num}_result.txt"

    echo -e "${BLUE}  Run $run_num/$RUNS_PER_SCALE...${NC}" >&2

    cd "$PROJECT_ROOT"
    [[ -f venv/bin/activate ]] && source venv/bin/activate

    # Clear PostgreSQL table (using Python since psql may not be available)
    python3 -c "
import psycopg2
try:
    conn = psycopg2.connect(
        host='$POSTGRES_HOST', port=$POSTGRES_PORT,
        user='$POSTGRES_USER', password='$POSTGRES_PASSWORD',
        database='$POSTGRES_DB'
    )
    cur = conn.cursor()
    cur.execute('TRUNCATE TABLE ${ORG_ID}.reporting_ocpusagelineitem_daily_summary')
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    pass  # Table may not exist yet
" 2>/dev/null || true

    # Run aggregation with continuous memory monitoring (100ms sampling)
    python3 << WRAPPER_AGG > "$mem_log"
import subprocess
import psutil
import time
import sys
import os

os.chdir('$PROJECT_ROOT')

proc = subprocess.Popen(
    [sys.executable, '-c', 'from src.main import main; main()'],
    stdout=open('$log_file', 'w'),
    stderr=subprocess.STDOUT,
    env={**os.environ, 'USE_STREAMING': 'false'}
)

peak_mb = 0
samples = 0
start = time.time()

# Continuous memory sampling at 100ms interval (industry standard)
while proc.poll() is None:
    try:
        p = psutil.Process(proc.pid)
        rss = p.memory_info().rss / (1024**2)
        for c in p.children(recursive=True):
            try: rss += c.memory_info().rss / (1024**2)
            except: pass
        peak_mb = max(peak_mb, rss)
        samples += 1
    except: pass
    time.sleep(0.1)  # 100ms sampling interval

elapsed = time.time() - start
print(f"TIME={elapsed:.2f}")
print(f"PEAK_MB={peak_mb:.0f}")
print(f"SAMPLES={samples}")
print(f"EXIT={proc.returncode or 0}")
WRAPPER_AGG

    local agg_time=$(grep "TIME=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local peak_memory=$(grep "PEAK_MB=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local exit_code=$(grep "EXIT=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")

    # Get output row count from log (validation row_count is most reliable)
    local output_rows=$(grep "row_count:" "$log_file" 2>/dev/null | tail -1 | awk -F': ' '{print $NF}' | tr -d ' ' || echo "0")
    [[ -z "$output_rows" || "$output_rows" == "0" ]] && output_rows=$(grep -oE 'row_count=[0-9]+' "$log_file" 2>/dev/null | tail -1 | cut -d= -f2 || echo "0")
    [[ -z "$output_rows" ]] && output_rows="0"
    # Fallback to PostgreSQL query if log parsing failed
    # Fallback to Python query if log parsing failed
    if [[ "$output_rows" == "0" ]]; then
        output_rows=$(python3 -c "
import psycopg2
try:
    conn = psycopg2.connect(host='$POSTGRES_HOST', port=$POSTGRES_PORT, user='$POSTGRES_USER', password='$POSTGRES_PASSWORD', database='$POSTGRES_DB')
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary')
    print(cur.fetchone()[0])
    cur.close()
    conn.close()
except:
    print(0)
" 2>/dev/null || echo "0")
    fi

    local throughput=0
    # Clean numeric values (remove any whitespace/special chars)
    local clean_rows=$(echo "$output_rows" | tr -dc '0-9')
    local clean_time=$(echo "$agg_time" | tr -dc '0-9.')
    if [[ -n "$clean_rows" && "$clean_rows" != "0" && -n "$clean_time" && "$clean_time" != "0" ]]; then
        # Use bc for reliable calculation
        throughput=$(echo "scale=0; $clean_rows / $clean_time" | bc 2>/dev/null || echo "0")
        [[ -z "$throughput" ]] && throughput=0
    fi

    # Record raw run data
    echo "$scale,$run_num,$output_rows,$agg_time,$peak_memory,$throughput" >> "$RAW_CSV"

    echo -e "${GREEN}    Run $run_num: ${agg_time}s, ${peak_memory}MB, $output_rows rows, $throughput rows/s${NC}" >&2

    # Return values via file
    echo "$agg_time $peak_memory $output_rows $throughput" > "$result_file"
}

# Run multiple aggregations and compute statistics
run_aggregation_with_stats() {
    local scale=$1

    log_info "Stage 3: Running $RUNS_PER_SCALE aggregation runs for $scale..."

    local times=()
    local memories=()
    local rows=0
    local throughputs=()

    for run in $(seq 1 $RUNS_PER_SCALE); do
        run_single_aggregation "$scale" "$run"
        local result_file="$RESULTS_DIR/${scale}_run${run}_result.txt"
        local result=$(cat "$result_file")
        local time=$(echo "$result" | awk '{print $1}')
        local mem=$(echo "$result" | awk '{print $2}')
        local r=$(echo "$result" | awk '{print $3}')
        local tput=$(echo "$result" | awk '{print $4}')

        times+=("$time")
        memories+=("$mem")
        rows=$r
        throughputs+=("$tput")
    done

    # Strip any ANSI color codes from values
    local clean_rows=$(echo "$rows" | sed 's/\x1B\[[0-9;]*[JKmsu]//g' | tr -d '[:space:]')
    [[ -z "$clean_rows" ]] && clean_rows="0"

    # Calculate median and stddev using Python
    python3 << EOF
import statistics

times = [float(t) for t in "${times[*]}".split()]
memories = [float(m) for m in "${memories[*]}".split()]
throughputs = [float(t) for t in "${throughputs[*]}".split()]
rows = int("$clean_rows") if "$clean_rows".isdigit() else 0

time_median = statistics.median(times)
time_stddev = statistics.stdev(times) if len(times) > 1 else 0
mem_median = statistics.median(memories)
mem_stddev = statistics.stdev(memories) if len(memories) > 1 else 0
tput_median = statistics.median(throughputs)

print(f"SCALE=$scale")
print(f"ROWS={rows}")
print(f"TIME_MEDIAN={time_median:.2f}")
print(f"TIME_STDDEV={time_stddev:.2f}")
print(f"MEM_MEDIAN={mem_median:.0f}")
print(f"MEM_STDDEV={mem_stddev:.0f}")
print(f"THROUGHPUT={tput_median:.0f}")

# Write to results CSV
with open('$RESULTS_CSV', 'a') as f:
    f.write(f"$scale,{rows},{time_median:.2f},{time_stddev:.2f},{mem_median:.0f},{mem_stddev:.0f},{tput_median:.0f}\n")

print("")
print(f"  📊 Statistics for $scale:")
print(f"     Output Rows: {rows}")
print(f"     Time: {time_median:.2f}s ± {time_stddev:.2f}s")
print(f"     Memory: {mem_median:.0f}MB ± {mem_stddev:.0f}MB")
print(f"     Throughput: {tput_median:.0f} rows/sec")
EOF
}

# Validate results correctness
validate_results() {
    local scale=$1

    log_info "Validating results for $scale..."

    python3 << EOF
import psycopg2

try:
    conn = psycopg2.connect(
        host='$POSTGRES_HOST',
        port=$POSTGRES_PORT,
        dbname='$POSTGRES_DB',
        user='$POSTGRES_USER',
        password='$POSTGRES_PASSWORD'
    )
    cur = conn.cursor()

    # Count rows
    cur.execute('SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary;')
    count = cur.fetchone()[0]

    # Check for nulls in required columns
    cur.execute('''
        SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary
        WHERE namespace IS NULL OR pod IS NULL;
    ''')
    nulls = cur.fetchone()[0]

    # Check date range
    cur.execute('SELECT COUNT(DISTINCT DATE(usage_start)) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary;')
    days = cur.fetchone()[0]

    conn.close()

    print(f"  ✓ Row count: {count}")
    print(f"  ✓ Null values: {nulls}")
    print(f"  ✓ Distinct days: {days}")

    if nulls > 0:
        print(f"  ⚠️ WARNING: {nulls} rows have NULL values")

except Exception as e:
    print(f"  ❌ Validation error: {e}")
EOF
}

# Process a single scale
process_scale() {
    local scale=$1

    echo ""
    echo "========================================"
    echo "Processing: $scale"
    echo "========================================"

    # Stage 1: Generate nise data (ONCE)
    generate_nise_data "$scale"

    # Stage 2: Transform to Parquet (ONCE)
    transform_and_upload "$scale"

    # Stage 3: Aggregation with statistics (3 runs)
    run_aggregation_with_stats "$scale"

    # Validate results
    validate_results "$scale"
}

summarize_results() {
    echo ""
    echo "========================================"
    echo "Benchmark Complete!"
    echo "========================================"
echo ""
    echo "Results saved to: $RESULTS_DIR"
echo ""

echo "=== RAW RUNS ==="
    echo ""
    column -t -s',' "$RAW_CSV"
echo ""

echo "=== SUMMARY (Median ± StdDev) ==="
    echo ""
    column -t -s',' "$RESULTS_CSV"
echo ""

    # Generate markdown summary
    cat > "$RESULTS_DIR/SUMMARY.md" << EOFMD
# OCP-Only Benchmark Results

**Date**: $(date)
**Host**: $(hostname)
**Methodology**: $RUNS_PER_SCALE runs per scale, reporting median ± stddev
**Memory Sampling**: 100ms interval (continuous)

## Summary Results

| Scale | Output Rows | Time (s) | Time StdDev | Memory (MB) | Memory StdDev | Throughput |
|-------|-------------|----------|-------------|-------------|---------------|------------|
$(tail -n +2 "$RESULTS_CSV" | while IFS=',' read scale rows time_med time_std mem_med mem_std tput; do
    echo "| $scale | $rows | $time_med | ±$time_std | $mem_med | ±$mem_std | $tput rows/s |"
done)

## Raw Run Data

| Scale | Run | Output Rows | Time (s) | Memory (MB) | Throughput |
|-------|-----|-------------|----------|-------------|------------|
$(tail -n +2 "$RAW_CSV" | while IFS=',' read scale run rows time mem tput; do
    echo "| $scale | $run | $rows | $time | $mem | $tput rows/s |"
done)

## Configuration

- Mode: OCP-only (in-memory, no AWS)
- Runs per scale: $RUNS_PER_SCALE
- Memory sampling: 100ms interval
- PostgreSQL: $POSTGRES_HOST:$POSTGRES_PORT
- MinIO: localhost:9000

EOFMD

    log_success "Summary report: $RESULTS_DIR/SUMMARY.md"
}

# Main
main() {
    local run_scales=()

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-warmup)
                DO_WARMUP=false
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [scale] [--no-warmup]"
                echo "  scale: 20k, 50k, 100k, 250k, 500k, 1m, 1.5m, 2m"
                echo "  --no-warmup: Skip warmup run"
echo ""
                echo "If no scale specified, runs all scales."
                exit 0
                ;;
            20k|50k|100k|250k|500k|1m|1.5m|2m)
                run_scales+=("$1")
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Default to all scales if none specified
    if [[ ${#run_scales[@]} -eq 0 ]]; then
        run_scales=("${SCALES[@]}")
    fi

    check_dependencies
    setup_environment

    # Optional warmup
    if [[ "$DO_WARMUP" == "true" ]]; then
        log_info "Running warmup (will be discarded)..."
        cd "$PROJECT_ROOT"
        [[ -f venv/bin/activate ]] && source venv/bin/activate
        export USE_STREAMING="false"
        python3 -c "from src.main import main; main()" > /dev/null 2>&1 || true
        log_success "Warmup complete"
    fi

    # Process each scale
    for scale in "${run_scales[@]}"; do
        process_scale "$scale"
    done

    summarize_results
}

main "$@"
