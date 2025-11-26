# GitHub Actions Workflows

## Current Workflows

### `test.yml` - Test Suite

Comprehensive test pipeline with three main jobs:

#### 1. **Unit Tests**
- Runs storage aggregator unit tests
- Validates behavior and correctness
- Generates code coverage reports
- **Runtime**: ~30 seconds

#### 2. **Integration Tests**
- Spins up PostgreSQL and MinIO services
- Creates database schema
- Runs end-to-end storage aggregation tests
- Validates Pod + Storage combined output
- **Runtime**: ~2 minutes

#### 3. **E2E Test with Nise**
- Full end-to-end test with real data generation
- Uses `nise` to generate OCP test data (pods + storage)
- Converts CSV → Parquet → MinIO
- Runs complete POC pipeline
- Validates results in PostgreSQL
- **Runtime**: ~3-4 minutes

#### 4. **Summary**
- Aggregates results from all test jobs
- Fails if any test job fails
- Provides clear pass/fail status

---

## Triggers

- **Push**: On `main` branch and all `feature/*` branches
- **Pull Request**: Against `main` branch

---

## Services

### PostgreSQL
- **Image**: `postgres:15`
- **Port**: `5432`
- **User**: `koku`
- **Database**: `koku`
- **Schema**: `org1234567`

### MinIO
- **Image**: `bitnami/minio:latest`
- **Port**: `9000`
- **Bucket**: `cost-management`
- **Credentials**: `minioadmin` / `minioadmin`

---

## E2E Test Scenario

The E2E test generates a realistic OCP scenario with:

### Infrastructure
- **2 nodes**: `e2e-node-1` (4 CPU, 16GB), `e2e-node-2` (8 CPU, 32GB)
- **2 namespaces**: `frontend`, `backend`
- **2 pods**: `web-1`, `api-1`
- **2 PVCs**: `web-pvc` (10GB gp2), `api-pvc` (50GB io1)

### Data Generated
- Pod usage metrics (CPU, memory)
- Storage usage metrics (capacity, requests, usage)
- Node labels, namespace labels, volume labels
- CSI volume handles

### Validations
- ✅ Pod aggregation successful
- ✅ Storage aggregation successful
- ✅ Both `data_source` types present ('Pod' and 'Storage')
- ✅ Pod rows have CPU/memory, NULL storage
- ✅ Storage rows have storage metrics, NULL CPU/memory
- ✅ CSI volume handles preserved
- ✅ No duplicate rows
- ✅ Row counts > 0

---

## Adding New Tests

### Adding Unit Tests

1. Create test file in `tests/test_*.py`
2. Follow existing patterns (behavior, not implementation)
3. Tests run automatically in CI

### Adding Integration Tests

1. Add to `tests/test_*_integration.py`
2. Use existing service containers (PostgreSQL, MinIO)
3. Tests run automatically in CI

### Adding E2E Scenarios

1. Modify `e2e-test` job in `test.yml`
2. Update nise configuration (`nise_config.yml`)
3. Add validation queries
4. Tests run automatically in CI

---

## Future Extensions

### OCP-in-AWS E2E Test (Planned)

When OCP-in-AWS implementation is complete, we'll add:

```yaml
e2e-test-ocp-aws:
  name: End-to-End Test - OCP on AWS
  runs-on: ubuntu-latest

  steps:
    - Generate OCP data with nise
    - Generate AWS CUR data with nise
    - Run POC with OCP-in-AWS aggregation
    - Validate resource ID matching
    - Validate tag-based matching
    - Validate cost attribution
    - Validate disk capacity calculation
```

**Requirements**:
- OCP-in-AWS aggregator implemented
- AWS CUR data generation in nise
- Resource ID matching logic
- Tag-based matching logic

---

## Local Testing

### Run Tests Locally

```bash
# Unit tests
pytest tests/test_storage_aggregator.py -v

# Integration tests (requires PostgreSQL + MinIO)
docker-compose up -d postgres minio
pytest tests/test_storage_integration.py -v

# E2E test (requires nise)
pip install koku-nise
./scripts/run_e2e_test.sh
```

### Debug Failed CI Jobs

1. Check job logs in GitHub Actions
2. Look for specific test failures
3. Reproduce locally with same environment
4. Fix and push

---

## Monitoring

### Code Coverage

- Unit tests coverage uploaded to Codecov
- Integration tests coverage uploaded to Codecov
- Combined coverage report available

### Artifacts

- E2E test logs saved as artifacts (7 day retention)
- CSV files from nise generation
- POC output logs

---

## Workflow Status Badge

Add to README.md:

```markdown
![Tests](https://github.com/your-org/poc-parquet-aggregator/workflows/Test%20Suite/badge.svg)
```

---

## Best Practices

1. **Keep tests fast**: Target < 5 minutes total
2. **Test behavior**: What it does, not how
3. **Use realistic data**: E2E tests use nise-generated data
4. **Validate comprehensively**: Check all critical outputs
5. **Clean up**: Services auto-cleaned after workflow
6. **Fail fast**: Stop on first failure
7. **Provide context**: Clear error messages

---

## Troubleshooting

### PostgreSQL Connection Failed

**Issue**: `could not connect to server`

**Fix**: Wait for health check to pass (configured in workflow)

### MinIO Not Ready

**Issue**: `connection refused to localhost:9000`

**Fix**: Health checks ensure services ready before tests run

### Nise Data Generation Failed

**Issue**: `nise report ocp` command failed

**Fix**:
- Check nise configuration syntax
- Verify nise is installed (`pip install koku-nise`)
- Check nise logs for specific error

### CSV to Parquet Conversion Failed

**Issue**: `No such file or directory: *.csv`

**Fix**:
- Verify nise generated CSV files
- Check file paths in conversion script
- Ensure correct cluster ID

### POC Aggregation Failed

**Issue**: `POC COMPLETED SUCCESSFULLY` not found in logs

**Fix**:
- Check environment variables
- Verify data uploaded to MinIO
- Check PostgreSQL schema created
- Review POC logs for specific error

---

## Performance Targets

| Job | Target Time | Actual Time |
|-----|-------------|-------------|
| Unit Tests | < 1 min | ~30s |
| Integration Tests | < 3 min | ~2 min |
| E2E Test | < 5 min | ~4 min |
| **Total** | **< 10 min** | **~7 min** |

---

*Last Updated*: November 21, 2025
*Status*: Active and ready for OCP standalone testing

