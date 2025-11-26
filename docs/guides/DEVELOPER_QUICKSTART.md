# Developer Quick Start Guide

**For**: Development team members testing the OCP Parquet Aggregator POC
**Time**: ~5 minutes to get up and running

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Setup](#quick-setup-3-steps)
3. [Running the POC](#running-the-poc)
4. [Validation](#validation)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.9+** (check with `python3 --version`)
- **Git** (for cloning)
- **Access to**:
  - MinIO instance (S3-compatible storage)
  - PostgreSQL database
  - Trino instance (for validation, optional)

---

## Quick Setup (3 Steps)

### 1. Clone and Enter Project
```bash
git clone <repository-url>
cd poc-parquet-aggregator
```

### 2. Run Setup Script
```bash
./scripts/setup_dev_environment.sh
```

**This will**:
- ✅ Check Python version (3.9+ required)
- ✅ Create virtual environment (`./venv`)
- ✅ Install all dependencies
- ✅ Validate everything works

**Expected output**:
```
✅ Virtual environment created
✅ All dependencies installed and validated
🎉 Setup Complete!
```

### 3. Activate Virtual Environment
```bash
source venv/bin/activate
```

**Done!** You're ready to run the POC.

---

## Running the POC

### Option A: Use Provided Test Data
```bash
# Set environment variables
export OCP_CLUSTER_ID="benchmark-small-fab13fc0"
export OCP_PROVIDER_UUID="fab13fc0-942e-429f-9a9e-e4d4f0eed848"
export OCP_YEAR="2025"
export OCP_MONTH="10"

# Run POC
python3 -m src.main
```

### Option B: Use Your Own Data
```bash
# 1. Configure environment
cp env.example .env
# Edit .env with your settings

# 2. Run POC
python3 -m src.main
```

---

## Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/test_storage_aggregator.py

# Integration tests
pytest tests/test_storage_integration.py

# With coverage
pytest --cov=src --cov-report=html
```

---

## Validating Against Trino

```bash
# After running POC, compare with Trino
python3 scripts/validate_against_trino.py \
  <cluster_id> \
  <provider_uuid> \
  <year> \
  <month>

# Example
python3 scripts/validate_against_trino.py \
  benchmark-small-fab13fc0 \
  fab13fc0-942e-429f-9a9e-e4d4f0eed848 \
  2025 \
  10
```

---

## Troubleshooting

### "ModuleNotFoundError"
**Solution**: Activate virtual environment
```bash
source venv/bin/activate
```

### "Connection refused" (PostgreSQL/MinIO)
**Solution**: Start services or port-forward
```bash
# PostgreSQL
oc port-forward -n cost-mgmt svc/postgresql 5432:5432

# MinIO (if local)
podman start minio
```

### "Table doesn't exist"
**Solution**: Check if you have data in MinIO
```bash
python3 -c "
import s3fs
fs = s3fs.S3FileSystem(endpoint_url='http://localhost:9000', key='minioadmin', secret='minioadmin')
print(fs.ls('data/'))
"
```

### Dependencies broken/missing
**Solution**: Re-run setup
```bash
./scripts/setup_dev_environment.sh
```

### Validate environment manually
```bash
python3 scripts/validate_environment.py
```

---

## Project Structure

```
poc-parquet-aggregator/
├── src/                      # Main source code
│   ├── main.py               # Entry point
│   ├── parquet_reader.py     # Read Parquet from S3
│   ├── aggregator_pod.py     # Pod aggregation logic
│   ├── aggregator_storage.py # Storage aggregation logic
│   ├── db_writer.py          # Write to PostgreSQL
│   └── utils.py              # Utilities
├── tests/                    # Test suite
│   ├── test_storage_aggregator.py
│   └── test_storage_integration.py
├── scripts/                  # Helper scripts
│   ├── setup_dev_environment.sh      # 👈 Start here
│   ├── validate_environment.py       # Check dependencies
│   ├── validate_against_trino.py     # Compare with Trino
│   └── csv_to_parquet_minio.py       # Upload test data
├── config/                   # Configuration
│   └── config.yaml           # Main config
├── requirements.txt          # Python dependencies
└── README.md                 # Full documentation
```

---

## Common Commands

```bash
# Setup (once)
./scripts/setup_dev_environment.sh

# Activate venv (every session)
source venv/bin/activate

# Run POC
python3 -m src.main

# Run tests
pytest

# Validate environment
python3 scripts/validate_environment.py

# Validate against Trino
python3 scripts/validate_against_trino.py <cluster> <provider> <year> <month>

# Deactivate venv (when done)
deactivate
```

---

## Configuration

### Environment Variables
```bash
# Required
export OCP_CLUSTER_ID="your-cluster"
export OCP_PROVIDER_UUID="your-provider-uuid"
export OCP_YEAR="2025"
export OCP_MONTH="10"

# Database
export POSTGRES_HOST="localhost"  # or postgresql.cost-management.svc.cluster.local
export POSTGRES_PORT="5432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="your-password"
export POSTGRES_SCHEMA="org1234567"

# S3/MinIO
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="data"
```

### Or use `.env` file
```bash
cp env.example .env
# Edit .env with your values
```

---

## Expected Results

### Successful POC Run
```
Phase 1: Reading configuration...
Phase 2: Connecting to database...
Phase 3: Reading node labels...
Phase 4: Reading namespace labels...
Phase 5: Aggregating pod usage...
  ✓ Generated 22,000 pod summary rows
Phase 5b: Aggregating storage usage...
  ✓ Generated 320 storage summary rows
Phase 6: Writing to database...
  ✓ Inserted 22,320 rows

POC COMPLETED SUCCESSFULLY in 3.5 seconds
```

### Successful Trino Validation
```
=== Trino Validation: POC vs Production ===
Cluster ID:    benchmark-small-fab13fc0
Provider UUID: fab13fc0-942e-429f-9a9e-e4d4f0eed848

📊 Querying PostgreSQL (POC results)...
📊 Querying Trino (production results)...

=== Comparison Results ===
✅ Pod: MATCH (row count, metrics within 1%)
✅ Storage: MATCH (row count, metrics within 1%)

✅✅✅ SUCCESS: POC matches Trino 1:1 ✅✅✅
```

---

## Getting Help

1. **Check documentation**: Read `README.md` and `SCHEMA_FIX_COMPLETE.md`
2. **Validate environment**: Run `python3 scripts/validate_environment.py`
3. **Check logs**: Look for detailed error messages in terminal output
4. **Ask the team**: Reach out with specific error messages

---

## Performance Notes

- **Small dataset** (22K rows): ~3-5 seconds
- **Medium dataset** (500K rows): ~30-60 seconds
- **Large dataset** (1M rows): ~2-3 minutes
- **Streaming mode**: Use for datasets >500K rows to reduce memory

---

## What's Different from Trino?

The POC writes directly to PostgreSQL, while Trino writes to Hive then copies to PostgreSQL.

**Key differences**:
- ✅ Faster (no intermediate Hive step)
- ✅ Simpler architecture (pure Python)
- ✅ Same results (1:1 parity validated)
- ✅ Scalable (in-memory processing optimized for production)
- ❌ No partition columns (`source`, `year`, `month`, `day`) in output
  - These are Hive-only, not in PostgreSQL schema

---

## Success Checklist

- ✅ Setup script completes without errors
- ✅ `validate_environment.py` shows all green checks
- ✅ POC runs and inserts data to PostgreSQL
- ✅ Tests pass (`pytest`)
- ✅ (Optional) Trino validation confirms 1:1 parity

---

**Questions?** Check `VALIDATION_READY.md` for detailed Trino validation steps.

**Happy testing!** 🚀

