#!/bin/bash
#
# Create Koku Integration Package
#
# This script packages the POC aggregator modules for integration into koku.
#
# Usage:
#   ./scripts/create_koku_integration_package.sh [output_dir]
#
# Output:
#   Creates koku-integration/poc_aggregator/ with all necessary files

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PROJECT_ROOT/koku-integration}"

echo "📦 Creating Koku Integration Package"
echo "   Source: $PROJECT_ROOT/src"
echo "   Output: $OUTPUT_DIR/poc_aggregator"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR/poc_aggregator"

# Core modules
CORE_MODULES=(
    "aggregator_pod.py"
    "aggregator_storage.py"
    "aggregator_unallocated.py"
    "aggregator_ocp_aws.py"
    "parquet_reader.py"
    "db_writer.py"
    "arrow_compute.py"
    "utils.py"
    "config_loader.py"
)

# Supporting modules (for OCP-on-AWS)
SUPPORT_MODULES=(
    "aws_data_loader.py"
    "cost_attributor.py"
    "resource_matcher.py"
    "tag_matcher.py"
    "network_cost_handler.py"
    "disk_capacity_calculator.py"
)

# Optional modules
OPTIONAL_MODULES=(
    "expected_results.py"
    "streaming_processor.py"
    "streaming_selector.py"
)

echo "📋 Copying core modules..."
for module in "${CORE_MODULES[@]}"; do
    if [ -f "$PROJECT_ROOT/src/$module" ]; then
        cp "$PROJECT_ROOT/src/$module" "$OUTPUT_DIR/poc_aggregator/"
        echo "   ✅ $module"
    else
        echo "   ⚠️  $module not found (skipping)"
    fi
done

echo ""
echo "📋 Copying support modules..."
for module in "${SUPPORT_MODULES[@]}"; do
    if [ -f "$PROJECT_ROOT/src/$module" ]; then
        cp "$PROJECT_ROOT/src/$module" "$OUTPUT_DIR/poc_aggregator/"
        echo "   ✅ $module"
    else
        echo "   ⚠️  $module not found (skipping)"
    fi
done

echo ""
echo "📋 Copying optional modules..."
for module in "${OPTIONAL_MODULES[@]}"; do
    if [ -f "$PROJECT_ROOT/src/$module" ]; then
        cp "$PROJECT_ROOT/src/$module" "$OUTPUT_DIR/poc_aggregator/"
        echo "   ✅ $module"
    else
        echo "   ⚠️  $module not found (skipping)"
    fi
done

# Create __init__.py
echo ""
echo "📝 Creating __init__.py..."
cat > "$OUTPUT_DIR/poc_aggregator/__init__.py" << 'EOF'
"""
POC Parquet Aggregator - Koku Integration

This module provides parquet-based aggregation for OCP and OCP-on-AWS
cost data, replacing Trino SQL queries with PyArrow compute operations.

Usage:
    from koku.masu.processor.parquet.poc_aggregator import (
        PodAggregator,
        StorageAggregator,
        UnallocatedAggregator,
        OCPAWSAggregator,
    )
    
    # OCP-only aggregation
    pod_agg = PodAggregator(provider_uuid, year, month, schema)
    results = pod_agg.run()
    
    # OCP-on-AWS aggregation  
    ocp_aws_agg = OCPAWSAggregator(ocp_uuid, aws_uuid, year, month, schema)
    results = ocp_aws_agg.run()
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

echo "   ✅ __init__.py"

# Create poc_integration.py (the integration layer)
echo ""
echo "📝 Creating poc_integration.py..."
cat > "$OUTPUT_DIR/poc_integration.py" << 'INTEGRATION_EOF'
"""
POC Parquet Aggregator Integration Layer

This module provides the integration between koku's Celery tasks
and the POC parquet aggregator.

Copy this file to: koku/masu/processor/parquet/poc_integration.py
"""

import logging
import os
from typing import Optional

LOG = logging.getLogger(__name__)


def get_config_from_settings():
    """Get configuration from Django settings (when available)."""
    try:
        from django.conf import settings
        return {
            'db_host': settings.DATABASES['default']['HOST'],
            'db_port': settings.DATABASES['default']['PORT'],
            'db_name': settings.DATABASES['default']['NAME'],
            'db_user': settings.DATABASES['default']['USER'],
            'db_password': settings.DATABASES['default']['PASSWORD'],
            's3_bucket': getattr(settings, 'S3_BUCKET_NAME', os.getenv('S3_BUCKET_NAME')),
            's3_endpoint': getattr(settings, 'S3_ENDPOINT', os.getenv('S3_ENDPOINT')),
        }
    except Exception:
        # Fallback to environment variables
        return {
            'db_host': os.getenv('DATABASE_HOST', 'localhost'),
            'db_port': os.getenv('DATABASE_PORT', '5432'),
            'db_name': os.getenv('DATABASE_NAME', 'koku'),
            'db_user': os.getenv('DATABASE_USER', 'koku'),
            'db_password': os.getenv('DATABASE_PASSWORD', ''),
            's3_bucket': os.getenv('S3_BUCKET_NAME', 'cost-usage'),
            's3_endpoint': os.getenv('S3_ENDPOINT'),
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
    from .poc_aggregator import PodAggregator, StorageAggregator, UnallocatedAggregator
    
    LOG.info(
        f"POC: Starting OCP parquet processing for {schema_name}, "
        f"provider={provider_uuid}, period={year}-{month:02d}"
    )
    
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
    from .poc_aggregator import OCPAWSAggregator
    
    LOG.info(
        f"POC: Starting OCP-on-AWS parquet processing for {schema_name}, "
        f"ocp={ocp_provider_uuid}, aws={aws_provider_uuid}, period={year}-{month:02d}"
    )
    
    results = {'status': 'success', 'aggregators': {}}
    
    try:
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
INTEGRATION_EOF

echo "   ✅ poc_integration.py"

# Create README
echo ""
echo "📝 Creating README..."
cat > "$OUTPUT_DIR/README.md" << 'README_EOF'
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
README_EOF

echo "   ✅ README.md"

# Summary
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✅ Integration package created successfully!"
echo ""
echo "📁 Output: $OUTPUT_DIR/"
echo ""
echo "📋 Next steps:"
echo "   1. cd $OUTPUT_DIR"
echo "   2. Review the generated files"
echo "   3. Copy to koku: cp -r poc_aggregator/ /path/to/koku/koku/masu/processor/parquet/"
echo "   4. Copy integration layer: cp poc_integration.py /path/to/koku/koku/masu/processor/parquet/"
echo "   5. Follow the integration plan in docs/KOKU_INTEGRATION_PLAN.md"
echo "════════════════════════════════════════════════════════════════"

