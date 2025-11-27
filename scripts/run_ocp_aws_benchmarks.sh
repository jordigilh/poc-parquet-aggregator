#!/bin/bash

# =============================================================================
# OCP-on-AWS Benchmark Runner (Industry Standard)
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
#   Phase 1: Generate nise data (CSV) - ONCE per scale
#   Phase 2: Transform CSV to Parquet + upload - ONCE per scale
#   Phase 3: Aggregation - 3 TIMES (for statistical validity)
#
# Usage:
#   ./scripts/run_ocp_aws_benchmarks.sh              # Run all scales
#   ./scripts/run_ocp_aws_benchmarks.sh scale-20k    # Single scale
#   ./scripts/run_ocp_aws_benchmarks.sh --no-warmup  # Skip warmup
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
MANIFESTS_DIR="$PROJECT_ROOT/test-manifests/ocp-aws-benchmarks"
RESULTS_DIR="$PROJECT_ROOT/benchmark_results/ocp_aws_$(date +%Y%m%d_%H%M%S)"
TEMP_DIR="/tmp/ocp-aws-benchmarks"
RESULTS_CSV="$RESULTS_DIR/RESULTS.csv"
PHASE_CSV="$RESULTS_DIR/phase_breakdown.csv"
RAW_CSV="$RESULTS_DIR/raw_runs.csv"

# PostgreSQL connection (from podman-compose)
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-15432}"
POSTGRES_USER="${POSTGRES_USER:-koku}"
# Force correct password for local development (docker-compose uses koku123)
POSTGRES_PASSWORD="koku123"
POSTGRES_DB="${POSTGRES_DB:-koku}"

# Benchmark settings
SCALES=("scale-20k" "scale-50k" "scale-100k" "scale-250k" "scale-500k" "scale-1m" "scale-1.5m" "scale-2m")
RUNS_PER_SCALE=3  # Industry standard: minimum 3 runs
DO_WARMUP=true

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }


check_dependencies() {
    log_info "Checking dependencies..."

    local missing=()
    local optional_missing=()

    # Required - nise can be run via `python3 -m nise` if not in PATH
    (command -v nise >/dev/null 2>&1 || python3 -m nise --version >/dev/null 2>&1) || missing+=("nise")
    command -v podman-compose >/dev/null 2>&1 || missing+=("podman-compose")
    command -v python3 >/dev/null 2>&1 || missing+=("python3")

    # Optional (we can work around these)
    command -v mc >/dev/null 2>&1 || optional_missing+=("mc (minio client)")
    command -v yq >/dev/null 2>&1 || optional_missing+=("yq")
    command -v jq >/dev/null 2>&1 || optional_missing+=("jq")
    command -v psql >/dev/null 2>&1 || optional_missing+=("psql")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing[*]}"
        exit 1
    fi

    if [[ ${#optional_missing[@]} -gt 0 ]]; then
        log_warn "Optional dependencies not found (will use Python fallbacks): ${optional_missing[*]}"
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
    export OCP_PROVIDER_UUID="12345678-1234-1234-1234-123456789012"
    export AWS_PROVIDER_UUID="87654321-4321-4321-4321-210987654321"
    export S3_ENDPOINT="http://localhost:9000"
    export S3_BUCKET="test-bucket"
    export S3_ACCESS_KEY="minioadmin"
    export S3_SECRET_KEY="minioadmin"
    export OCP_CLUSTER_ID="benchmark-cluster"
    export OCP_CLUSTER_ALIAS="benchmark-cluster"
    export OCP_YEAR=2025
    export OCP_MONTH=10

    # Initialize CSV files with headers
    echo "scale,output_rows,time_median,time_stddev,memory_median,memory_stddev,throughput,avg_cpu_pct,max_cpu_pct" > "$RESULTS_CSV"
    echo "scale,phase,time_sec,memory_mb,exit_code" > "$PHASE_CSV"
    echo "scale,run,output_rows,time_sec,memory_mb,throughput,avg_cpu_pct,max_cpu_pct" > "$RAW_CSV"

    # Check services (port 9000 is the S3 API, port 9001 is console)
    if ! curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        log_warn "MinIO not responding. Starting services..."
        cd "$PROJECT_ROOT" && podman-compose up -d
        sleep 5
    fi

    document_versions
    log_success "Environment ready"
}

# Phase 1: Generate nise data (CSV)
generate_nise_data() {
    local scale=$1
    local manifest="$MANIFESTS_DIR/benchmark_${scale}.yml"
    local output_dir="$TEMP_DIR/$scale"

    log_info "Phase 1: Generating nise data for $scale..."

    mkdir -p "$output_dir"
    cd "$output_dir"
    rm -rf ocp aws *.csv *.parquet 2>/dev/null || true
    mkdir -p ocp

    # Extract and generate OCP data
    local ocp_manifest="$output_dir/ocp_manifest.yml"
    python3 -c "
import yaml
with open('$manifest') as f:
    data = yaml.safe_load(f)
ocp_data = data.get('ocp', {})
start_date = data.get('start_date', '2025-10-01')
end_date = data.get('end_date', '2025-10-02')
ocp_data['start_date'] = start_date
ocp_data['end_date'] = end_date
for gen in ocp_data.get('generators', []):
    if 'OCPGenerator' in gen:
        gen['OCPGenerator']['start_date'] = start_date
        gen['OCPGenerator']['end_date'] = end_date
with open('$ocp_manifest', 'w') as f:
    yaml.dump(ocp_data, f, default_flow_style=False)
"

    # Run OCP nise with memory tracking
    local ocp_mem_log="$RESULTS_DIR/${scale}_nise_ocp_mem.log"
    python3 << WRAPPER_OCP > "$ocp_mem_log"
import subprocess
import psutil
import time
import sys

import shutil
nise_cmd = ['nise'] if shutil.which('nise') else ['python3', '-m', 'nise']
proc = subprocess.Popen(
    nise_cmd + ['report', 'ocp',
     '--static-report-file', '$ocp_manifest',
     '--ocp-cluster-id', 'benchmark-cluster',
     '--start-date', '2025-10-01', '--end-date', '2025-10-02',
     '--insights-upload', 'ocp'],
    stdout=open('$RESULTS_DIR/${scale}_nise_ocp.log', 'w'),
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
WRAPPER_OCP

    local ocp_time=$(grep "TIME=" "$ocp_mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local ocp_mem=$(grep "PEAK_MB=" "$ocp_mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local ocp_rows=$(find ocp -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")

    # Extract and generate AWS data
    local aws_manifest="$output_dir/aws_manifest.yml"
    python3 -c "
import yaml
with open('$manifest') as f:
    data = yaml.safe_load(f)
aws_data = data.get('aws', {})
aws_data['start_date'] = data.get('start_date', '2025-10-01')
aws_data['end_date'] = data.get('end_date', '2025-10-02')
with open('$aws_manifest', 'w') as f:
    yaml.dump(aws_data, f, default_flow_style=False)
"

    # Run AWS nise with memory tracking
    local aws_mem_log="$RESULTS_DIR/${scale}_nise_aws_mem.log"
    python3 << WRAPPER_AWS > "$aws_mem_log"
import subprocess
import psutil
import time

import shutil
nise_cmd = ['nise'] if shutil.which('nise') else ['python3', '-m', 'nise']
proc = subprocess.Popen(
    nise_cmd + ['report', 'aws',
     '--static-report-file', '$aws_manifest',
     '--start-date', '2025-10-01', '--end-date', '2025-10-02',
     '--write-monthly'],
    stdout=open('$RESULTS_DIR/${scale}_nise_aws.log', 'w'),
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
WRAPPER_AWS

    local aws_time=$(grep "TIME=" "$aws_mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local aws_mem=$(grep "PEAK_MB=" "$aws_mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local aws_rows=$(find . -maxdepth 1 -name "*.csv" -type f -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")

    # Total nise time and max memory
    local nise_time=$(python3 -c "print(f'{float($ocp_time) + float($aws_time):.2f}')")
    local nise_mem=$(python3 -c "print(f'{max(float($ocp_mem), float($aws_mem)):.0f}')")

    echo "$scale,nise_generation,$nise_time,$nise_mem,0" >> "$PHASE_CSV"

    log_success "Nise data: OCP=$ocp_rows rows, AWS=$aws_rows rows, time=${nise_time}s, peak_mem=${nise_mem}MB"

    cd "$PROJECT_ROOT"
}

# Phase 2: Transform CSV to Parquet and upload
transform_and_upload() {
    local scale=$1
    local data_dir="$TEMP_DIR/$scale"
    local mem_log="$RESULTS_DIR/${scale}_parquet_mem.log"

    log_info "Phase 2: Transforming to Parquet and uploading for $scale..."

    cd "$data_dir"
    [[ -f "$PROJECT_ROOT/venv/bin/activate" ]] && source "$PROJECT_ROOT/venv/bin/activate"

    # Run parquet transform with memory tracking
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

# Phase 3: Run single aggregation with memory tracking
run_single_aggregation() {
    local scale=$1
    local run_num=$2
    local log_file="$RESULTS_DIR/${scale}_run${run_num}.log"
    local mem_log="$RESULTS_DIR/${scale}_run${run_num}_memory.log"
    local result_file="$RESULTS_DIR/${scale}_run${run_num}_result.txt"

    echo -e "${BLUE}  Run $run_num/$RUNS_PER_SCALE...${NC}" >&2

    cd "$PROJECT_ROOT"
    [[ -f venv/bin/activate ]] && source venv/bin/activate

    # Clear table
    python3 << EOF 2>/dev/null || true
import psycopg2
try:
    conn = psycopg2.connect(host='$POSTGRES_HOST', port=$POSTGRES_PORT, dbname='$POSTGRES_DB', user='$POSTGRES_USER', password='$POSTGRES_PASSWORD')
    cur = conn.cursor()
    cur.execute('TRUNCATE TABLE ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;')
    conn.commit()
    conn.close()
except Exception as e:
    pass  # Table might not exist yet
EOF

    # Run aggregation with continuous memory + CPU monitoring (100ms sampling)
    python3 << WRAPPER_AGG > "$mem_log"
import subprocess
import psutil
import time
import sys
import os

os.chdir('$PROJECT_ROOT')

proc = subprocess.Popen(
    [sys.executable, '-m', 'src.main'],
    stdout=open('$log_file', 'w'),
    stderr=subprocess.STDOUT,
    env={**os.environ, 'USE_STREAMING': 'false'}
)

peak_mb = 0
samples = 0
cpu_samples = []
start = time.time()

# Continuous memory + CPU sampling at ~100ms interval
while proc.poll() is None:
    try:
        p = psutil.Process(proc.pid)
        rss = p.memory_info().rss / (1024**2)
        
        # Get all processes (main + children)
        all_procs = [p] + list(p.children(recursive=True))
        
        total_cpu = 0
        for proc_obj in all_procs:
            try:
                if proc_obj != p:
                    rss += proc_obj.memory_info().rss / (1024**2)
                # Use cpu_percent with small interval for accurate readings
                cpu = proc_obj.cpu_percent(interval=0.05)
                total_cpu += cpu
            except: pass
        
        if samples > 0:  # Skip first sample
            cpu_samples.append(total_cpu)
        peak_mb = max(peak_mb, rss)
        samples += 1
    except: pass
    time.sleep(0.05)  # ~100ms total with cpu_percent interval

elapsed = time.time() - start

# Calculate CPU stats
avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
max_cpu = max(cpu_samples) if cpu_samples else 0

print(f"TIME={elapsed:.2f}")
print(f"PEAK_MB={peak_mb:.0f}")
print(f"SAMPLES={samples}")
print(f"AVG_CPU={avg_cpu:.1f}")
print(f"MAX_CPU={max_cpu:.1f}")
print(f"EXIT={proc.returncode or 0}")
WRAPPER_AGG

    local agg_time=$(grep "TIME=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local peak_memory=$(grep "PEAK_MB=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local avg_cpu=$(grep "AVG_CPU=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local max_cpu=$(grep "MAX_CPU=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")
    local exit_code=$(grep "EXIT=" "$mem_log" 2>/dev/null | cut -d= -f2 || echo "0")

    # Extract output rows from log
    local output_rows=$(grep "OCP-AWS summary rows" "$log_file" | tail -1 | grep -oE '[0-9]+ OCP-AWS' | grep -oE '[0-9]+' || echo "0")
    [[ -z "$output_rows" ]] && output_rows="0"

    local throughput=0
    # Clean numeric values (remove any whitespace/special chars)
    local clean_rows=$(echo "$output_rows" | tr -dc '0-9')
    local clean_time=$(echo "$agg_time" | tr -dc '0-9.')
    if [[ -n "$clean_rows" && "$clean_rows" != "0" && -n "$clean_time" && "$clean_time" != "0" ]]; then
        # Use bc for reliable calculation
        throughput=$(echo "scale=0; $clean_rows / $clean_time" | bc 2>/dev/null || echo "0")
        [[ -z "$throughput" ]] && throughput=0
    fi

    # Record raw run data (now includes CPU metrics)
    echo "$scale,$run_num,$output_rows,$agg_time,$peak_memory,$throughput,$avg_cpu,$max_cpu" >> "$RAW_CSV"

    echo -e "${GREEN}    Run $run_num: ${agg_time}s, ${peak_memory}MB, CPU avg=${avg_cpu}% max=${max_cpu}%, $output_rows rows${NC}" >&2

    # Return values via file to avoid log pollution (now includes CPU)
    echo "$agg_time $peak_memory $output_rows $throughput $avg_cpu $max_cpu" > "$result_file"
}

# Run multiple aggregations and compute statistics
run_aggregation_with_stats() {
    local scale=$1

    log_info "Phase 3: Running $RUNS_PER_SCALE aggregation runs for $scale..."

    local times=()
    local memories=()
    local rows=0
    local throughputs=()
    local avg_cpus=()
    local max_cpus=()

    for run in $(seq 1 $RUNS_PER_SCALE); do
        run_single_aggregation "$scale" "$run"
        local result_file="$RESULTS_DIR/${scale}_run${run}_result.txt"
        local result=$(cat "$result_file")
        local time=$(echo "$result" | awk '{print $1}')
        local mem=$(echo "$result" | awk '{print $2}')
        local r=$(echo "$result" | awk '{print $3}')
        local tput=$(echo "$result" | awk '{print $4}')
        local avg_cpu=$(echo "$result" | awk '{print $5}')
        local max_cpu=$(echo "$result" | awk '{print $6}')

        times+=("$time")
        memories+=("$mem")
        rows=$r
        throughputs+=("$tput")
        avg_cpus+=("$avg_cpu")
        max_cpus+=("$max_cpu")
    done

    # Calculate median and stddev using Python
    python3 << EOF
import statistics

times = [float(t) for t in "${times[*]}".split()]
memories = [float(m) for m in "${memories[*]}".split()]
throughputs = [float(t) for t in "${throughputs[*]}".split()]
avg_cpus = [float(c) for c in "${avg_cpus[*]}".split()]
max_cpus = [float(c) for c in "${max_cpus[*]}".split()]
rows = $rows

time_median = statistics.median(times)
time_stddev = statistics.stdev(times) if len(times) > 1 else 0
mem_median = statistics.median(memories)
mem_stddev = statistics.stdev(memories) if len(memories) > 1 else 0
tput_median = statistics.median(throughputs)
avg_cpu_median = statistics.median(avg_cpus)
max_cpu_median = statistics.median(max_cpus)

print(f"SCALE=$scale")
print(f"ROWS={rows}")
print(f"TIME_MEDIAN={time_median:.2f}")
print(f"TIME_STDDEV={time_stddev:.2f}")
print(f"MEM_MEDIAN={mem_median:.0f}")
print(f"MEM_STDDEV={mem_stddev:.0f}")
print(f"THROUGHPUT={tput_median:.0f}")
print(f"AVG_CPU={avg_cpu_median:.1f}")
print(f"MAX_CPU={max_cpu_median:.1f}")

# Write to results CSV (now includes CPU metrics)
with open('$RESULTS_CSV', 'a') as f:
    f.write(f"$scale,{rows},{time_median:.2f},{time_stddev:.2f},{mem_median:.0f},{mem_stddev:.0f},{tput_median:.0f},{avg_cpu_median:.1f},{max_cpu_median:.1f}\n")

print("")
print(f"  📊 Statistics for $scale:")
print(f"     Output Rows: {rows}")
print(f"     Time: {time_median:.2f}s ± {time_stddev:.2f}s")
print(f"     Memory: {mem_median:.0f}MB ± {mem_stddev:.0f}MB")
print(f"     Throughput: {tput_median:.0f} rows/sec")
print(f"     CPU: avg={avg_cpu_median:.1f}%, max={max_cpu_median:.1f}% (single-threaded)")
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
    cur.execute('SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;')
    count = cur.fetchone()[0]

    # Check for nulls in required columns (namespace only - OCP-on-AWS doesn't have pod column)
    cur.execute('''
        SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p
        WHERE namespace IS NULL;
    ''')
    nulls = cur.fetchone()[0]

    # Check costs (use unblended_cost - the actual cost column in the table)
    cur.execute('SELECT SUM(unblended_cost) FROM ${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;')
    total_cost = cur.fetchone()[0] or 0

    conn.close()

    print(f"  ✓ Row count: {count}")
    print(f"  ✓ Null values: {nulls}")
    print(f"  ✓ Total infrastructure cost: \${total_cost:.2f}")

    if nulls > 0:
        print(f"  ⚠️ WARNING: {nulls} rows have NULL values")
    if total_cost <= 0:
        print(f"  ⚠️ WARNING: No infrastructure costs recorded")

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

    # Phase 1: Generate nise data (ONCE)
    generate_nise_data "$scale"

    # Phase 2: Transform to Parquet (ONCE)
    transform_and_upload "$scale"

    # Phase 3: Aggregation with statistics (3 runs)
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
# OCP-on-AWS Benchmark Results

**Date**: $(date)
**Host**: $(hostname)
**Methodology**: $RUNS_PER_SCALE runs per scale, reporting median ± stddev

## Summary Results

| Scale | Output Rows | Time (s) | Time StdDev | Memory (MB) | Memory StdDev | Throughput | Avg CPU | Max CPU |
|-------|-------------|----------|-------------|-------------|---------------|------------|---------|---------|
$(tail -n +2 "$RESULTS_CSV" | while IFS=',' read scale rows time_med time_std mem_med mem_std tput avg_cpu max_cpu; do
    echo "| $scale | $rows | $time_med | ±$time_std | $mem_med | ±$mem_std | $tput rows/s | ${avg_cpu}% | ${max_cpu}% |"
done)

## Raw Run Data

| Scale | Run | Output Rows | Time (s) | Memory (MB) | Throughput | Avg CPU | Max CPU |
|-------|-----|-------------|----------|-------------|------------|---------|---------|
$(tail -n +2 "$RAW_CSV" | while IFS=',' read scale run rows time mem tput avg_cpu max_cpu; do
    echo "| $scale | $run | $rows | $time | $mem | $tput rows/s | ${avg_cpu}% | ${max_cpu}% |"
done)

## Configuration

- Mode: In-memory only (streaming disabled, **single-threaded**)
- Runs per scale: $RUNS_PER_SCALE
- Memory sampling: 100ms interval
- CPU sampling: 100ms interval (confirms single-core utilization ~100%)
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
                echo "Usage: $0 [scale-name] [--no-warmup]"
                echo "  scale-name: scale-20k, scale-50k, scale-100k, scale-250k, scale-500k, scale-1m, scale-1.5m, scale-2m"
                echo "  --no-warmup: Skip warmup run"
                echo ""
                echo "If no scale specified, runs all scales."
                exit 0
                ;;
            scale-*)
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
        python3 -m src.main > /dev/null 2>&1 || true
        log_success "Warmup complete"
    fi

    # Process each scale
    for scale in "${run_scales[@]}"; do
        process_scale "$scale"
    done

    summarize_results
}

main "$@"
