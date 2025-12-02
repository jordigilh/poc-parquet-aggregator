"""
S3 Adapter for Koku Integration

This module provides S3 access using boto3 (koku's pattern) instead of s3fs.
Enables seamless integration with koku's existing S3 infrastructure.

For standalone POC testing, set environment variables:
    S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME

For koku integration, these come from Django settings.
"""

import io
import os
from typing import List, Optional

import pyarrow.parquet as pq

from .utils import get_logger

logger = get_logger("s3_adapter")


def get_s3_config():
    """
    Get S3 configuration from koku Django settings or environment variables.

    Priority:
    1. Django settings (when running in koku)
    2. Environment variables (standalone testing)
    """
    try:
        from django.conf import settings
        return {
            'endpoint_url': getattr(settings, 'S3_ENDPOINT', None),
            'access_key': getattr(settings, 'S3_ACCESS_KEY', None),
            'secret_key': getattr(settings, 'S3_SECRET_KEY', None),
            'bucket': getattr(settings, 'S3_BUCKET_NAME', 'cost-usage'),
            'timeout': getattr(settings, 'S3_TIMEOUT', 60),
        }
    except Exception:
        # Fallback to environment variables for standalone testing
        return {
            'endpoint_url': os.getenv('S3_ENDPOINT', 'http://localhost:9000'),
            'access_key': os.getenv('S3_ACCESS_KEY', os.getenv('AWS_ACCESS_KEY_ID', 'minioadmin')),
            'secret_key': os.getenv('S3_SECRET_KEY', os.getenv('AWS_SECRET_ACCESS_KEY', 'minioadmin')),
            'bucket': os.getenv('S3_BUCKET_NAME', 'cost-usage'),
            'timeout': int(os.getenv('S3_TIMEOUT', '60')),
        }


def get_s3_client():
    """
    Get S3 client using boto3 (koku's pattern).

    Returns:
        boto3 S3 client configured for MinIO/S3
    """
    import boto3
    from botocore.config import Config

    config_dict = get_s3_config()

    boto_config = Config(
        connect_timeout=config_dict['timeout'],
        retries={'max_attempts': 3}
    )

    client = boto3.client(
        's3',
        endpoint_url=config_dict['endpoint_url'],
        aws_access_key_id=config_dict['access_key'],
        aws_secret_access_key=config_dict['secret_key'],
        config=boto_config,
    )

    logger.debug("S3 client created", endpoint=config_dict['endpoint_url'])
    return client


def read_parquet_from_s3(bucket: str, key: str) -> pq.ParquetFile:
    """
    Read parquet file from S3/MinIO using boto3.

    Args:
        bucket: S3 bucket name
        key: Object key (path) in bucket

    Returns:
        PyArrow ParquetFile object
    """
    client = get_s3_client()

    logger.debug("Reading parquet from S3", bucket=bucket, key=key)

    response = client.get_object(Bucket=bucket, Key=key)
    data = response['Body'].read()

    return pq.ParquetFile(io.BytesIO(data))


def read_parquet_table_from_s3(bucket: str, key: str, columns: Optional[List[str]] = None):
    """
    Read parquet file as PyArrow Table from S3/MinIO.

    Args:
        bucket: S3 bucket name
        key: Object key (path) in bucket
        columns: Optional list of columns to read

    Returns:
        PyArrow Table
    """
    client = get_s3_client()

    logger.debug("Reading parquet table from S3", bucket=bucket, key=key)

    response = client.get_object(Bucket=bucket, Key=key)
    data = response['Body'].read()

    parquet_file = pq.ParquetFile(io.BytesIO(data))
    return parquet_file.read(columns=columns)


def list_parquet_files(bucket: str, prefix: str) -> List[str]:
    """
    List parquet files in S3 bucket with given prefix.

    Args:
        bucket: S3 bucket name
        prefix: Key prefix to filter

    Returns:
        List of object keys ending in .parquet
    """
    client = get_s3_client()
    paginator = client.get_paginator('list_objects_v2')

    files = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.parquet'):
                files.append(obj['Key'])

    logger.debug("Listed parquet files", bucket=bucket, prefix=prefix, count=len(files))
    return files


def check_s3_connectivity() -> bool:
    """
    Check if S3/MinIO is accessible.

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = get_s3_client()
        config = get_s3_config()
        client.head_bucket(Bucket=config['bucket'])
        logger.info("S3 connectivity check passed", bucket=config['bucket'])
        return True
    except Exception as e:
        logger.error("S3 connectivity check failed", error=str(e))
        return False

