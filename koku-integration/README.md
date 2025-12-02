# Koku Integration Package

This package contains the POC Parquet Aggregator modules prepared for integration into koku.

## Contents

```
koku-integration/
├── poc_aggregator/          # Core aggregator modules
│   ├── __init__.py
│   ├── aggregator_pod.py
│   ├── aggregator_storage.py
│   ├── aggregator_unallocated.py
│   ├── aggregator_ocp_aws.py
│   └── ... (support modules)
├── poc_integration.py       # Integration layer for koku
└── README.md               # This file
```

## Installation

1. Copy `poc_aggregator/` to `koku/masu/processor/parquet/`:
   ```bash
   cp -r poc_aggregator/ /path/to/koku/koku/masu/processor/parquet/
   ```

2. Copy `poc_integration.py` to the same directory:
   ```bash
   cp poc_integration.py /path/to/koku/koku/masu/processor/parquet/
   ```

3. Add Celery tasks to `koku/masu/processor/tasks.py` (see integration plan)

4. Build and test the koku image

## Usage

From within koku:

```python
from koku.masu.processor.parquet.poc_integration import (
    process_ocp_parquet_poc,
    process_ocp_aws_parquet_poc,
)

# OCP-only
result = process_ocp_parquet_poc('org1234567', 'provider-uuid', 2025, 10)

# OCP-on-AWS
result = process_ocp_aws_parquet_poc('org1234567', 'ocp-uuid', 'aws-uuid', 2025, 10)
```

## See Also

- [Full Integration Plan](../docs/KOKU_INTEGRATION_PLAN.md)
