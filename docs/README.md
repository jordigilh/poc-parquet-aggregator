# Documentation Index

This directory contains all documentation for the POC Parquet Aggregator project.

## Directory Structure

```
docs/
├── ocp-only/           # OCP-only aggregation
│   ├── README.md
│   └── MATCHING_LABELS.md
├── ocp-on-aws/         # OCP-on-AWS cost attribution
│   ├── README.md
│   └── MATCHING_LABELS.md
├── architecture/       # System architecture
│   └── ARCHITECTURE.md
├── benchmarks/         # Performance benchmarks
│   ├── BENCHMARK_RESULTS_TEMPLATE.md
│   ├── OCP_BENCHMARK_PLAN.md
│   ├── OCP_BENCHMARK_RESULTS.md
│   ├── OCP_ON_AWS_BENCHMARK_PLAN.md
│   └── OCP_ON_AWS_BENCHMARK_RESULTS.md
└── guides/             # How-to guides
    ├── DEVELOPER_QUICKSTART.md
    └── BENCHMARK_HOWTO.md
```

---

## Quick Links

### By Scenario

| Scenario | Overview | Matching Labels | Benchmark Plan | Results |
|----------|----------|-----------------|----------------|---------|
| **OCP-only** | [README](ocp-only/README.md) | [MATCHING_LABELS](ocp-only/MATCHING_LABELS.md) | [Plan](benchmarks/OCP_BENCHMARK_PLAN.md) | [Results](benchmarks/OCP_BENCHMARK_RESULTS.md) |
| **OCP-on-AWS** | [README](ocp-on-aws/README.md) | [MATCHING_LABELS](ocp-on-aws/MATCHING_LABELS.md) | [Plan](benchmarks/OCP_ON_AWS_BENCHMARK_PLAN.md) | [Results](benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) |

### Essential Reading

| Document | Description |
|----------|-------------|
| [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | System architecture overview |
| [guides/DEVELOPER_QUICKSTART.md](guides/DEVELOPER_QUICKSTART.md) | Getting started for developers |
| [guides/BENCHMARK_HOWTO.md](guides/BENCHMARK_HOWTO.md) | How to run benchmarks |

### Benchmark Results

| Document | Description |
|----------|-------------|
| [OCP_BENCHMARK_RESULTS.md](benchmarks/OCP_BENCHMARK_RESULTS.md) | OCP-only performance results |
| [OCP_ON_AWS_BENCHMARK_RESULTS.md](benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) | OCP-on-AWS performance results |

---

## Finding What You Need

| Question | Where to Look |
|----------|---------------|
| How does the POC work? | [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) |
| OCP-only Trino parity? | [ocp-only/MATCHING_LABELS.md](ocp-only/MATCHING_LABELS.md) |
| OCP-on-AWS Trino parity? | [ocp-on-aws/MATCHING_LABELS.md](ocp-on-aws/MATCHING_LABELS.md) |
| OCP-only performance? | [benchmarks/OCP_BENCHMARK_RESULTS.md](benchmarks/OCP_BENCHMARK_RESULTS.md) |
| OCP-on-AWS performance? | [benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md](benchmarks/OCP_ON_AWS_BENCHMARK_RESULTS.md) |
| How do I run benchmarks? | [guides/BENCHMARK_HOWTO.md](guides/BENCHMARK_HOWTO.md) |
| How do I set up locally? | [guides/DEVELOPER_QUICKSTART.md](guides/DEVELOPER_QUICKSTART.md) |

---

*Last Updated: November 27, 2025*
