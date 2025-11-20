#!/usr/bin/env python3
"""Generate synthetic Parquet data for benchmarking at various scales."""

import argparse
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
import random

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import get_logger, format_bytes


def generate_pod_usage_data(num_rows: int, num_days: int = 1) -> pd.DataFrame:
    """Generate synthetic pod usage data.

    Args:
        num_rows: Total number of rows to generate
        num_days: Number of days to spread data across

    Returns:
        DataFrame with synthetic pod usage data
    """
    logger = get_logger("synthetic_data")

    # Calculate rows per day
    rows_per_day = num_rows // num_days

    # Generate base data
    nodes = [f"node-{i:03d}" for i in range(1, 11)]  # 10 nodes
    namespaces = ["kube-system", "monitoring", "app-prod", "app-dev", "app-staging"]
    pods_per_namespace = {
        "kube-system": ["kube-proxy", "kube-dns", "calico-node"],
        "monitoring": ["prometheus", "grafana", "alertmanager"],
        "app-prod": [f"web-{i}" for i in range(5)],
        "app-dev": [f"web-dev-{i}" for i in range(3)],
        "app-staging": [f"web-staging-{i}" for i in range(2)]
    }

    data = []
    start_date = datetime(2025, 10, 1)

    for day in range(num_days):
        current_date = start_date + timedelta(days=day)

        for _ in range(rows_per_day):
            namespace = random.choice(namespaces)
            pod = random.choice(pods_per_namespace[namespace])
            node = random.choice(nodes)

            # Generate realistic metrics
            cpu_request = random.uniform(0.1, 2.0)
            cpu_usage = cpu_request * random.uniform(0.3, 0.9)
            cpu_limit = cpu_request * random.uniform(1.2, 2.0)

            memory_request = random.uniform(128, 2048)  # MB
            memory_usage = memory_request * random.uniform(0.4, 0.8)
            memory_limit = memory_request * random.uniform(1.2, 1.5)

            # Convert to seconds/bytes for hourly interval
            interval_seconds = 3600

            row = {
                'interval_start': current_date.strftime('%Y-%m-%d %H:%M:%S +0000 UTC'),
                'interval_end': (current_date + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S +0000 UTC'),
                'namespace': namespace,
                'node': node,
                'pod': f"{pod}-{uuid.uuid4().hex[:8]}",
                'resource_id': f"pod-{uuid.uuid4().hex[:16]}",
                'pod_labels': f'{{"app":"{namespace}","tier":"backend","version":"v1.0"}}',
                'pod_usage_cpu_core_seconds': cpu_usage * interval_seconds,
                'pod_request_cpu_core_seconds': cpu_request * interval_seconds,
                'pod_limit_cpu_core_seconds': cpu_limit * interval_seconds,
                'pod_effective_usage_cpu_core_seconds': max(cpu_usage, cpu_request) * interval_seconds,
                'pod_usage_memory_byte_seconds': memory_usage * 1024 * 1024 * interval_seconds,
                'pod_request_memory_byte_seconds': memory_request * 1024 * 1024 * interval_seconds,
                'pod_limit_memory_byte_seconds': memory_limit * 1024 * 1024 * interval_seconds,
                'pod_effective_usage_memory_byte_seconds': max(memory_usage, memory_request) * 1024 * 1024 * interval_seconds,
                'node_capacity_cpu_core_seconds': 8.0 * interval_seconds,  # 8 cores per node
                'node_capacity_memory_byte_seconds': 32 * 1024 * 1024 * 1024 * interval_seconds,  # 32 GB per node
                'source': str(uuid.uuid4())
            }
            data.append(row)

    df = pd.DataFrame(data)

    logger.info(
        f"Generated synthetic data",
        rows=len(df),
        days=num_days,
        memory=format_bytes(df.memory_usage(deep=True).sum())
    )

    return df


def upload_to_minio(df: pd.DataFrame, provider_uuid: str, year: str, month: str, day: str):
    """Upload DataFrame to MinIO as Parquet.

    Args:
        df: DataFrame to upload
        provider_uuid: Provider UUID
        year: Year
        month: Month (zero-padded)
        day: Day (zero-padded)
    """
    logger = get_logger("synthetic_data")

    # Create S3 filesystem
    fs = s3fs.S3FileSystem(
        key='minioadmin',
        secret='minioadmin',
        client_kwargs={'endpoint_url': 'http://localhost:9000'}
    )

    # S3 path
    s3_path = f"cost-management/data/org1234567/OCP/source={provider_uuid}/year={year}/month={month}/day={day}/openshift_pod_usage_line_items/data.parquet"

    # Convert to PyArrow table
    table = pa.Table.from_pandas(df)

    # Write to S3
    with fs.open(s3_path, 'wb') as f:
        pq.write_table(table, f, compression='snappy')

    logger.info(
        f"Uploaded to MinIO",
        path=s3_path,
        rows=len(df),
        size=format_bytes(df.memory_usage(deep=True).sum())
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate synthetic benchmark data")
    parser.add_argument(
        '--rows',
        type=int,
        required=True,
        help='Number of rows to generate'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=1,
        help='Number of days to spread data across'
    )
    parser.add_argument(
        '--provider-uuid',
        default=None,
        help='Provider UUID (generates random if not provided)'
    )
    parser.add_argument(
        '--year',
        default='2025',
        help='Year'
    )
    parser.add_argument(
        '--month',
        default='10',
        help='Month (zero-padded)'
    )
    parser.add_argument(
        '--output',
        help='Output CSV file (optional, for local testing)'
    )
    parser.add_argument(
        '--upload',
        action='store_true',
        help='Upload to MinIO'
    )

    args = parser.parse_args()

    # Generate provider UUID if not provided
    provider_uuid = args.provider_uuid or str(uuid.uuid4())

    print(f"Generating {args.rows:,} rows of synthetic data...")
    print(f"Provider UUID: {provider_uuid}")
    print(f"Days: {args.days}")
    print("")

    # Generate data
    df = generate_pod_usage_data(args.rows, args.days)

    # Save to CSV if requested
    if args.output:
        df.to_csv(args.output, index=False)
        print(f"✓ Saved to: {args.output}")

    # Upload to MinIO if requested
    if args.upload:
        print(f"Uploading to MinIO...")

        # Group by day and upload
        df['date'] = pd.to_datetime(df['interval_start'].str.replace(r' \+\d{4} UTC$', '', regex=True)).dt.date

        for date, day_df in df.groupby('date'):
            day_str = f"{date.day:02d}"
            upload_to_minio(
                day_df.drop('date', axis=1),
                provider_uuid,
                args.year,
                args.month,
                day_str
            )

        print(f"✓ Uploaded {len(df.groupby('date'))} days to MinIO")
        print(f"  Provider UUID: {provider_uuid}")
        print(f"  Path: cost-management/data/org1234567/OCP/source={provider_uuid}/year={args.year}/month={args.month}/")

    # Print summary
    print("")
    print("Summary:")
    print(f"  Total rows: {len(df):,}")
    print(f"  Memory: {format_bytes(df.memory_usage(deep=True).sum())}")
    print(f"  Unique namespaces: {df['namespace'].nunique()}")
    print(f"  Unique nodes: {df['node'].nunique()}")
    print(f"  Unique pods: {df['pod'].nunique()}")
    print("")
    print("Next steps:")
    print(f"  export OCP_PROVIDER_UUID='{provider_uuid}'")
    print(f"  export POC_YEAR='{args.year}'")
    print(f"  export POC_MONTH='{args.month}'")
    print(f"  python3 scripts/benchmark_performance.py \\")
    print(f"      --provider-uuid '{provider_uuid}' \\")
    print(f"      --year '{args.year}' \\")
    print(f"      --month '{args.month}' \\")
    print(f"      --output 'benchmark_results/benchmark_{args.rows}_rows.json'")

    return 0


if __name__ == '__main__':
    sys.exit(main())

