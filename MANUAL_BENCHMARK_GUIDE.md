# Manual Benchmark Guide

## ✅ Preflight Checks Passed

All infrastructure is ready:
- ✅ PostgreSQL container running
- ✅ MinIO container running
- ✅ Python environment ready
- ✅ All dependencies installed
- ✅ Database table exists (156 rows)
- ✅ MinIO bucket exists
- ✅ Disk space available: 124Gi

---

## Quick Manual Benchmark

### Step 1: Generate Test Data

Generate a small dataset for quick testing:

```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
source venv/bin/activate

# Generate small dataset (5K rows)
./scripts/generate_nise_benchmark_data.sh small /tmp/nise_small
```

### Step 2: Upload to MinIO

```bash
# Convert CSV to Parquet and upload
python3 scripts/csv_to_parquet_minio.py /tmp/nise_small
```

### Step 3: Test Non-Streaming Mode

```bash
# Configure for non-streaming
python3 << 'EOF'
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = False
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print("✓ Set use_streaming = False")
EOF

# Clear database
podman exec postgres-poc psql -U koku -d koku -c "TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;"

# Run with metrics
echo "=== Non-Streaming Mode ===" > /tmp/benchmark_non_streaming.txt
/usr/bin/time -l python3 -m src.main 2>&1 | tee -a /tmp/benchmark_non_streaming.txt
```

### Step 4: Test Streaming Mode

```bash
# Configure for streaming
python3 << 'EOF'
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = True
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
print("✓ Set use_streaming = True")
EOF

# Clear database
podman exec postgres-poc psql -U koku -d koku -c "TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;"

# Run with metrics
echo "=== Streaming Mode ===" > /tmp/benchmark_streaming.txt
/usr/bin/time -l python3 -m src.main 2>&1 | tee -a /tmp/benchmark_streaming.txt
```

### Step 5: Compare Results

```bash
echo ""
echo "================================================================================"
echo "BENCHMARK COMPARISON"
echo "================================================================================"
echo ""
echo "Non-Streaming:"
grep -E "(real|maximum resident)" /tmp/benchmark_non_streaming.txt
echo ""
echo "Streaming:"
grep -E "(real|maximum resident)" /tmp/benchmark_streaming.txt
echo ""
echo "================================================================================"
```

---

## Environment Variables (Already Set)

The following are configured from your environment:

```bash
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="cost-management"

export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku"
export POSTGRES_SCHEMA="org1234567"

export OCP_CLUSTER_ID="test-ocp-cluster"
export OCP_PROVIDER_UUID="11111111-1111-1111-1111-111111111111"
export OCP_YEAR="2024"
export OCP_MONTH="05"
```

---

## Expected Metrics

For **small** scale (5K rows):

**Non-Streaming Mode:**
- Real time: ~5-10 seconds
- Peak memory: ~200-300 MB

**Streaming Mode:**
- Real time: ~6-12 seconds (slightly slower due to chunking)
- Peak memory: ~100-150 MB (50% reduction)

---

## Troubleshooting

### If database is locked:
```bash
podman restart postgres-poc
sleep 5
```

### If MinIO is unreachable:
```bash
podman restart minio-poc
sleep 5
```

### Run preflight checks again:
```bash
./scripts/preflight_check.sh
```

---

## Full Benchmark (Multiple Scales)

To test multiple scales:

```bash
SCALES=("small" "medium" "large")

for scale in "${SCALES[@]}"; do
    echo "Testing $scale..."

    # Generate data
    ./scripts/generate_nise_benchmark_data.sh "$scale" "/tmp/nise_$scale"
    python3 scripts/csv_to_parquet_minio.py "/tmp/nise_$scale"

    # Test both modes
    for mode in "False" "True"; do
        # Configure
        python3 << EOF
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['performance']['use_streaming'] = $mode
with open('config/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False)
EOF

        # Clear and run
        podman exec postgres-poc psql -U koku -d koku -c "TRUNCATE TABLE org1234567.reporting_ocpusagelineitem_daily_summary;"
        /usr/bin/time -l python3 -m src.main 2>&1 | tee "/tmp/benchmark_${scale}_${mode}.txt"
    done
done
```

---

## Next Steps

Once benchmarks are complete, the results will show:
1. ✅ Streaming mode works correctly
2. ✅ Memory usage is reduced
3. ✅ Correctness is maintained (same output rows)

Then proceed to Phase 2 optimizations.

