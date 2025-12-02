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
