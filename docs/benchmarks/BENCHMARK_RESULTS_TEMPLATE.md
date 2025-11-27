# {SCENARIO_NAME} Benchmark Results

**Date**: {DATE}  
**Environment**: {MACHINE_SPECS}  
**Methodology**: 3 runs per scale, median ± stddev, continuous 100ms memory sampling

## Table of Contents

1. [Summary](#summary)
2. [Scale Interpretation](#scale-interpretation)
3. [Detailed Results](#detailed-results)
4. [Performance Analysis](#performance-analysis)
5. [Memory Analysis](#memory-analysis)
6. [Visualizations](#visualizations)
7. [Production Fit Analysis](#production-fit-analysis)
8. [Key Insights](#key-insights)
9. [Comparison with {OTHER_SCENARIO}](#comparison-with-{other_scenario_anchor})

---

## Summary

| Scale | Input Rows | Output Rows | Time (s) | Memory (MB) | Throughput |
|-------|------------|-------------|----------|-------------|------------|
| **20k** | {INPUT} | {OUTPUT} | {TIME} ± {STDDEV} | {MEM} ± {STDDEV} | {THROUGHPUT} rows/s |
| **50k** | ... | ... | ... | ... | ... |
| **100k** | ... | ... | ... | ... | ... |
| **250k** | ... | ... | ... | ... | ... |
| **500k** | ... | ... | ... | ... | ... |
| **1m** | ... | ... | ... | ... | ... |
| **1.5m** | ... | ... | ... | ... | ... |
| **2m** | ... | ... | ... | ... | ... |

> **Scale names** refer to input rows (hourly data). E.g., "20k" = ~20,000 input rows.  
> **Throughput** = Output Rows / Time (calculated from median values)

---

## Scale Interpretation

| Scale | Input Rows | Output Rows | Cluster Size | Use Case |
|-------|------------|-------------|--------------|----------|
| **20k** | ~20,000 | {OUTPUT} | {NODES} nodes, ~{PODS} pods | {USE_CASE} |
| **50k** | ~50,000 | ... | ... | ... |
| **100k** | ~100,000 | ... | ... | ... |
| **250k** | ~250,000 | ... | ... | ... |
| **500k** | ~500,000 | ... | ... | ... |
| **1m** | ~1,000,000 | ... | ... | ... |
| **1.5m** | ~1,500,000 | ... | ... | ... |
| **2m** | ~2,000,000 | ... | ... | ... |

> **Input Rows** = {INPUT_FORMULA}  
> **Output Rows** = {OUTPUT_FORMULA}

---

## Detailed Results

### Raw Run Data

| Scale | Run | Output Rows | Time (s) | Memory (MB) |
|-------|-----|-------------|----------|-------------|
| 20k | 1 | ... | ... | ... |
| 20k | 2 | ... | ... | ... |
| 20k | 3 | ... | ... | ... |
| ... | ... | ... | ... | ... |

---

## Performance Analysis

### Processing Time Scaling

| Scale | Time per Input Row |
|-------|-------------------|
| 20k | {TIME_PER_ROW} ms |
| 2m | {TIME_PER_ROW} ms |

**Observation**: {SCALING_OBSERVATION}

### Throughput Consistency

| Scale | Throughput (rows/s) |
|-------|---------------------|
| 20k | ... |
| 50k | ... |
| 100k | ... |
| 250k | ... |
| 500k | ... |
| 1m | ... |
| 1.5m | ... |
| 2m | ... |

**Average throughput**: ~{AVG_THROUGHPUT} output rows/second

---

## Memory Analysis

### Memory Scaling

| Scale | Input Rows | Memory (MB) | MB per 1K Input |
|-------|------------|-------------|-----------------|
| 20k | ~20,000 | ... | ... |
| 50k | ~50,000 | ... | ... |
| 100k | ~100,000 | ... | ... |
| 250k | ~250,000 | ... | ... |
| 500k | ~500,000 | ... | ... |
| 1m | ~1,000,000 | ... | ... |
| 1.5m | ~1,500,000 | ... | ... |
| 2m | ~2,000,000 | ... | ... |

**Key Insight**: {MEMORY_INSIGHT}

### Memory Formula

```
Estimated Memory (MB) ≈ {BASE} + (Input Rows × {COEFFICIENT})

Examples:
- 500,000 input:   {BASE} + {CALC} = ~{RESULT} MB
- 2,000,000 input: {BASE} + {CALC} = ~{RESULT} MB ✓
```

---

## Visualizations

### Processing Time vs Input Rows

```mermaid
xychart-beta
    title "Processing Time vs Input Rows"
    x-axis "Input Rows" [20K, 50K, 100K, 250K, 500K, 1M, 1.5M, 2M]
    y-axis "Time (seconds)" 0 --> {MAX_TIME}
    bar "Time" [{TIME_VALUES}]
```

### Memory Usage vs Input Rows

```mermaid
xychart-beta
    title "Peak Memory Usage vs Input Rows"
    x-axis "Input Rows" [20K, 50K, 100K, 250K, 500K, 1M, 1.5M, 2M]
    y-axis "Memory (MB)" 0 --> {MAX_MEMORY}
    bar "Memory" [{MEMORY_VALUES}]
```

### Throughput vs Scale

```mermaid
xychart-beta
    title "Throughput (rows/sec) vs Scale"
    x-axis "Input Rows" [20K, 50K, 100K, 250K, 500K, 1M, 1.5M, 2M]
    y-axis "Rows/Second" 0 --> {MAX_THROUGHPUT}
    line "Throughput" [{THROUGHPUT_VALUES}]
```

---

## Production Fit Analysis

### Measured Memory (from benchmarks)

| Scale | Input Rows | Memory (Measured) | % of 32GB |
|-------|------------|-------------------|-----------|
| 100k | ~100,000 | {MEASURED_100K} MB | {PCT}% |
| 500k | ~500,000 | {MEASURED_500K} MB | {PCT}% |
| 1m | ~1,000,000 | {MEASURED_1M} MB | {PCT}% |
| 2m | ~2,000,000 | {MEASURED_2M} MB | {PCT}% |

### Conclusions

1. **Memory-efficient**: ~{MB_PER_1K} MB per 1K input rows at production scale
2. **Scalable**: {SCALING_TYPE} time scaling with consistent throughput (~{THROUGHPUT} rows/sec)
3. **Production-ready**: Handles 2M input rows using only {MAX_PCT}% of 32GB capacity

---

## Key Insights

> **IMPORTANT**: This section provides analytical observations about the benchmark data.
> Every benchmark results document MUST include this section with scenario-specific analysis.

### 1. Memory Scaling Behavior

Analyze how memory scales with input size:

| Scale Transition | Memory Change | Interpretation |
|------------------|---------------|----------------|
| 1M → 1.5M | +{DELTA} MB | {LINEAR/PLATEAU/SUBLINEAR} |
| 1.5M → 2M | +{DELTA} MB | {INTERPRETATION} |

**Questions to answer**:
- Does memory scale linearly, sub-linearly, or plateau?
- Are there fixed structures dominating memory (e.g., AWS data for JOINs)?
- Is the growth rate predictable?

### 2. Throughput Trends

Analyze throughput behavior across scales:

| Scale Range | Throughput Change | Interpretation |
|-------------|-------------------|----------------|
| Small (20k-100k) | {CHANGE}% | {INTERPRETATION} |
| Medium (100k-500k) | {CHANGE}% | {INTERPRETATION} |
| Large (500k-2m) | {CHANGE}% | {INTERPRETATION} |

**Questions to answer**:
- Does throughput increase, decrease, or plateau at scale?
- What explains the trend (fixed overhead amortization, I/O limits, aggregation limits)?
- Is throughput predictable for capacity planning?

### 3. Variance Analysis

Analyze measurement stability:

| Scale | Time StdDev | Memory StdDev | Interpretation |
|-------|-------------|---------------|----------------|
| Small scales | {VALUE} | {VALUE} | {INTERPRETATION} |
| Large scales | {VALUE} | {VALUE} | {INTERPRETATION} |

**Questions to answer**:
- Are measurements reproducible (low variance)?
- Does variance change with scale?
- Are there outliers that need explanation?

### 4. Prediction Confidence

Summarize confidence in extrapolating beyond tested scales:

| Metric | Confidence | Reasoning |
|--------|------------|-----------|
| **Time** | {HIGH/MEDIUM/LOW} | {REASONING} |
| **Memory** | {HIGH/MEDIUM/LOW} | {REASONING} |

**Prediction formulas** (if applicable):
```
Time (s) ≈ {FORMULA}
Memory (MB) ≈ {FORMULA}
```

### 5. Scenario-Specific Observations

Include any observations unique to this scenario:
- Why is throughput higher/lower than other scenarios?
- What explains memory differences?
- Are there architectural implications (e.g., JOINs, aggregations)?

---

## Comparison with {OTHER_SCENARIO}

| Metric | {THIS_SCENARIO} | {OTHER_SCENARIO} |
|--------|-----------------|------------------|
| Throughput | ~{THIS_THROUGHPUT} rows/s | ~{OTHER_THROUGHPUT} rows/s |
| Memory per 1K input | ~{THIS_MEM} MB | ~{OTHER_MEM} MB |
| Output type | {THIS_OUTPUT_TYPE} | {OTHER_OUTPUT_TYPE} |
| Complexity | {THIS_COMPLEXITY} | {OTHER_COMPLEXITY} |

> {COMPARISON_NOTE}

---

*Generated by automated benchmark suite*
