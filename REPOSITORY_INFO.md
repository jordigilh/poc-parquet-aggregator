# POC Parquet Aggregator Repository

**Status**: ✅ POC Complete - All Tests Passing  
**Location**: Standalone repository (moved from koku branch)  
**Purpose**: Trino + Hive replacement using custom Parquet aggregation

---

## Repository Structure

This is a **standalone repository** containing the complete POC for replacing Trino + Hive with custom code aggregation.

**Moved from**: `koku/poc-parquet-aggregator` branch  
**Reason**: Keep POC isolated to avoid interfering with main koku development

---

## Quick Start

```bash
# Clone this repository
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install koku-nise Jinja2

# Start local environment
./scripts/start-local-env.sh

# Run a test
./scripts/test_iqe_production_scenarios.sh
```

---

## Key Documents

### Getting Started
- **[README.md](README.md)** - Overview and architecture
- **[QUICKSTART.md](QUICKSTART.md)** - Quick setup guide
- **[POC_TRIAGE.md](POC_TRIAGE.md)** - Implementation status and next steps

### Technical Details
- **[TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md)** - How this replaces Trino + Hive
- **[docs/TRINO_SQL_100_PERCENT_AUDIT.md](docs/TRINO_SQL_100_PERCENT_AUDIT.md)** - Line-by-line SQL audit

### Testing
- **[IQE_VALIDATION_GUIDE.md](IQE_VALIDATION_GUIDE.md)** - Test execution guide
- **[FINAL_POC_RESULTS.md](FINAL_POC_RESULTS.md)** - Test results (7/7 production, 18/18 extended)
- **[TEST_SUITES_EXPLAINED.md](TEST_SUITES_EXPLAINED.md)** - Test suite breakdown

### Validation
- **[VALIDATION_WORKFLOW.md](VALIDATION_WORKFLOW.md)** - Validation process
- **[VALIDATION_FIX_EXPLAINED.md](VALIDATION_FIX_EXPLAINED.md)** - Multi-generator validation logic

---

## Test Results

**Production Scenarios**: 7/7 ✅  
**Extended Scenarios**: 18/18 ✅  
**Total**: 25/25 ✅

**Performance**: 3-7K rows/sec  
**Accuracy**: 100% match with expected values  
**Confidence**: 100% for POC, 90% for production readiness

---

## What's Implemented

✅ **Pod Aggregation** (100% Trino SQL equivalent)
- Lines 95-316 of Trino SQL
- 3-way label merge (node + namespace + pod)
- 2-level capacity aggregation
- CPU/memory metrics conversion
- Effective usage calculations

✅ **Comprehensive Testing**
- 18 IQE test scenarios
- Automated test execution
- Expected value validation
- Multi-month support

✅ **Local Development**
- MinIO for S3 storage
- PostgreSQL for results
- Podman Compose setup
- Complete test workflow

---

## What's NOT Implemented (Post-POC)

⏳ **Storage Aggregation** (Lines 318-446 of Trino SQL)  
⏳ **Unallocated Capacity** (Lines 461-581 of Trino SQL)  
⏳ **Other Providers** (AWS, Azure, GCP)  
⏳ **MASU Integration**  
⏳ **Kubernetes Deployment**  
⏳ **Production Data Testing**

See [POC_TRIAGE.md](POC_TRIAGE.md) for detailed roadmap.

---

## Directory Structure

```
.
├── config/              # Test YAML files (18 IQE scenarios)
├── docs/                # Technical documentation
├── scripts/             # Test and setup scripts
├── src/                 # Core aggregation code
├── tests/               # Unit tests
├── docker-compose.yml   # Local environment setup
├── requirements.txt     # Python dependencies
└── *.md                 # Documentation files
```

---

## Development Workflow

### Run Production Tests

```bash
source venv/bin/activate
./scripts/test_iqe_production_scenarios.sh
```

### Run Extended Tests

```bash
source venv/bin/activate
./scripts/test_extended_iqe_scenarios.sh
```

### Run Single Test

```bash
source venv/bin/activate
export IQE_YAML="ocp_report_1.yml"
./scripts/run_iqe_validation.sh
```

### Clean Up

```bash
./scripts/stop-local-env.sh
```

---

## Related Repositories

- **koku**: Main application repository
- **iqe-cost-management-plugin**: IQE test suite (required for testing)
- **ros-helm-chart**: Helm chart for deployment

---

## Next Steps

1. **Code Review** - Review POC with team
2. **Production Testing** - Test with real production data
3. **MASU Integration** - Integrate into MASU workflow
4. **Kubernetes Deployment** - Deploy to dev cluster
5. **Parallel Run** - Run alongside Trino for validation

See [POC_TRIAGE.md](POC_TRIAGE.md) for detailed timeline.

---

## Support

**Questions?** See documentation:
- [POC_TRIAGE.md](POC_TRIAGE.md) - Status and roadmap
- [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md) - Architecture details
- [IQE_VALIDATION_GUIDE.md](IQE_VALIDATION_GUIDE.md) - Testing guide

---

**Last Updated**: 2025-11-20  
**Status**: ✅ POC COMPLETE  
**Recommendation**: ✅ PROCEED TO PRODUCTION TESTING
