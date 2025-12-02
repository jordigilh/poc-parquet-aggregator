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
