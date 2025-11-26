# How to Run Benchmarks

> **Purpose**: Step-by-step guide to run POC benchmarks
> **Audience**: Developers, QE, anyone validating performance
> **Prerequisites**: Docker/Podman, Python 3.12+, ~8GB free memory

---

## Quick Start

```bash
# 1. Start infrastructure
podman-compose up -d

# 2. Activate virtual environment
source venv/bin/activate

# 3. Run OCP-on-AWS benchmarks (all scales)
./scripts/run_ocp_aws_benchmarks.sh --all

# 4. View results
cat benchmark_results/ocp_aws_*/results.csv
```

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Infrastructure Setup](#infrastructure-setup)
3. [Running OCP-on-AWS Benchmarks](#running-ocp-on-aws-benchmarks)
4. [Running OCP-Only Benchmarks](#running-ocp-only-benchmarks)
5. [Understanding Results](#understanding-results)
6. [Customizing Benchmarks](#customizing-benchmarks)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.12+ | POC runtime |
| Podman/Docker | Latest | MinIO + PostgreSQL |
| podman-compose | Latest | Container orchestration |

### Optional (for nise data generation)

| Software | Purpose |
|----------|---------|
| nise | Generate synthetic OCP/AWS data |
| yq | YAML processing |

### Install Python Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Infrastructure Setup

### 1. Start MinIO + PostgreSQL

```bash
# Start containers
podman-compose up -d

# Verify running
podman ps
```

**Expected containers:**
- `minio-poc` (port 9000: API, port 9001: console)
- `postgres-poc` (port 15432)

### 2. Verify Connectivity

```bash
# MinIO
curl http://localhost:9000/minio/health/live

# PostgreSQL
PGPASSWORD=koku123 psql -h localhost -p 15432 -U koku -d koku -c "SELECT 1"
```

### 3. MinIO Console (Optional)

Open http://localhost:9001 in browser:
- Username: `minioadmin`
- Password: `minioadmin`

---

## Running OCP-on-AWS Benchmarks

### Full Benchmark Suite

Runs all scales (20K to 1.5M output rows):

```bash
./scripts/run_ocp_aws_benchmarks.sh --all
```

**Duration**: ~20-30 minutes
**Output**: `benchmark_results/ocp_aws_YYYYMMDD_HHMMSS/`

### Single Scale

Run a specific scale:

```bash
# Options: scale-20k, scale-50k, scale-100k, scale-250k, scale-500k, scale-1m, scale-1.5m
./scripts/run_ocp_aws_benchmarks.sh --scale scale-250k
```

### Skip Warmup

For faster iteration during development:

```bash
./scripts/run_ocp_aws_benchmarks.sh --scale scale-100k --no-warmup
```

### What the Benchmark Does

For each scale:

1. **Phase 1: Nise Generation** - Generate synthetic OCP + AWS CSV data
2. **Phase 2: Parquet Transform** - Convert CSV to Parquet, upload to MinIO
3. **Phase 3: Aggregation** - Run POC aggregation, write to PostgreSQL

---

## Running OCP-Only Benchmarks

### Generate Test Data

```bash
# Generate nise data for OCP
nise report ocp --static-report-file test-manifests/ocp/benchmark_ocp.yml

# Convert to Parquet and upload
python scripts/csv_to_parquet_minio.py ./ocp
```

### Run OCP Aggregation

```bash
# Set environment
export OCP_PROVIDER_UUID="test-provider-uuid"
export POC_YEAR=2025
export POC_MONTH=01

# Run aggregation
python -m src.main --mode ocp
```

---

## Understanding Results

### Output Files

```
benchmark_results/ocp_aws_YYYYMMDD_HHMMSS/
├── results.csv          # Aggregation metrics per scale
├── phase_breakdown.csv  # Per-phase timings
└── *.log               # Detailed logs per scale
```

### Key Metrics

| Metric | Description |
|--------|-------------|
| `output_rows` | Rows written to PostgreSQL |
| `total_time_sec` | End-to-end processing time |
| `peak_memory_mb` | Maximum memory usage |
| `throughput_rows_sec` | Processing speed |

### Sample Output

```
scale       mode      output_rows  total_time_sec  peak_memory_mb  throughput
scale-100k  inmemory  33600        13.22           514             2542
scale-250k  inmemory  83328        31.67           938             2631
scale-500k  inmemory  166656       61.79           1693            2697
```

---

## Customizing Benchmarks

### Create Custom Scale

1. Edit `scripts/generate_benchmark_manifests.py`:

```python
SCALES = {
    'scale-custom': {
        'target_rows': 750000,
        'nodes': 744,
        'pods_per_node': 42,
        'namespaces': 3,
    },
    # ... other scales
}
```

2. Regenerate manifests:

```bash
python scripts/generate_benchmark_manifests.py
```

3. Run benchmark:

```bash
./scripts/run_ocp_aws_benchmarks.sh --scale scale-custom
```

### Adjust Chunk Size

For streaming mode testing:

```bash
export CHUNK_SIZE=10000
./scripts/run_ocp_aws_benchmarks.sh --scale scale-250k
```

### Enable Streaming Mode

```bash
export USE_STREAMING=true
./scripts/run_ocp_aws_benchmarks.sh --scale scale-250k
```

**Note**: Streaming has limited benefit for OCP-on-AWS due to JOIN requirements.

---

## Troubleshooting

### MinIO Connection Failed

```
Error: S3 endpoint not reachable
```

**Solution**:
```bash
# Check if MinIO is running
podman ps | grep minio

# Restart if needed
podman-compose restart minio
```

### PostgreSQL Connection Failed

```
Error: could not connect to server
```

**Solution**:
```bash
# Check if PostgreSQL is running
podman ps | grep postgres

# Verify port
PGPASSWORD=koku123 psql -h localhost -p 15432 -U koku -d koku -c "SELECT 1"
```

### Out of Memory

```
Error: MemoryError during aggregation
```

**Solutions**:
1. Use a smaller scale: `--scale scale-100k`
2. Enable streaming: `export USE_STREAMING=true`
3. Increase container memory limits

### Nise Not Found

```
Error: nise: command not found
```

**Solution**:
```bash
pip install nise
```

### Data Already Exists

```
Warning: Overwriting existing data in MinIO
```

This is expected - benchmarks clear and regenerate data each run.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POC_YEAR` | 2024 | Year for data generation |
| `POC_MONTH` | 01 | Month for data generation |
| `POSTGRES_HOST` | localhost | PostgreSQL host |
| `POSTGRES_PORT` | 15432 | PostgreSQL port |
| `POSTGRES_USER` | koku | PostgreSQL user |
| `POSTGRES_PASSWORD` | koku123 | PostgreSQL password |
| `S3_ENDPOINT` | http://localhost:9000 | MinIO endpoint |
| `S3_BUCKET` | koku | MinIO bucket |
| `USE_STREAMING` | false | Enable streaming mode |
| `CHUNK_SIZE` | 100000 | Chunk size for streaming |

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [OCP_ON_AWS_BENCHMARK_RESULTS.md](../benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) | Benchmark results and analysis |
| [OCP_ON_AWS_BENCHMARK_DETAILS.md](../benchmarks/OCP_ON_AWS_BENCHMARK_DETAILS.md) | Detailed phase breakdown |
| [ARCHITECTURE.md](../architecture/ARCHITECTURE.md) | System architecture |

---

*Last Updated: November 25, 2025*


