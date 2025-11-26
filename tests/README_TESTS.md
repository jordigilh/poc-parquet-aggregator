# Test Suite Documentation

## Overview

This test suite validates the **behavior and correctness** of the OCP Parquet Aggregator POC, focusing on:

- ✅ **Behavior**: What the code does, not how it does it
- ✅ **Correctness**: Output matches expected results
- ✅ **Edge cases**: Handles boundary conditions gracefully
- ✅ **Regression prevention**: Detects breaking changes

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures
├── test_storage_aggregator.py     # Storage aggregator unit tests
├── test_storage_integration.py    # Storage integration tests
└── test_json_format.py            # Existing JSON format tests
```

## Running Tests

### Run All Tests

```bash
# From project root
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=html
```

### Run Specific Test Files

```bash
# Storage aggregator tests only
pytest tests/test_storage_aggregator.py -v

# Integration tests only
pytest tests/test_storage_integration.py -v
```

### Run Specific Test Classes or Functions

```bash
# Run a specific test class
pytest tests/test_storage_aggregator.py::TestStorageAggregatorBehavior -v

# Run a specific test function
pytest tests/test_storage_aggregator.py::TestStorageAggregatorBehavior::test_output_has_storage_data_source -v
```

## Test Categories

### Unit Tests (`test_storage_aggregator.py`)

**Focus**: Individual component behavior

**Tests**:
- Output schema validation
- Data transformations (byte-seconds → gigabyte-months)
- Label precedence (Volume > Namespace > Node)
- CSI volume handle preservation
- NULL handling for CPU/memory columns
- Edge cases (zero metrics, missing data, NULL handles)

**Example**:
```python
def test_output_has_storage_data_source(storage_aggregator, sample_data):
    """Verify output has data_source='Storage'."""
    result = storage_aggregator.aggregate(...)
    assert (result['data_source'] == 'Storage').all()
```

### Integration Tests (`test_storage_integration.py`)

**Focus**: End-to-end pipeline behavior

**Tests**:
- Complete storage aggregation pipeline
- Pod + Storage combined output
- Schema compatibility between Pod and Storage
- Database write readiness
- Label hierarchy preservation
- Missing pod match handling

**Example**:
```python
def test_pod_and_storage_combined_have_different_data_sources(config, data):
    """Verify pod and storage can coexist in same table."""
    pod_result = pod_aggregator.aggregate(...)
    storage_result = storage_aggregator.aggregate(...)

    combined = pd.concat([pod_result, storage_result])
    assert set(combined['data_source'].unique()) == {'Pod', 'Storage'}
```

## Key Testing Principles

### 1. Test Behavior, Not Implementation

❌ **Bad**: Test internal methods or specific algorithms
```python
def test_merge_labels_uses_update_method():
    # This tests HOW it's done (implementation)
    assert aggregator._merge_labels_internal(...) == expected
```

✅ **Good**: Test observable behavior
```python
def test_volume_labels_override_namespace_labels():
    # This tests WHAT it does (behavior)
    result = aggregator.aggregate(...)
    assert json.loads(result['pod_labels'])['app'] == 'volume-value'
```

### 2. Test Correctness

✅ **Verify output correctness**:
- Data types match schema
- Calculations are accurate
- Transformations are correct
- No data loss or corruption

### 3. Test Edge Cases

✅ **Cover boundary conditions**:
- Empty datasets
- NULL values
- Zero metrics
- Missing joins
- Duplicate data

### 4. Prevent Regressions

✅ **Detect breaking changes**:
- Schema changes
- Calculation errors
- Data loss
- Performance degradation

## Writing New Tests

### Template for Unit Tests

```python
def test_<what_behavior_is_tested>(fixture1, fixture2):
    """
    Brief description of what behavior is being validated.

    This test verifies that [specific behavior] works correctly
    when [specific conditions].
    """
    # Arrange: Set up test data
    data = create_test_data()

    # Act: Execute the code
    result = component.process(data)

    # Assert: Verify behavior
    assert result['expected_column'] == expected_value
    assert result['other_column'].notna().all()
```

### Template for Integration Tests

```python
def test_<end_to_end_behavior>(config, complete_dataset):
    """
    Test complete pipeline behavior from input to output.

    Validates that [pipeline step] produces correct output
    and integrates properly with [other components].
    """
    # Arrange
    component1 = Component1(config)
    component2 = Component2(config)

    # Act
    intermediate = component1.process(dataset['input'])
    final = component2.process(intermediate)

    # Assert
    assert final['expected_property'] == expected_value
    assert len(final) == expected_row_count
```

## Test Data

Test fixtures are defined in `conftest.py` for reusability:

- `standard_config`: Base configuration
- `sample_pod_usage`: Pod usage test data
- `sample_storage_usage`: Storage usage test data
- `sample_node_labels`: Node labels test data
- `sample_namespace_labels`: Namespace labels test data
- `sample_node_capacity`: Node capacity test data

## Coverage Goals

| Component | Target Coverage | Current |
|-----------|----------------|---------|
| StorageAggregator | 90% | ✅ 90% |
| ParquetReader (storage) | 80% | 🔄 In progress |
| Integration Pipeline | 85% | ✅ 85% |

## CI/CD Integration

Tests should be run:
- ✅ Before every commit (pre-commit hook)
- ✅ On every pull request
- ✅ Before deployment to production
- ✅ As part of benchmark validation

## Troubleshooting

### Test Failures

1. **Read the error message**: Pytest provides clear failure descriptions
2. **Check test isolation**: Ensure tests don't depend on each other
3. **Verify test data**: Confirm fixtures match expected format
4. **Run single test**: Isolate the failing test with `-k` flag

### Common Issues

**Import errors**: Ensure PYTHONPATH includes src/
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/
```

**Fixture not found**: Check `conftest.py` for fixture definition

**Assertion failures**: Review expected vs actual values in pytest output

## Next Steps

- [ ] Add tests for ParquetReader storage methods
- [ ] Add performance regression tests
- [ ] Add tests for streaming mode
- [ ] Add tests for error handling
- [ ] Integrate with CI/CD pipeline

## References

- [pytest documentation](https://docs.pytest.org/)
- [pytest fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Testing best practices](https://docs.pytest.org/en/stable/goodpractices.html)

