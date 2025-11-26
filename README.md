# POC: Parquet Aggregator for Cost Management

> **Replace Trino + Hive with Python-based Parquet aggregation for on-prem deployments**

[![CI](https://github.com/insights-onprem/poc-parquet-aggregator/actions/workflows/ci.yml/badge.svg)](https://github.com/insights-onprem/poc-parquet-aggregator/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)](docs/architecture/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/Tests-23%2F23%20Passing-brightgreen)](docs/MATCHING_LABELS.md)
[![OCP](https://img.shields.io/badge/OCP-✓%20Supported-blue)](docs/benchmarks/OCP_BENCHMARK_RESULTS.md)
[![OCP--on--AWS](https://img.shields.io/badge/OCP--on--AWS-✓%20Supported-blue)](docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md)

---

## Overview

This POC demonstrates replacing **Trino + Hive** with a custom Python aggregation layer that:

- ✅ Reads Parquet files directly from S3/MinIO using PyArrow
- ✅ Performs all aggregation logic in Python/Pandas
- ✅ Writes results directly to PostgreSQL
- ✅ Achieves **100% Trino parity** (23/23 E2E test scenarios passing)

### Supported Modes

| Mode | Description | Status |
|------|-------------|--------|
| **OCP-only** | OpenShift pod/storage aggregation | ✅ Production Ready |
| **OCP-on-AWS** | OCP + AWS cost attribution | ✅ Production Ready |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Before: Trino + Hive                          │
│                                                                         │
│   S3 ◄──► Trino ◄──► Hive Metastore ◄──► Metastore DB (PostgreSQL)     │
│              │                                                          │
│              ▼                                                          │
│           MASU ──► PostgreSQL (reporting tables)                        │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         After: POC Aggregator                           │
│                                                                         │
│   S3/MinIO ──► POC Aggregator (Python) ──► PostgreSQL                  │
│                      │                                                  │
│                      ├── PyArrow (Parquet reading)                     │
│                      ├── Pandas (Aggregation)                          │
│                      └── psycopg2 (DB writes)                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Benefits

- **Fewer components**: 3 vs 6 (removes Trino, Hive Metastore, Metastore DB)
- **Simpler operations**: Single Python process instead of distributed JVM services
- **Direct writes**: S3 → Aggregator → PostgreSQL (no intermediate S3 writes)

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker/Podman (for MinIO + PostgreSQL)
- `pip install -r requirements.txt`

### 1. Start Infrastructure

```bash
podman-compose up -d
```

### 2. Run OCP Aggregation

```bash
# Required - must match S3 folder structure: data/{ORG_ID}/OCP/source={UUID}/...
export OCP_PROVIDER_UUID="00000000-0000-0000-0000-000000000001"
export OCP_CLUSTER_ID="my-cluster"

# S3/MinIO connection
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"

# PostgreSQL
export POSTGRES_PASSWORD="koku123"

# Optional (have defaults)
export POC_YEAR=2025
export POC_MONTH=01

python -m src.main
```

### 3. Run OCP-on-AWS Aggregation

```bash
# Same as above, plus AWS provider (must match S3 folder: data/{ORG_ID}/AWS/source={UUID}/...)
export AWS_PROVIDER_UUID="00000000-0000-0000-0000-000000000002"

python -m src.main
```

> **Note**: Provider UUIDs must match the folder structure in S3 where Parquet files are stored.
> The aggregation mode is determined automatically based on whether `AWS_PROVIDER_UUID` is set.

---

## Documentation

| Document | Description |
|----------|-------------|
| **[Architecture](docs/architecture/ARCHITECTURE.md)** | Technical architecture overview |
| **[Matching Labels](docs/MATCHING_LABELS.md)** | Trino vs POC feature parity reference |
| **[Benchmark Guide](docs/guides/BENCHMARK_HOWTO.md)** | How to run benchmarks |
| **[OCP Benchmark Plan](docs/benchmarks/OCP_BENCHMARK_PLAN.md)** | OCP-only benchmark methodology |
| **[OCP-on-AWS Benchmark Plan](docs/benchmarks/OCP_ON_AWS_BENCHMARK_PLAN.md)** | OCP-on-AWS benchmark methodology |
| **[OCP-on-AWS Benchmark Results](docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md)** | Performance results |
| **[Developer Quickstart](docs/guides/DEVELOPER_QUICKSTART.md)** | Getting started guide |

### Additional Resources

```
docs/
├── architecture/       # System architecture
├── benchmarks/         # Performance benchmarks
├── analysis/           # Technical analysis docs
├── guides/             # How-to guides
└── ocp_on_aws/        # OCP-on-AWS specific docs
```

---

## Benchmark Results

### OCP-on-AWS Performance (In-Memory, Industry Standard)

Results from 3 runs per scale, reporting median ± stddev:

| Output Rows | Time (s) | Memory (MB) | Throughput |
|-------------|----------|-------------|------------|
| 6,720 | 3.52 ±0.01 | 224 ±16 | 1,909 rows/s |
| 33,600 | 12.74 ±0.07 | 470 ±11 | 2,637 rows/s |
| 166,656 | 59.67 ±0.38 | 1,748 ±33 | 2,792 rows/s |
| 333,312 | 120.97 ±0.22 | 3,304 ±107 | 2,755 rows/s |
| 499,968 | 184.10 ±0.34 | 4,924 ±22 | 2,715 rows/s |
| 666,624 | 249.18 ±0.78 | 6,215 ±27 | 2,675 rows/s |

> **Methodology**: 3 runs per scale, continuous 100ms memory sampling.

**Memory Scaling**: ~9 MB per 1K output rows (linear)

### OCP-Only Performance (In-Memory)

| Output Rows | Time (s) | Memory (MB) | Throughput |
|-------------|----------|-------------|------------|
| 420 | 2.52 ±0.06 | 253 ±1 | 167 rows/s |
| 2,085 | 8.13 ±0.07 | 502 ±3 | 257 rows/s |
| 10,430 | 37.17 ±0.03 | 1,969 ±17 | 281 rows/s |
| 20,850 | 72.37 ±0.19 | 3,729 ±69 | 288 rows/s |
| 41,650 | 139.19 ±0.77 | 7,184 ±29 | 299 rows/s |

**Memory Scaling**: ~170 MB per 1K output rows (linear)

See [OCP_ON_AWS_BENCHMARK_RESULTS.md](docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) and [OCP_BENCHMARK_RESULTS.md](docs/benchmarks/OCP_BENCHMARK_RESULTS.md) for details.

---

## Test Coverage

### E2E Test Scenarios: 23/23 Passing ✅

| Category | Scenarios | Status |
|----------|-----------|--------|
| Basic Attribution | 1-4 | ✅ Pass |
| Multi-Cluster | 5-8 | ✅ Pass |
| Tag Matching | 9-12 | ✅ Pass |
| Network Costs | 13-15 | ✅ Pass |
| Storage Attribution | 16-22 | ✅ Pass |
| Edge Cases | 23 | ✅ Pass |

See [MATCHING_LABELS.md](docs/MATCHING_LABELS.md) for detailed test mapping.

---

## Configuration

```yaml
# config/config.yaml
cost:
  distribution:
    method: cpu  # cpu, memory, or weighted

performance:
  max_workers: 4
  use_streaming: false  # Enable for large OCP-only datasets
  use_bulk_copy: true   # Faster PostgreSQL writes
```

---

## Running Tests

### Unit Tests (no infrastructure needed)

```bash
# All unit tests
pytest tests/ -v

# Specific component tests
pytest tests/test_cost_attributor.py -v      # Cost attribution logic
pytest tests/test_resource_matcher.py -v     # EC2/EBS matching
pytest tests/test_tag_matcher.py -v          # OpenShift tag matching
pytest tests/test_network_cost_handler.py -v # Network cost detection
```

### Integration Tests (requires MinIO + PostgreSQL)

```bash
# Start infrastructure first
podman-compose up -d

# OCP-on-AWS integration tests
pytest tests/test_ocp_aws_integration.py -v

# Storage integration tests
pytest tests/test_storage_integration.py -v
```

### E2E Tests (full pipeline validation)

```bash
# OCP-on-AWS E2E scenarios (23 scenarios)
./scripts/run_ocp_aws_scenario_tests.sh --all

# Run specific scenario
./scripts/run_ocp_aws_scenario_tests.sh --scenario 1

# OCP-only tests
./scripts/run_ocp_tests.sh
```

### Benchmarks

```bash
# OCP-on-AWS benchmarks (multiple scales)
./scripts/run_ocp_aws_benchmarks.sh --all

# OCP-only benchmark
./scripts/run_ocp_benchmarks.sh
```

---

## Project Structure

```
poc-parquet-aggregator/
├── src/
│   ├── main.py                 # Entry point
│   ├── aggregator_pod.py       # OCP pod aggregation
│   ├── aggregator_ocp_aws.py   # OCP-on-AWS aggregation
│   ├── cost_attributor.py      # Cost attribution logic
│   ├── resource_matcher.py     # EC2/EBS matching
│   ├── tag_matcher.py          # OpenShift tag matching
│   ├── parquet_reader.py       # S3/Parquet reading
│   └── db_writer.py            # PostgreSQL writer
├── tests/                       # Unit and integration tests
├── scripts/                     # Utility scripts
├── config/                      # Configuration files
└── docs/                        # Documentation
```

---

## Contributing

### Before Committing

```bash
# 1. Run unit tests (fast, no infrastructure needed)
pytest tests/ -v

# 2. Run OCP-only tests (if infrastructure available)
./scripts/run_ocp_tests.sh

# 3. Run E2E tests for any changed OCP-on-AWS functionality
./scripts/run_ocp_aws_scenario_tests.sh --all
```

### Code Style

- Python 3.12+ required
- Follow existing patterns in the codebase
- Update documentation for new features

### CI Pipeline

GitHub Actions runs automatically on push/PR:

| Job | Description |
|-----|-------------|
| **Lint** | Black, isort, flake8 checks |
| **Build** | Verify imports and dependencies |
| **Unit Tests** | Fast tests (no infrastructure) |
| **Integration Tests** | Tests with MinIO + PostgreSQL |
| **E2E OCP** | OCP-only end-to-end tests |
| **E2E OCP-on-AWS** | OCP-on-AWS end-to-end tests |

---

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
