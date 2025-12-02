# POC Parquet Aggregator → Koku Integration Plan

**Version**: 1.0  
**Date**: December 2, 2025  
**Confidence Level**: 90%  
**Estimated Effort**: 3-5 days

---

## Executive Summary

This document outlines the integration of the POC Parquet Aggregator into the koku codebase to create a testable container image for the development team.

### Goals
1. Create a koku image with POC aggregation capabilities
2. Enable dev team to validate POC against real/synthetic data
3. Maintain backward compatibility with existing koku functionality
4. Provide clear validation methodology

---

## Part 1: Pre-Integration Checklist

### 1.1 Dependency Compatibility ✅

| Dependency | POC Version | Koku Version | Status |
|------------|-------------|--------------|--------|
| pyarrow | >=14.0.0 | >=0.17.1 | ✅ Compatible |
| psycopg2-binary | >=2.9.9 | * | ✅ Compatible |
| pandas | >=2.1.0 | (via pyarrow) | ✅ Compatible |
| boto3 | (via s3fs) | ==1.35.99 | ✅ Compatible |
| numpy | >=1.24.0 | * | ✅ Compatible |

### 1.2 Files to Integrate

**Core Modules** (Required):
```
src/
├── aggregator_pod.py           # OCP pod aggregation
├── aggregator_storage.py       # OCP storage aggregation  
├── aggregator_unallocated.py   # Unallocated capacity
├── aggregator_ocp_aws.py       # OCP-on-AWS cost attribution
├── parquet_reader.py           # MinIO/S3 parquet reading
├── db_writer.py                # PostgreSQL output
├── arrow_compute.py            # PyArrow compute utilities
├── utils.py                    # Common utilities
└── config_loader.py            # Configuration management
```

**Supporting Modules** (Required for OCP-on-AWS):
```
src/
├── aws_data_loader.py          # AWS CUR data loading
├── cost_attributor.py          # Cost attribution logic
├── resource_matcher.py         # Resource ID matching
├── tag_matcher.py              # Tag-based matching
├── network_cost_handler.py     # Network cost handling
└── disk_capacity_calculator.py # Storage calculations
```

**Optional** (For testing/validation):
```
src/
├── expected_results.py         # Test validation
├── streaming_processor.py      # Large dataset handling
└── streaming_selector.py       # Memory-efficient selection
```

---

## Part 2: Integration Architecture

### 2.1 Target Location in Koku

```
koku/
└── koku/
    └── masu/
        └── processor/
            └── parquet/
                ├── __init__.py                      # Existing
                ├── parquet_report_processor.py      # Existing
                ├── summary_sql_metadata.py          # Existing
                └── poc_aggregator/                  # NEW DIRECTORY
                    ├── __init__.py
                    ├── aggregator_pod.py
                    ├── aggregator_storage.py
                    ├── aggregator_unallocated.py
                    ├── aggregator_ocp_aws.py
                    ├── parquet_reader.py
                    ├── db_writer.py
                    ├── arrow_compute.py
                    ├── utils.py
                    ├── config_loader.py
                    ├── aws_data_loader.py
                    ├── cost_attributor.py
                    ├── resource_matcher.py
                    ├── tag_matcher.py
                    ├── network_cost_handler.py
                    └── disk_capacity_calculator.py
```

### 2.2 Integration Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│                         KOKU                                     │
├─────────────────────────────────────────────────────────────────┤
│  Celery Tasks (tasks.py)                                        │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  NEW: POC Integration Layer                              │    │
│  │  koku/masu/processor/parquet/poc_integration.py         │    │
│  │                                                          │    │
│  │  - process_ocp_parquet_poc()                            │    │
│  │  - process_ocp_aws_parquet_poc()                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  POC Aggregator Module                                   │    │
│  │  koku/masu/processor/parquet/poc_aggregator/            │    │
│  │                                                          │    │
│  │  PodAggregator, StorageAggregator, OCPAWSAggregator     │    │
│  └─────────────────────────────────────────────────────────┘    │
│       │                                                          │
│       ▼                                                          │
│  PostgreSQL (existing koku database)                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Step-by-Step Integration

### Phase 1: Prepare POC Package (Day 1)
**Location**: poc-parquet-aggregator project

```bash
# Step 1.1: Create integration package
cd /path/to/poc-parquet-aggregator

mkdir -p koku-integration/poc_aggregator
cp src/aggregator_*.py koku-integration/poc_aggregator/
cp src/parquet_reader.py koku-integration/poc_aggregator/
cp src/db_writer.py koku-integration/poc_aggregator/
cp src/arrow_compute.py koku-integration/poc_aggregator/
cp src/utils.py koku-integration/poc_aggregator/
cp src/config_loader.py koku-integration/poc_aggregator/
cp src/aws_data_loader.py koku-integration/poc_aggregator/
cp src/cost_attributor.py koku-integration/poc_aggregator/
cp src/resource_matcher.py koku-integration/poc_aggregator/
cp src/tag_matcher.py koku-integration/poc_aggregator/
cp src/network_cost_handler.py koku-integration/poc_aggregator/
cp src/disk_capacity_calculator.py koku-integration/poc_aggregator/

# Step 1.2: Create __init__.py
cat > koku-integration/poc_aggregator/__init__.py << 'EOF'
"""
POC Parquet Aggregator - Koku Integration

This module provides parquet-based aggregation for OCP and OCP-on-AWS
cost data, replacing Trino SQL queries with PyArrow compute operations.
"""

from .aggregator_pod import PodAggregator
from .aggregator_storage import StorageAggregator
from .aggregator_unallocated import UnallocatedAggregator
from .aggregator_ocp_aws import OCPAWSAggregator

__all__ = [
    'PodAggregator',
    'StorageAggregator', 
    'UnallocatedAggregator',
    'OCPAWSAggregator',
]

__version__ = '1.0.0'
EOF

# Step 1.3: Fix relative imports (if needed)
# The POC uses relative imports that may need adjustment
```

### Phase 2: Copy to Koku (Day 1-2)
**Location**: koku project

```bash
# Step 2.1: Create target directory
cd /path/to/koku
mkdir -p koku/masu/processor/parquet/poc_aggregator

# Step 2.2: Copy POC modules
cp -r /path/to/poc-parquet-aggregator/koku-integration/poc_aggregator/* \
    koku/masu/processor/parquet/poc_aggregator/

# Step 2.3: Verify structure
ls -la koku/masu/processor/parquet/poc_aggregator/
```

### Phase 3: Create Integration Layer (Day 2)
**Location**: koku project

Create `koku/masu/processor/parquet/poc_integration.py`:

```python
"""
POC Parquet Aggregator Integration Layer

This module provides the integration between koku's Celery tasks
and the POC parquet aggregator.
"""

import logging
import os
from datetime import datetime
from typing import Optional

from django.conf import settings

from .poc_aggregator import (
    PodAggregator,
    StorageAggregator,
    UnallocatedAggregator,
    OCPAWSAggregator,
)

LOG = logging.getLogger(__name__)


class POCAggregatorConfig:
    """Configuration for POC aggregator from koku settings."""
    
    def __init__(self, schema_name: str):
        self.schema_name = schema_name
        self.s3_bucket = os.getenv('S3_BUCKET_NAME', settings.S3_BUCKET_NAME)
        self.s3_endpoint = os.getenv('S3_ENDPOINT', getattr(settings, 'S3_ENDPOINT', None))
        self.db_config = {
            'host': settings.DATABASES['default']['HOST'],
            'port': settings.DATABASES['default']['PORT'],
            'database': settings.DATABASES['default']['NAME'],
            'user': settings.DATABASES['default']['USER'],
            'password': settings.DATABASES['default']['PASSWORD'],
        }


def process_ocp_parquet_poc(
    schema_name: str,
    provider_uuid: str,
    year: int,
    month: int,
    cluster_id: Optional[str] = None,
) -> dict:
    """
    Process OCP parquet data using POC aggregator.
    
    Args:
        schema_name: Database schema (org ID)
        provider_uuid: OCP provider UUID
        year: Year to process
        month: Month to process
        cluster_id: Optional cluster ID filter
        
    Returns:
        dict with processing results and metrics
    """
    LOG.info(
        f"POC: Starting OCP parquet processing for {schema_name}, "
        f"provider={provider_uuid}, period={year}-{month:02d}"
    )
    
    config = POCAggregatorConfig(schema_name)
    results = {'status': 'success', 'aggregators': {}}
    
    try:
        # Run Pod Aggregator
        pod_agg = PodAggregator(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            schema=schema_name,
            cluster_id=cluster_id,
        )
        pod_results = pod_agg.run()
        results['aggregators']['pod'] = pod_results
        LOG.info(f"POC: Pod aggregation complete: {pod_results}")
        
        # Run Storage Aggregator
        storage_agg = StorageAggregator(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            schema=schema_name,
            cluster_id=cluster_id,
        )
        storage_results = storage_agg.run()
        results['aggregators']['storage'] = storage_results
        LOG.info(f"POC: Storage aggregation complete: {storage_results}")
        
        # Run Unallocated Aggregator
        unalloc_agg = UnallocatedAggregator(
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            schema=schema_name,
            cluster_id=cluster_id,
        )
        unalloc_results = unalloc_agg.run()
        results['aggregators']['unallocated'] = unalloc_results
        LOG.info(f"POC: Unallocated aggregation complete: {unalloc_results}")
        
    except Exception as e:
        LOG.error(f"POC: OCP aggregation failed: {e}", exc_info=True)
        results['status'] = 'error'
        results['error'] = str(e)
    
    return results


def process_ocp_aws_parquet_poc(
    schema_name: str,
    ocp_provider_uuid: str,
    aws_provider_uuid: str,
    year: int,
    month: int,
    cluster_id: Optional[str] = None,
) -> dict:
    """
    Process OCP-on-AWS parquet data using POC aggregator.
    
    Args:
        schema_name: Database schema (org ID)
        ocp_provider_uuid: OCP provider UUID
        aws_provider_uuid: AWS provider UUID
        year: Year to process
        month: Month to process
        cluster_id: Optional cluster ID filter
        
    Returns:
        dict with processing results and metrics
    """
    LOG.info(
        f"POC: Starting OCP-on-AWS parquet processing for {schema_name}, "
        f"ocp={ocp_provider_uuid}, aws={aws_provider_uuid}, period={year}-{month:02d}"
    )
    
    config = POCAggregatorConfig(schema_name)
    results = {'status': 'success', 'aggregators': {}}
    
    try:
        # Run OCP-on-AWS Aggregator
        ocp_aws_agg = OCPAWSAggregator(
            ocp_provider_uuid=ocp_provider_uuid,
            aws_provider_uuid=aws_provider_uuid,
            year=year,
            month=month,
            schema=schema_name,
            cluster_id=cluster_id,
        )
        ocp_aws_results = ocp_aws_agg.run()
        results['aggregators']['ocp_aws'] = ocp_aws_results
        LOG.info(f"POC: OCP-on-AWS aggregation complete: {ocp_aws_results}")
        
    except Exception as e:
        LOG.error(f"POC: OCP-on-AWS aggregation failed: {e}", exc_info=True)
        results['status'] = 'error'
        results['error'] = str(e)
    
    return results
```

### Phase 4: Add Celery Tasks (Day 2-3)
**Location**: koku project

Add to `koku/masu/processor/tasks.py`:

```python
# Add at the top with other imports
from koku.masu.processor.parquet.poc_integration import (
    process_ocp_parquet_poc,
    process_ocp_aws_parquet_poc,
)

# Add these task definitions

@celery.task(name="masu.processor.tasks.process_ocp_parquet_poc_task", queue="summary")
def process_ocp_parquet_poc_task(
    schema_name: str,
    provider_uuid: str,
    year: int,
    month: int,
    cluster_id: str = None,
):
    """
    Celery task to run POC OCP parquet aggregation.
    
    This task can be triggered manually for testing the POC aggregator:
    
        from koku.masu.processor.tasks import process_ocp_parquet_poc_task
        process_ocp_parquet_poc_task.delay('org1234567', 'uuid', 2025, 10)
    """
    return process_ocp_parquet_poc(
        schema_name=schema_name,
        provider_uuid=provider_uuid,
        year=year,
        month=month,
        cluster_id=cluster_id,
    )


@celery.task(name="masu.processor.tasks.process_ocp_aws_parquet_poc_task", queue="summary")
def process_ocp_aws_parquet_poc_task(
    schema_name: str,
    ocp_provider_uuid: str,
    aws_provider_uuid: str,
    year: int,
    month: int,
    cluster_id: str = None,
):
    """
    Celery task to run POC OCP-on-AWS parquet aggregation.
    
    This task can be triggered manually for testing the POC aggregator:
    
        from koku.masu.processor.tasks import process_ocp_aws_parquet_poc_task
        process_ocp_aws_parquet_poc_task.delay('org1234567', 'ocp-uuid', 'aws-uuid', 2025, 10)
    """
    return process_ocp_aws_parquet_poc(
        schema_name=schema_name,
        ocp_provider_uuid=ocp_provider_uuid,
        aws_provider_uuid=aws_provider_uuid,
        year=year,
        month=month,
        cluster_id=cluster_id,
    )
```

### Phase 5: Update Dependencies (Day 3)
**Location**: koku project

Add to `Pipfile` under `[packages]`:

```toml
# POC Parquet Aggregator dependencies (most already present)
s3fs = ">=2023.12.0"  # If not present - for MinIO/S3 access
```

Then run:

```bash
pipenv lock
pipenv install
```

### Phase 6: Build Test Image (Day 3-4)
**Location**: koku project

```bash
# Step 6.1: Build the image
docker build -t koku-poc:test .

# Step 6.2: Tag for registry (if needed)
docker tag koku-poc:test quay.io/your-org/koku-poc:test

# Step 6.3: Push to registry (if needed)
docker push quay.io/your-org/koku-poc:test
```

### Phase 7: Validation (Day 4-5)
**Location**: koku project with running containers

```bash
# Step 7.1: Start koku environment
docker-compose up -d

# Step 7.2: Enter the koku container
docker-compose exec koku bash

# Step 7.3: Test import
python -c "from koku.masu.processor.parquet.poc_aggregator import PodAggregator; print('Import OK')"

# Step 7.4: Run a test aggregation (from Django shell)
python manage.py shell

>>> from koku.masu.processor.parquet.poc_integration import process_ocp_parquet_poc
>>> result = process_ocp_parquet_poc('org1234567', 'test-provider-uuid', 2025, 10)
>>> print(result)
```

---

## Part 4: Validation Checklist

### 4.1 Unit Tests

| Test | Description | Command |
|------|-------------|---------|
| Import test | Verify modules import correctly | `python -c "from ...poc_aggregator import *"` |
| Config test | Verify koku settings are read | Check POCAggregatorConfig |
| Connection test | Verify DB connection works | Run simple query |

### 4.2 Integration Tests

| Test | Description | Expected |
|------|-------------|----------|
| OCP-only aggregation | Process OCP parquet data | Rows in reporting_ocpusagelineitem_daily_summary_p |
| OCP-on-AWS aggregation | Process OCP+AWS data | Rows in reporting_ocpawscostlineitem_project_daily_summary_p |
| Celery task | Trigger task via Celery | Task completes successfully |

### 4.3 Comparison Tests

```sql
-- Compare POC output with existing Trino output
SELECT 
    'POC' as source,
    COUNT(*) as rows,
    SUM(unblended_cost) as total_cost
FROM org1234567.reporting_ocpawscostlineitem_project_daily_summary_p
WHERE usage_start >= '2025-10-01'

UNION ALL

SELECT 
    'Trino' as source,
    COUNT(*) as rows,
    SUM(unblended_cost) as total_cost
FROM <trino_equivalent_table>
WHERE usage_start >= '2025-10-01';
```

---

## Part 5: Rollback Plan

If integration fails:

```bash
# Step 1: Remove POC modules
rm -rf koku/masu/processor/parquet/poc_aggregator/
rm koku/masu/processor/parquet/poc_integration.py

# Step 2: Revert tasks.py changes
git checkout -- koku/masu/processor/tasks.py

# Step 3: Revert Pipfile changes (if any)
git checkout -- Pipfile Pipfile.lock

# Step 4: Rebuild image
docker build -t koku:latest .
```

---

## Part 6: Timeline Summary

| Day | Phase | Deliverable |
|-----|-------|-------------|
| 1 | Phase 1-2 | POC package prepared and copied to koku |
| 2 | Phase 3-4 | Integration layer and Celery tasks |
| 3 | Phase 5-6 | Dependencies updated and image built |
| 4-5 | Phase 7 | Validation and testing |

---

## Part 7: Success Criteria

✅ **Integration Complete When**:
1. POC modules import without errors in koku container
2. `process_ocp_parquet_poc()` processes test data successfully
3. `process_ocp_aws_parquet_poc()` processes test data successfully
4. Celery tasks can be triggered and complete
5. Output matches expected values from test manifests
6. No regressions in existing koku functionality

---

## Appendix A: Quick Reference Commands

```bash
# From POC project - create integration package
./scripts/create_koku_integration_package.sh

# From koku project - integrate
./scripts/integrate_poc.sh

# Test integration
docker-compose exec koku python -c "from koku.masu.processor.parquet.poc_aggregator import *"

# Run POC task manually
docker-compose exec koku python manage.py shell -c "
from koku.masu.processor.tasks import process_ocp_parquet_poc_task
result = process_ocp_parquet_poc_task('org1234567', 'uuid', 2025, 10)
print(result)
"
```

---

## Appendix B: Files Changed in Koku

| File | Change Type | Description |
|------|-------------|-------------|
| `koku/masu/processor/parquet/poc_aggregator/` | New directory | POC aggregator modules |
| `koku/masu/processor/parquet/poc_integration.py` | New file | Integration layer |
| `koku/masu/processor/tasks.py` | Modified | Added Celery tasks |
| `Pipfile` | Modified | Added s3fs dependency |

---

**Document Maintainer**: POC Integration Team  
**Last Updated**: December 2, 2025

