# POC: Parquet Aggregator for Cost Management

> **Replace Trino + Hive with Python-based Parquet aggregation for on-prem deployments**

[![CI](https://github.com/insights-onprem/poc-parquet-aggregator/actions/workflows/ci.yml/badge.svg)](https://github.com/insights-onprem/poc-parquet-aggregator/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)](docs/architecture/ARCHITECTURE.md)
[![OCP](https://img.shields.io/badge/OCP-20%2F20%20Passing-brightgreen)](docs/ocp-only/MATCHING_LABELS.md)
[![OCP--on--AWS](https://img.shields.io/badge/OCP--on--AWS-23%2F23%20Passing-brightgreen)](docs/ocp-on-aws/MATCHING_LABELS.md)

---

## Overview

This POC demonstrates replacing **Trino + Hive** with a custom Python aggregation layer that:

- ✅ Reads Parquet files directly from S3/MinIO using PyArrow
- ✅ Performs all aggregation logic in Python/Pandas
- ✅ Writes results directly to PostgreSQL
- ✅ Achieves **100% Trino parity** (43 E2E test scenarios passing: 20 OCP + 23 OCP-on-AWS)

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
| **[OCP-only Matching Labels](docs/ocp-only/MATCHING_LABELS.md)** | OCP-only Trino vs POC feature parity |
| **[OCP-on-AWS Matching Labels](docs/ocp-on-aws/MATCHING_LABELS.md)** | OCP-on-AWS Trino vs POC feature parity |
| **[Benchmark Guide](docs/guides/BENCHMARK_HOWTO.md)** | How to run benchmarks |
| **[OCP Benchmark Plan](docs/benchmarks/OCP_BENCHMARK_PLAN.md)** | OCP-only benchmark methodology |
| **[OCP-on-AWS Benchmark Plan](docs/benchmarks/OCP_ON_AWS_BENCHMARK_PLAN.md)** | OCP-on-AWS benchmark methodology |
| **[OCP Benchmark Results](docs/benchmarks/OCP_BENCHMARK_RESULTS.md)** | OCP-only performance results |
| **[OCP-on-AWS Benchmark Results](docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md)** | OCP-on-AWS performance results |
| **[Developer Quickstart](docs/guides/DEVELOPER_QUICKSTART.md)** | Getting started guide |

### Additional Resources

```
docs/
├── architecture/       # System architecture
├── benchmarks/         # Performance benchmarks
├── guides/             # How-to guides
├── ocp-only/           # OCP-only specific docs
└── ocp-on-aws/         # OCP-on-AWS specific docs
```

---

## Benchmark Results

### OCP-on-AWS Performance

Results from 3 runs per scale, reporting median ± stddev:

| Scale | Input Rows | Output Rows | Time (s) | Memory (MB) | Throughput |
|-------|------------|-------------|----------|-------------|------------|
| 20k | ~20,000 | 19,920 | 7.99 ± 0.03 | 381 ± 13 | 2,493 rows/s |
| 100k | ~100,000 | 99,840 | 34.10 ± 0.06 | 1,108 ± 38 | 2,927 rows/s |
| 500k | ~500,000 | 499,200 | 166.84 ± 1.27 | 4,188 ± 440 | 2,992 rows/s |
| 1m | ~1,000,000 | 998,400 | 334.29 ± 2.22 | 6,862 ± 379 | 2,986 rows/s |
| 2m | ~2,000,000 | 1,996,800 | 640.26 ± 11.54 | 7,326 ± 122 | 3,118 rows/s |

**Memory Scaling**: ~4-7 MB per 1K input rows at production scale

### OCP-Only Performance

| Scale | Input Rows | Output Rows | Time (s) | Memory (MB) | Throughput |
|-------|------------|-------------|----------|-------------|------------|
| 20k | ~20,000 | 830 | 4.35 ± 0.06 | 328 ± 4 | 191 rows/s |
| 100k | ~100,000 | 4,160 | 15.60 ± 0.03 | 839 ± 8 | 267 rows/s |
| 500k | ~500,000 | 20,800 | 72.04 ± 1.55 | 3,689 ± 32 | 289 rows/s |
| 1m | ~1,000,000 | 41,600 | 139.67 ± 2.47 | 7,171 ± 493 | 298 rows/s |
| 2m | ~2,000,000 | 83,200 | 282.76 ± 3.14 | 10,342 ± 292 | 294 rows/s |

**Memory Scaling**: ~5-7 MB per 1K input rows at production scale

See [OCP_ON_AWS_BENCHMARK_RESULTS.md](docs/benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) and [OCP_BENCHMARK_RESULTS.md](docs/benchmarks/OCP_BENCHMARK_RESULTS.md) for full details.

---

## Test Coverage

### E2E Test Scenarios: 43 Passing ✅

| Mode | Scenarios | Status |
|------|-----------|--------|
| **OCP-only** | 20/20 | ✅ Pass |
| **OCP-on-AWS** | 23/23 | ✅ Pass |

See [OCP-only MATCHING_LABELS](docs/ocp-only/MATCHING_LABELS.md) and [OCP-on-AWS MATCHING_LABELS](docs/ocp-on-aws/MATCHING_LABELS.md) for detailed test mapping.

---

## Configuration

```yaml
# config/config.yaml
cost:
  distribution:
    method: cpu  # cpu, memory, or weighted

performance:
  max_workers: 4
  use_streaming: false  # Not recommended (see benchmark plans)
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
