# IQE Test Script vs Benchmark Scripts - Key Differences

## The Core Difference

### ✅ IQE Tests (WORKING - 18/18 passing)
```bash
# From run_iqe_validation.sh line 106
python3 -m src.main --truncate
```

**Calls**: The actual POC code directly (`src.main`)

### ❌ Benchmark Scripts (FAILING)
```bash
# From run_comprehensive_scale_benchmarks.sh
python3 scripts/benchmark_performance.py \
    --provider-uuid "${PROVIDER_UUID}" \
    --year "2025" \
    --month "${MONTH}"
```

**Calls**: A wrapper script (`benchmark_performance.py`) that then calls `src.main`

## Why This Matters

### IQE Script Architecture (Simple)
```
run_iqe_validation.sh
    ├── Generate nise data
    ├── Convert to Parquet
    ├── Call: python3 -m src.main --truncate
    └── Validate results
```

**Layers**: 1 (direct call to POC)

### Benchmark Script Architecture (Complex)
```
run_comprehensive_scale_benchmarks.sh
    ├── Generate nise data
    ├── Convert to Parquet
    ├── Modify config.yaml dynamically
    └── Call: python3 scripts/benchmark_performance.py
            └── Which calls: src.main
```

**Layers**: 2 (wrapper → POC)

## Specific Differences

### 1. How They Run the POC

**IQE Tests**:
```bash
# Line 106 in run_iqe_validation.sh
python3 -m src.main --truncate
```

**Benchmarks**:
```bash
# Line 190+ in run_comprehensive_scale_benchmarks.sh
python3 "${SCRIPT_DIR}/benchmark_performance.py" \
    --provider-uuid "${PROVIDER_UUID}" \
    --year "2025" \
    --month "${MONTH}" \
    --output "${BENCHMARK_OUTPUT}"
```

### 2. Config Handling

**IQE Tests**:
- Uses `config.yaml` as-is
- No dynamic modification
- Relies on environment variables

**Benchmarks**:
- Tries to modify `config.yaml` on the fly
- Backs up and restores config
- Uses Python embedded in bash to update YAML
- More points of failure

### 3. Environment Variables

**IQE Tests** (from lines 22-35):
```bash
export S3_ENDPOINT=http://localhost:9000
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
export S3_BUCKET=cost-management
export POSTGRES_HOST=localhost
export POSTGRES_DB=koku
export POSTGRES_USER=koku
export POSTGRES_PASSWORD=koku123
export POSTGRES_SCHEMA=org${ORG_ID}
export OCP_PROVIDER_UUID=${PROVIDER_UUID}
export OCP_CLUSTER_ID=${CLUSTER_ID}
export ORG_ID=${ORG_ID}
export PROVIDER_TYPE=OCP
export IQE_YAML_FILE="config/${IQE_YAML}"
```

**Benchmarks**:
- Same variables PLUS
- `OCP_CLUSTER_ALIAS`
- `POC_YEAR` and `POC_MONTH` (in addition to `OCP_YEAR` and `OCP_MONTH`)
- More complexity = more failure points

### 4. What They Measure

**IQE Tests**:
- ✅ Correctness (expected vs actual values)
- ✅ All 18 scenarios
- ✅ Validates aggregation logic
- ❌ No performance metrics

**Benchmarks**:
- ❌ No correctness validation
- ✅ Performance metrics (time, memory)
- ✅ Streaming vs non-streaming comparison
- Complex metrics collection

## The Problem with benchmark_performance.py

### Why It Fails

The `benchmark_performance.py` script:

1. **Loads config first**:
   ```python
   config = get_config(args.config)  # Line 292
   ```

2. **Config loader requires ALL variables**:
   ```python
   # From config_loader.py
   # Fails if any ${VAR} in config.yaml is not set
   ```

3. **More variables than IQE tests need**:
   - `OCP_CLUSTER_ALIAS`
   - All S3 variables
   - All PostgreSQL variables
   - Timing issues with when they're set

4. **Then wraps the actual POC call**:
   ```python
   # Inside benchmark_performance.py
   # Eventually calls the same code as IQE tests
   # But with extra layers
   ```

## Why IQE Tests Work

### Key Success Factors

1. **Direct call**: No wrapper layers
2. **Simple**: Just runs the POC
3. **Proven**: Used for months/years
4. **Minimal dependencies**: Only what POC needs
5. **No config modification**: Uses config as-is

## The Solution

### Option 1: Use IQE Script for Benchmarking (SIMPLE)

**Modify run_iqe_validation.sh to collect metrics**:

```bash
# Around line 106, change from:
python3 -m src.main --truncate

# To:
/usr/bin/time -l python3 -m src.main --truncate 2>&1 | tee benchmark.log
```

**Pros**:
- ✅ Already works
- ✅ Minimal changes
- ✅ Proven reliability

**Cons**:
- Less detailed metrics than `benchmark_performance.py`
- But good enough for comparison

### Option 2: Simplify Benchmark Script (CURRENT APPROACH)

**Make benchmark script call POC directly**:

```bash
# In simple_scale_benchmark.sh
# Instead of calling benchmark_performance.py
# Call the POC directly like IQE does:

/usr/bin/time -l python3 -m src.main 2>&1 | tee output.txt
```

This is what the new `simple_scale_benchmark.sh` does!

### Option 3: Fix benchmark_performance.py (COMPLEX)

Would require:
1. Making all config variables optional
2. Handling missing variables gracefully
3. More defensive config loading
4. Still adds complexity vs direct call

## Summary Table

| Aspect | IQE Tests | Benchmark Scripts |
|--------|-----------|-------------------|
| **Call method** | Direct (`python3 -m src.main`) | Wrapper (`benchmark_performance.py`) |
| **Layers** | 1 | 2 |
| **Config** | Static | Dynamic modification |
| **Complexity** | Low | High |
| **Success rate** | 100% (18/18) | 0% (many failures) |
| **Metrics** | Correctness only | Performance only |
| **Reliability** | ✅ Proven | ❌ Fragile |

## Recommendation

**Use the IQE test pattern for benchmarking**:

```bash
# This works (proven 18/18 times):
python3 -m src.main --truncate

# Just add metrics wrapper:
/usr/bin/time -l python3 -m src.main --truncate 2>&1 | tee results.txt

# Extract what you need from results.txt
```

**Don't use**: Complex wrapper scripts with dynamic config modification.

## The New Simple Script

The `simple_scale_benchmark.sh` I just created follows the IQE pattern:

✅ Direct call to `src.main`
✅ System `time` command for metrics
✅ Static config (with backup/restore)
✅ Minimal layers
✅ Should actually work

---

**Bottom line**: The IQE tests work because they're simple. The benchmark scripts failed because they added unnecessary complexity. The new simple script copies the IQE approach.

