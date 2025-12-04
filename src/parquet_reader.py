"""Parquet reader for OCP usage data from S3."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pandas as pd
import pyarrow.parquet as pq
import s3fs

from .utils import PerformanceTimer, format_bytes, get_logger


class ParquetReader:
    """Read Parquet files from S3/MinIO."""

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

        # Initialize s3fs filesystem
        self.fs = self._create_s3_filesystem()

        self.logger.info(f"Initialized Parquet reader (endpoint={self.endpoint}, bucket={self.bucket})")

    def _create_s3_filesystem(self) -> s3fs.S3FileSystem:
        """Create S3 filesystem client.

        Returns:
            s3fs.S3FileSystem instance
        """
        fs = s3fs.S3FileSystem(
            key=self.access_key,
            secret=self.secret_key,
            client_kwargs={
                "endpoint_url": self.endpoint,
                "verify": self.verify_ssl,
                "region_name": self.config["s3"].get("region", "us-east-1"),
            },
            use_ssl=self.use_ssl,
        )
        # Clear any cached directory listings to prevent cross-scenario contamination
        # This is critical for test scenarios that share the same S3 paths
        fs.invalidate_cache()
        return fs

    def list_parquet_files(self, s3_prefix: str) -> List[str]:
        """List all Parquet files in an S3 prefix.

        Args:
            s3_prefix: S3 prefix (e.g., "cost-management/data/uuid/2025/11/")

        Returns:
            List of S3 URIs for Parquet files
        """
        full_prefix = f"{self.bucket}/{s3_prefix}"

        self.logger.debug(f"Listing Parquet files in: {full_prefix}")

        try:
            files = self.fs.glob(f"{full_prefix}/**/*.parquet")
            self.logger.info(f"Found {len(files)} Parquet files (prefix={s3_prefix}, count={len(files)})")
            return [f"s3://{f}" for f in files]
        except Exception as e:
            self.logger.error(f"Failed to list Parquet files (prefix={s3_prefix}, error={e})")
            raise

    def read_parquet_file(
        self,
        s3_uri: str,
        columns: Optional[List[str]] = None,
        filters: Optional[List] = None,
    ) -> pd.DataFrame:
        """Read a single Parquet file from S3.

        Args:
            s3_uri: S3 URI (e.g., "s3://bucket/path/to/file.parquet")
            columns: List of columns to read (None = all columns)
            filters: PyArrow filters for predicate pushdown

        Returns:
            pandas DataFrame
        """
        # Remove s3:// prefix for s3fs
        s3_path = s3_uri.replace("s3://", "")

        with PerformanceTimer(f"Read Parquet: {Path(s3_uri).name}", self.logger):
            try:
                # Read with PyArrow for better performance
                table = pq.read_table(s3_path, filesystem=self.fs, columns=columns, filters=filters)

                df = table.to_pandas()

                # Apply memory optimization if enabled (50-70% memory savings)
                if self.config.get("performance", {}).get("use_categorical", True):
                    df = self._optimize_dataframe_memory(df)

                # Calculate size
                memory_usage = df.memory_usage(deep=True).sum()

                self.logger.info(
                    "Loaded Parquet file",
                    file=Path(s3_uri).name,
                    rows=len(df),
                    columns=len(df.columns),
                    memory=format_bytes(memory_usage),
                )

                return df

            except Exception as e:
                self.logger.error(f"Failed to read Parquet file (file={s3_uri}, error={e})")
                raise

    def read_parquet_streaming(
        self, s3_uri: str, chunk_size: int = 10000, columns: Optional[List[str]] = None
    ) -> Iterator[pd.DataFrame]:
        """Read Parquet file in chunks (streaming mode).

        Args:
            s3_uri: S3 URI
            chunk_size: Number of rows per chunk
            columns: List of columns to read

        Yields:
            pandas DataFrame chunks
        """
        s3_path = s3_uri.replace("s3://", "")

        self.logger.info(f"Starting streaming read (file={Path(s3_uri).name}, chunk_size={chunk_size})")

        try:
            # Open Parquet file
            parquet_file = pq.ParquetFile(s3_path, filesystem=self.fs)

            total_rows = parquet_file.metadata.num_rows
            chunks_count = (total_rows + chunk_size - 1) // chunk_size

            self.logger.info(f"Parquet file metadata (total_rows={total_rows}, chunks={chunks_count})")

            # Read in batches
            for batch_idx, batch in enumerate(parquet_file.iter_batches(batch_size=chunk_size, columns=columns)):
                df = batch.to_pandas()

                self.logger.debug(f"Read chunk {batch_idx + 1}/{chunks_count} (rows={len(df)})")

                yield df

        except Exception as e:
            self.logger.error(f"Failed to stream Parquet file (file={s3_uri}, error={e})")
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
            # Replace '_daily' with '' to get hourly path
            path_template = self.config["ocp"]["parquet_path_pod"].replace("_daily/", "/")

        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(
                f"No pod usage Parquet files found ({'daily' if daily else 'hourly'})",
                prefix=s3_prefix,
            )
            return pd.DataFrame() if not streaming else iter([])

        self.logger.info(
            f"Found {len(files)} {'daily' if daily else 'hourly'} pod usage files",
            prefix=s3_prefix,
        )

        # Read and concatenate all files
        # Use column filtering if enabled (30-40% memory savings)
        columns = None
        if self.config.get("performance", {}).get("column_filtering", True):
            columns = self.get_optimal_columns_pod_usage()
            self.logger.info(f"Column filtering enabled: reading {len(columns)} of ~50 columns")

        if streaming:
            # For streaming, yield chunks from all files sequentially
            def stream_all_files():
                for file in files:
                    yield from self.read_parquet_streaming(file, chunk_size, columns=columns)

            return stream_all_files()
        else:
            # Use parallel reading for better performance
            parallel_workers = self.config.get("performance", {}).get("parallel_readers", 4)
            return self._read_files_parallel(files, parallel_workers, columns=columns)

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
        """Read OCP storage usage line items (hourly or daily).

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
        # Determine path based on daily vs hourly
        if daily:
            path_key = "parquet_path_storage_usage_daily"
        else:
            path_key = "parquet_path_storage_usage"

        path_template = self.config["ocp"].get(
            path_key,
            "cost-management/data/{provider_uuid}/{year}/{month}/openshift_storage_usage_line_items_daily",
        )

        s3_prefix = path_template.format(provider_uuid=provider_uuid, year=year, month=month)

        files = self.list_parquet_files(s3_prefix)

        if not files:
            self.logger.warning(f"No storage usage files found in: {s3_prefix}")
            if streaming:
                return iter([pd.DataFrame()])
            return pd.DataFrame()

        self.logger.info(f"Found {len(files)} storage usage files")

        # Column filtering (if enabled)
        columns = None
        if self.config.get("performance", {}).get("column_filtering", False):
            columns = self.get_optimal_columns_storage_usage()
            self.logger.info(f"Column filtering enabled: reading {len(columns)} columns for storage")

        if streaming:
            # For streaming, yield chunks from all files sequentially
            def stream_all_files():
                for file in files:
                    yield from self.read_parquet_streaming(file, chunk_size, columns=columns)

            return stream_all_files()
        else:
            # Use parallel reading for better performance
            parallel_workers = self.config.get("performance", {}).get("parallel_readers", 4)
            return self._read_files_parallel(files, parallel_workers, columns=columns)

    def _read_files_parallel(
        self,
        files: List[str],
        max_workers: int = 4,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Read multiple Parquet files in parallel.

        Args:
            files: List of S3 URIs
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
            List of essential columns

        Note: pod_effective_usage_* columns are NOT included because they are
        computed at runtime in aggregator_pod.py, not present in source Parquet files.
        Also, 'source' column is not in input Parquet - it's added later as provider_uuid.
        """
        return [
            "interval_start",
            "namespace",
            "node",
            "pod",
            "resource_id",
            "cluster_id",  # Required for multi-cluster scenarios
            "pod_labels",
            "pod_usage_cpu_core_seconds",
            "pod_request_cpu_core_seconds",
            "pod_limit_cpu_core_seconds",
            # 'pod_effective_usage_cpu_core_seconds',  # REMOVED: Computed at runtime, not in source
            "pod_usage_memory_byte_seconds",
            "pod_request_memory_byte_seconds",
            "pod_limit_memory_byte_seconds",
            # 'pod_effective_usage_memory_byte_seconds',  # REMOVED: Computed at runtime, not in source
            "node_capacity_cpu_core_seconds",
            "node_capacity_memory_byte_seconds",
            # 'source' is NOT in input data - it's added later in _format_output()
        ]

    def get_optimal_columns_storage_usage(self) -> List[str]:
        """Get optimal column list for storage usage (reduce memory).

        Returns:
            List of essential columns for storage aggregation
        """
        return [
            "interval_start",
            "namespace",
            "pod",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "cluster_id",  # Required for multi-cluster scenarios
            "persistentvolumeclaim_capacity_byte_seconds",
            "volume_request_storage_byte_seconds",
            "persistentvolumeclaim_usage_byte_seconds",
            "persistentvolume_labels",
            "persistentvolumeclaim_labels",
            "csi_volume_handle",
            # 'source' is NOT in input data - it's added later
        ]

    def _optimize_dataframe_memory(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimize DataFrame memory by using categorical types.

        String columns that repeat frequently (namespace, node, pod) use a lot of memory.
        Converting to categorical can save 50-70% memory.

        Args:
            df: Input DataFrame

        Returns:
            Optimized DataFrame with categorical types
        """
        # String columns that repeat a lot → use categorical (50-70% memory savings)
        # NOTE: 'source' is critical for groupby, make sure it exists before converting
        categorical_cols = ["namespace", "node", "pod", "resource_id"]

        # Only add 'source' if it exists in the DataFrame
        if "source" in df.columns:
            categorical_cols.append("source")

        for col in categorical_cols:
            if col in df.columns and df[col].dtype == "object":
                df[col] = df[col].astype("category")

        # Downcast numeric types (10-20% memory savings)
        for col in df.select_dtypes(include=["float64"]).columns:
            # Skip columns that might have NaN values or need high precision
            if "cpu" not in col and "memory" not in col:
                df[col] = pd.to_numeric(df[col], downcast="float")

        return df

    def test_connectivity(self) -> bool:
        """Test S3 connectivity.

        Returns:
            True if connection successful
        """
        try:
            # Try to list bucket
            self.fs.ls(self.bucket)
            self.logger.info(f"S3 connectivity test: SUCCESS (bucket={self.bucket})")
            return True
        except Exception as e:
            self.logger.error(f"S3 connectivity test: FAILED (bucket={self.bucket}, error={e})")
            return False
