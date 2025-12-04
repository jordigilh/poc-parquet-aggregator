"""Parquet reader for OCP usage data from S3.

Uses boto3 for S3 access (aligned with Koku's pattern).
"""

import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import boto3
import pandas as pd
import pyarrow.parquet as pq

from .utils import PerformanceTimer, format_bytes, get_logger


class ParquetReader:
    """Read Parquet files from S3/MinIO using boto3."""

    def __init__(self, config: Dict):
        """Initialize Parquet reader with S3 configuration.

        Args:
            config: Configuration dictionary with s3 section
        """
        self.config = config
        self.logger = get_logger("parquet_reader")

        # S3 configuration
        s3_config = config["s3"]
        self.endpoint = s3_config["endpoint"]
        self.bucket = s3_config["bucket"]
        self.access_key = s3_config["access_key"]
        self.secret_key = s3_config["secret_key"]
        self.use_ssl = s3_config.get("use_ssl", True)
        self.verify_ssl = s3_config.get("verify_ssl", False)
        self.region = s3_config.get("region", "us-east-1")

        # Initialize boto3 S3 resource (aligned with Koku's pattern)
        self._s3_resource = None

        self.logger.info(f"Initialized Parquet reader (endpoint={self.endpoint}, bucket={self.bucket})")

    @property
    def s3_resource(self):
        """Lazy-load boto3 S3 resource."""
        if self._s3_resource is None:
            self._s3_resource = boto3.resource(
                "s3",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                endpoint_url=self.endpoint,
                region_name=self.region,
                verify=self.verify_ssl,
            )
        return self._s3_resource

    def list_parquet_files(self, s3_prefix: str) -> List[str]:
        """List all Parquet files in an S3 prefix.

        Args:
            s3_prefix: S3 prefix (e.g., "data/org1234567/OCP/source=uuid/year=2025/month=11/")

        Returns:
            List of S3 keys for Parquet files
        """
        self.logger.debug(f"Listing Parquet files in: {self.bucket}/{s3_prefix}")

        try:
            bucket = self.s3_resource.Bucket(self.bucket)
            files = []

            for obj in bucket.objects.filter(Prefix=s3_prefix):
                if obj.key.endswith(".parquet"):
                    files.append(obj.key)

            self.logger.info(f"Found {len(files)} Parquet files (prefix={s3_prefix}, count={len(files)})")
            return files
        except Exception as e:
            self.logger.error(f"Failed to list Parquet files (prefix={s3_prefix}, error={e})")
            raise

    def read_parquet_file(
        self,
        s3_key: str,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read a single Parquet file from S3.

        Args:
            s3_key: S3 object key (without s3:// prefix)
            columns: List of columns to read (None = all columns)

        Returns:
            pandas DataFrame
        """
        with PerformanceTimer(f"Read parquet: {Path(s3_key).name}", self.logger):
            try:
                # Get object from S3 using boto3
                obj = self.s3_resource.Object(self.bucket, s3_key)
                response = obj.get()
                data = response["Body"].read()

                # Read parquet with PyArrow
                parquet_file = pq.ParquetFile(io.BytesIO(data))
                table = parquet_file.read(columns=columns)
                df = table.to_pandas()

                # Apply categorical optimization if configured
                if self.config.get("performance", {}).get("use_categorical", True):
                    df = self._optimize_dataframe_memory(df)

                memory_usage = df.memory_usage(deep=True).sum()
                self.logger.info(
                    f"Loaded {len(df)} rows from {Path(s3_key).name} "
                    f"(columns={len(df.columns)}, memory={format_bytes(memory_usage)})"
                )

                return df

            except Exception as e:
                self.logger.error(f"Failed to read Parquet file (file={s3_key}, error={e})")
                raise

    def read_parquet_streaming(
        self, s3_key: str, chunk_size: int = 10000, columns: Optional[List[str]] = None
    ) -> Iterator[pd.DataFrame]:
        """Read Parquet file in chunks (streaming mode).

        Args:
            s3_key: S3 object key
            chunk_size: Number of rows per chunk
            columns: List of columns to read

        Yields:
            pandas DataFrame chunks
        """
        self.logger.info(f"Starting streaming read (file={Path(s3_key).name}, chunk_size={chunk_size})")

        try:
            # Get object from S3
            obj = self.s3_resource.Object(self.bucket, s3_key)
            response = obj.get()
            data = response["Body"].read()

            # Open Parquet file
            parquet_file = pq.ParquetFile(io.BytesIO(data))

            total_rows = parquet_file.metadata.num_rows
            chunks_count = (total_rows + chunk_size - 1) // chunk_size

            self.logger.info(f"Parquet file metadata (total_rows={total_rows}, chunks={chunks_count})")

            # Read in batches
            for batch_idx, batch in enumerate(parquet_file.iter_batches(batch_size=chunk_size, columns=columns)):
                df = batch.to_pandas()

                # Apply optimization if configured
                if self.config.get("performance", {}).get("use_categorical", True):
                    df = self._optimize_dataframe_memory(df)

                self.logger.debug(f"Read chunk {batch_idx + 1}/{chunks_count} (rows={len(df)})")

                yield df

        except Exception as e:
            self.logger.error(f"Failed to stream Parquet file (file={s3_key}, error={e})")
            raise

    def read_pod_usage_line_items(
        self,
        provider_uuid: str,
        year: str,
        month: str,
        daily: bool = True,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """Read OCP pod usage line items (hourly or daily).

        Args:
            provider_uuid: Provider UUID
            year: Year (e.g., "2025")
            month: Month (e.g., "11")
            daily: If True, read daily aggregated data; if False, read hourly
            streaming: Whether to stream chunks
            chunk_size: Chunk size for streaming

        Returns:
            DataFrame or Iterator of DataFrames
        """
        # Determine path based on daily flag
        if daily:
            # Daily aggregated: openshift_pod_usage_line_items_daily/
            path_template = self.config["ocp"]["parquet_path_pod"]
        else:
            # Hourly intervals: openshift_pod_usage_line_items/
            path_template = self.config["ocp"]["parquet_path_pod_hourly"]

        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(f"No pod usage files found (prefix={s3_prefix})")
            return pd.DataFrame() if not streaming else iter([])

        # Column filtering for memory optimization
        columns = None
        if self.config.get("performance", {}).get("column_filtering", True):
            columns = self.get_optimal_columns_pod_usage()

        if streaming:
            def stream_all_files():
                """Stream all pod usage files chunk by chunk."""
                for file in files:
                    self.logger.debug(f"Streaming pod usage file: {file}")
                    yield from self.read_parquet_streaming(file, chunk_size, columns)

            return stream_all_files()
        else:
            # Standard mode: parallel reading
            parallel_workers = self.config.get("performance", {}).get("parallel_readers", 4)
            return self._read_files_parallel(files, parallel_workers, columns)

    def read_node_labels_line_items(self, provider_uuid: str, year: str, month: str) -> pd.DataFrame:
        """Read OCP node labels line items (daily).

        Args:
            provider_uuid: Provider UUID
            year: Year
            month: Month

        Returns:
            DataFrame
        """
        path_template = self.config["ocp"]["parquet_path_node_labels"]
        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(f"No node labels found (prefix={s3_prefix})")
            return pd.DataFrame()

        # Read and concatenate all files
        dfs = []
        for file in files:
            df = self.read_parquet_file(file)
            if not df.empty:
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        combined_df = pd.concat(dfs, ignore_index=True)
        self.logger.info(f"Combined {len(dfs)} node label files (total_rows={len(combined_df)})")
        return combined_df

    def read_namespace_labels_line_items(self, provider_uuid: str, year: str, month: str) -> pd.DataFrame:
        """Read OCP namespace labels line items (daily).

        Args:
            provider_uuid: Provider UUID
            year: Year
            month: Month

        Returns:
            DataFrame
        """
        path_template = self.config["ocp"]["parquet_path_namespace_labels"]
        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(f"No namespace labels found (prefix={s3_prefix})")
            return pd.DataFrame()

        # Read and concatenate all files
        dfs = []
        for file in files:
            df = self.read_parquet_file(file)
            if not df.empty:
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        combined_df = pd.concat(dfs, ignore_index=True)
        self.logger.info(f"Combined {len(dfs)} namespace label files (total_rows={len(combined_df)})")
        return combined_df

    def read_storage_usage_line_items(
        self,
        provider_uuid: str,
        year: str,
        month: str,
        daily: bool = True,
        streaming: bool = False,
        chunk_size: int = 10000,
    ) -> pd.DataFrame | Iterator[pd.DataFrame]:
        """Read OCP storage usage line items.

        Args:
            provider_uuid: Provider UUID
            year: Year
            month: Month
            daily: If True, read daily aggregated data
            streaming: Whether to stream chunks
            chunk_size: Chunk size for streaming

        Returns:
            DataFrame or Iterator of DataFrames
        """
        if daily:
            path_template = self.config["ocp"]["parquet_path_storage_usage_daily"]
        else:
            path_template = self.config["ocp"]["parquet_path_storage"]

        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(f"No storage usage files found (prefix={s3_prefix})")
            return pd.DataFrame() if not streaming else iter([])

        # Column filtering for memory optimization
        columns = None
        if self.config.get("performance", {}).get("column_filtering", True):
            columns = self.get_optimal_columns_storage_usage()

        if streaming:
            def stream_all_files():
                """Stream all storage usage files chunk by chunk."""
                for file in files:
                    self.logger.debug(f"Streaming storage usage file: {file}")
                    yield from self.read_parquet_streaming(file, chunk_size, columns)

            return stream_all_files()
        else:
            # Standard mode: parallel reading
            parallel_workers = self.config.get("performance", {}).get("parallel_readers", 4)
            return self._read_files_parallel(files, parallel_workers, columns)

    def _read_files_parallel(
        self, files: List[str], max_workers: int = 4, columns: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """Read multiple Parquet files in parallel.

        Args:
            files: List of S3 keys
            max_workers: Number of parallel workers
            columns: Optional list of columns to read

        Returns:
            Combined DataFrame
        """
        if not files:
            return pd.DataFrame()

        self.logger.info(f"Reading {len(files)} files in parallel (workers={max_workers})")

        dfs = []
        with PerformanceTimer(f"Parallel read ({len(files)} files)", self.logger):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all file reads
                future_to_file = {executor.submit(self.read_parquet_file, file, columns): file for file in files}

                # Collect results as they complete
                for future in as_completed(future_to_file):
                    file = future_to_file[future]
                    try:
                        df = future.result()
                        if not df.empty:
                            dfs.append(df)
                    except Exception as e:
                        self.logger.error(f"Failed to read file in parallel (file={file}, error={e})")
                        # Continue with other files

        if not dfs:
            return pd.DataFrame()

        # Concatenate all dataframes
        combined_df = pd.concat(dfs, ignore_index=True)
        self.logger.info(f"Combined {len(dfs)} files (total_rows={len(combined_df)})")
        return combined_df

    def get_optimal_columns_pod_usage(self) -> List[str]:
        """Get optimal column list for pod usage (reduce memory).

        Returns:
            List of essential column names
        """
        return [
            # Identity columns
            "interval_start",
            "namespace",
            "node",
            "pod",
            "resource_id",
            "cluster_id",
            # Labels
            "pod_labels",
            # CPU metrics
            "pod_usage_cpu_core_seconds",
            "pod_request_cpu_core_seconds",
            "pod_limit_cpu_core_seconds",
            # Memory metrics
            "pod_usage_memory_byte_seconds",
            "pod_request_memory_byte_seconds",
            "pod_limit_memory_byte_seconds",
            # Node capacity
            "node_capacity_cpu_core_seconds",
            "node_capacity_memory_byte_seconds",
        ]

    def get_optimal_columns_storage_usage(self) -> List[str]:
        """Get optimal column list for storage usage (reduce memory).

        Returns:
            List of essential column names
        """
        return [
            # Identity columns
            "interval_start",
            "namespace",
            "pod",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "cluster_id",
            # Storage metrics
            "persistentvolumeclaim_capacity_byte_seconds",
            "volume_request_storage_byte_seconds",
            "persistentvolumeclaim_usage_byte_seconds",
            # Labels
            "persistentvolume_labels",
            "persistentvolumeclaim_labels",
        ]

    def _optimize_dataframe_memory(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimize DataFrame memory using categorical types.

        Args:
            df: Input DataFrame

        Returns:
            Optimized DataFrame with categorical columns
        """
        categorical_cols = [
            "namespace",
            "node",
            "pod",
            "resource_id",
            "cluster_id",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
        ]

        for col in categorical_cols:
            if col in df.columns and df[col].dtype == "object":
                df[col] = df[col].astype("category")

        return df

    def test_connectivity(self) -> bool:
        """Test S3 connectivity.

        Returns:
            True if connection successful
        """
        try:
            # Try to access the bucket
            bucket = self.s3_resource.Bucket(self.bucket)
            # Just check if bucket exists by accessing creation_date
            _ = bucket.creation_date
            self.logger.info(f"S3 connectivity test: SUCCESS (bucket={self.bucket})")
            return True
        except Exception as e:
            self.logger.error(f"S3 connectivity test: FAILED (bucket={self.bucket}, error={e})")
            return False
