# OCP-Only Benchmark Results

**Date**: November 26, 2025
**Environment**: MacBook Pro M2 Max (12 cores), 32GB RAM, 1TB SSD, podman containers (PostgreSQL + MinIO)
**Methodology**: 3 runs per scale, median ± stddev, continuous 100ms memory sampling

## Table of Contents

1. [Summary](#summary)
2. [Scale Interpretation](#scale-interpretation)
3. [Detailed Results](#detailed-results)
4. [Performance Analysis](#performance-analysis)
5. [Memory Analysis](#memory-analysis)
6. [Production Fit Analysis](#production-fit-analysis)

---

## Summary

| Scale | Input Rows | Output Rows | Time (s) | Memory (MB) | Throughput |
|-------|------------|-------------|----------|-------------|------------|
| **20k** | 20,406 | 830 | 4.35 ± 0.06 | 328 ± 4 | 191 rows/s |
| **50k** | 50,886 | 2,080 | 8.49 ± 0.10 | 510 ± 3 | 245 rows/s |
| **100k** | 101,766 | 4,160 | 15.60 ± 0.03 | 839 ± 8 | 267 rows/s |
| **250k** | 254,408 | 10,400 | 37.01 ± 0.62 | 1,964 ± 22 | 281 rows/s |
| **500k** | 508,810 | 20,800 | 72.04 ± 1.55 | 3,689 ± 32 | 289 rows/s |
| **1m** | 1,017,615 | 41,600 | 139.67 ± 2.47 | 7,171 ± 493 | 298 rows/s |
| **1.5m** | 1,526,420 | 62,400 | 208.55 ± 1.61 | 8,600 ± 302 | 299 rows/s |
| **2m** | 2,035,225 | 83,200 | 282.76 ± 3.14 | 10,342 ± 292 | 294 rows/s |

> **Note**: Scale names (20k, 50k, etc.) refer to **INPUT rows** (hourly data from nise).
> **Throughput** = Output Rows / Time (calculated from median values)

---

## Scale Interpretation

What does each scale represent in a production environment?

| Scale | Input Rows | Output Rows | Cluster Size | Use Case Example |
|-------|------------|-------------|--------------|------------------|
| **20k** | ~20,000 | 830 | 10 nodes, ~830 pods | Small production cluster |
| **50k** | ~50,000 | 2,080 | 20 nodes, ~2,080 pods | Medium production environment |
| **100k** | ~100,000 | 4,160 | 40 nodes, ~4,160 pods | Large enterprise deployment |
| **250k** | ~250,000 | 10,400 | 100 nodes, ~10,400 pods | Multi-cluster enterprise |
| **500k** | ~500,000 | 20,800 | 200 nodes, ~20,800 pods | Very large enterprise |
| **1m** | ~1,000,000 | 41,600 | 400 nodes, ~41,600 pods | Hyperscale platform |
| **1.5m** | ~1,500,000 | 62,400 | 600 nodes, ~62,400 pods | Major cloud provider scale |
| **2m** | ~2,000,000 | 83,200 | 800 nodes, ~83,200 pods | Maximum tested scale |

> **Key**: 
> - **Input Rows** = Pods × 24 hours (hourly data from nise)
> - **Output Rows** = Daily aggregated summaries (one per pod/namespace/node)
> - **Scale names now match input rows** (e.g., "20k" = ~20,000 input rows)

---

## Detailed Results

### Raw Run Data

| Scale | Run | Output Rows | Time (s) | Memory (MB) |
|-------|-----|-------------|----------|-------------|
| 20k | 1 | 830 | 4.31 | 328 |
| 20k | 2 | 830 | 4.35 | 330 |
| 20k | 3 | 830 | 4.42 | 322 |
| 50k | 1 | 2,080 | 8.49 | 507 |
| 50k | 2 | 2,080 | 8.59 | 510 |
| 50k | 3 | 2,080 | 8.40 | 512 |
| 100k | 1 | 4,160 | 15.62 | 844 |
| 100k | 2 | 4,160 | 15.60 | 829 |
| 100k | 3 | 4,160 | 15.57 | 839 |
| 250k | 1 | 10,400 | 36.79 | 1,997 |
| 250k | 2 | 10,400 | 37.95 | 1,955 |
| 250k | 3 | 10,400 | 37.01 | 1,964 |
| 500k | 1 | 20,800 | 72.04 | 3,689 |
| 500k | 2 | 20,800 | 71.62 | 3,722 |
| 500k | 3 | 20,800 | 74.49 | 3,659 |
| 1m | 1 | 41,600 | 143.58 | 6,322 |
| 1m | 2 | 41,600 | 139.67 | 7,180 |
| 1m | 3 | 41,600 | 139.00 | 7,171 |
| 1.5m | 1 | 62,400 | 211.29 | 8,097 |
| 1.5m | 2 | 62,400 | 208.44 | 8,638 |
| 1.5m | 3 | 62,400 | 208.55 | 8,600 |
| 2m | 1 | 83,200 | 277.34 | 10,342 |
| 2m | 2 | 83,200 | 282.81 | 10,374 |
| 2m | 3 | 83,200 | 282.76 | 9,853 |

---

## Performance Analysis

### Processing Time Scaling

```
Time (s) vs Input Rows (linear scaling observed):
- 20k input:  4.35s   → ~0.21ms per input row
- 2m input:   282.76s → ~0.14ms per input row

Observation: Efficiency improves at scale due to fixed overhead amortization.
```

### Throughput Consistency

Throughput remains consistent across scales (~260-300 output rows/sec), demonstrating:
- ✅ Linear scalability
- ✅ No performance degradation at larger scales
- ✅ Predictable resource requirements

---

## Memory Analysis

### Memory Scaling

| Scale | Input Rows | Output Rows | Memory (MB) | MB per 1K Input |
|-------|------------|-------------|-------------|-----------------|
| 20k | 20,406 | 830 | 328 | 16.1 |
| 50k | 50,886 | 2,080 | 510 | 10.0 |
| 100k | 101,766 | 4,160 | 839 | 8.2 |
| 250k | 254,408 | 10,400 | 1,964 | 7.7 |
| 500k | 508,810 | 20,800 | 3,689 | 7.2 |
| 1m | 1,017,615 | 41,600 | 7,171 | 7.0 |
| 1.5m | 1,526,420 | 62,400 | 8,600 | 5.6 |
| 2m | 2,035,225 | 83,200 | 10,342 | 5.1 |

**Key Insight**: Memory efficiency improves at scale (~5-7 MB per 1K input rows at production scale).

### Memory Formula

```
Estimated Memory (MB) ≈ 200 + (Input Rows × 0.005)

Examples:
- 500,000 input: 200 + 2,500 = ~2,700 MB
- 2,000,000 input: 200 + 10,000 = ~10,200 MB ✓
```

---

## Production Fit Analysis

### Memory Requirements

| Scenario | Input Rows | Est. Memory | Fits in 32GB? |
|----------|------------|-------------|---------------|
| Small customer | 100,000 | ~1 GB | ✅ Yes (3%) |
| Medium customer | 500,000 | ~4 GB | ✅ Yes (13%) |
| Large customer | 1,000,000 | ~7 GB | ✅ Yes (22%) |
| Very large | 2,000,000 | ~10 GB | ✅ Yes (31%) |
| Maximum tested | 2,000,000 | 10,342 MB | ✅ Yes (32%) |
| Projected max | 6,000,000 | ~31 GB | ✅ Yes (97%) |

### Conclusions

1. **Memory-efficient**: OCP-only aggregation uses ~5-7MB per 1K input rows at scale
2. **Scalable**: Linear time scaling with consistent throughput (~280-300 output rows/sec)
3. **Production-ready**: Comfortably handles 2M+ input rows within 32GB
4. **Input Row Alignment**: Scale names now correctly reflect input row counts

---

## Comparison with OCP-on-AWS

| Metric | OCP-Only | OCP-on-AWS |
|--------|----------|------------|
| Throughput | ~280-300 output rows/s | ~2,500-2,800 output rows/s |
| Memory per 1K input | ~5-7 MB | ~3-4 MB |
| Complexity | Simple aggregation | JOIN + matching |

**Note**: OCP-on-AWS has higher throughput due to different output row calculation (daily aggregation vs hourly).

---

*Generated by automated benchmark suite on November 26, 2025*
