"""
Shared Streaming Processor for chunk-based data processing.

This module provides a reusable streaming framework for processing large datasets
in bounded memory. It can be used by any aggregator that needs to process data
in chunks (OCP-only, OCP-on-AWS, OCP-on-OCP, etc.).

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                     StreamingProcessor                       │
    │  ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐   │
    │  │ Reference   │   │   Chunks    │   │   Processor     │   │
    │  │ Data (small)│ + │ (iterator)  │ → │   Function      │   │
    │  │ [in-memory] │   │ [streaming] │   │ [per-chunk]     │   │
    │  └─────────────┘   └─────────────┘   └─────────────────┘   │
    │                           ↓                                  │
    │                    Combine Results                          │
    └─────────────────────────────────────────────────────────────┘

Usage:
    processor = StreamingProcessor(config, logger)

    # Define how to process each chunk
    def process_chunk(chunk_df, reference_data, chunk_idx):
        # Your processing logic here
        return processed_df

    # Run streaming processing
    result = processor.process_chunks(
        chunks=data_iterator,
        reference_data={'aws': aws_df, 'capacities': cap_df},
        process_fn=process_chunk
    )
"""

import gc
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

import pandas as pd

from .utils import PerformanceTimer, get_logger


class StreamingProcessor:
    """
    Generic streaming processor for chunk-based data processing.

    Provides:
    - Serial processing (single-threaded, lowest memory)
    - Parallel processing (multi-threaded, faster but more memory)
    - Memory management (explicit gc after each chunk)
    - Progress logging

    Attributes:
        config: Configuration dictionary
        logger: Logger instance
        parallel_enabled: Whether to use parallel processing
        max_workers: Number of parallel workers
        chunk_size: Size of each chunk
    """

    def __init__(
        self,
        config: Dict[str, Any],
        logger: Optional[Any] = None,
        name: str = "streaming_processor",
    ):
        """
        Initialize streaming processor.

        Args:
            config: Configuration dictionary with 'performance' section
            logger: Optional logger instance
            name: Name for logging
        """
        self.config = config
        self.logger = logger or get_logger(name)

        # Performance settings
        perf_config = config.get("performance", {})
        self.parallel_enabled = perf_config.get("parallel_chunks", False)
        self.max_workers = perf_config.get("max_workers", 4)
        chunk_size_raw = perf_config.get("chunk_size", 50000)
        self.chunk_size = int(chunk_size_raw) if isinstance(chunk_size_raw, str) else chunk_size_raw

        self.logger.info(
            "StreamingProcessor initialized",
            parallel=self.parallel_enabled,
            max_workers=self.max_workers if self.parallel_enabled else 1,
            chunk_size=self.chunk_size,
        )

    def process_chunks(
        self,
        chunks: Iterator[pd.DataFrame],
        reference_data: Dict[str, Any],
        process_fn: Callable[[pd.DataFrame, Dict[str, Any], int], pd.DataFrame],
        combine_fn: Optional[Callable[[List[pd.DataFrame]], pd.DataFrame]] = None,
        timer_name: str = "Streaming processing",
    ) -> pd.DataFrame:
        """
        Process data chunks with a custom processing function.

        This is the main entry point for streaming processing. It:
        1. Iterates through chunks (or collects for parallel processing)
        2. Applies process_fn to each chunk with reference data
        3. Combines results using combine_fn (default: pd.concat)
        4. Manages memory with explicit gc.collect()

        Args:
            chunks: Iterator of DataFrame chunks to process
            reference_data: Dictionary of reference data (kept in memory)
            process_fn: Function(chunk_df, reference_data, chunk_idx) -> DataFrame
            combine_fn: Optional function to combine results (default: pd.concat)
            timer_name: Name for performance timer

        Returns:
            Combined DataFrame from all processed chunks
        """
        if combine_fn is None:
            combine_fn = lambda dfs: pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

        with PerformanceTimer(timer_name, self.logger):
            if self.parallel_enabled:
                return self._process_parallel(chunks, reference_data, process_fn, combine_fn)
            else:
                return self._process_serial(chunks, reference_data, process_fn, combine_fn)

    def _process_serial(
        self,
        chunks: Iterator[pd.DataFrame],
        reference_data: Dict[str, Any],
        process_fn: Callable,
        combine_fn: Callable,
    ) -> pd.DataFrame:
        """Process chunks serially (single-threaded)."""
        self.logger.info("Using SERIAL chunk processing (bounded memory)")

        processed_chunks = []
        total_input_rows = 0
        total_output_rows = 0
        chunk_count = 0

        for chunk_idx, chunk_df in enumerate(chunks):
            chunk_count += 1
            input_rows = len(chunk_df)
            total_input_rows += input_rows

            self.logger.info(
                f"Processing chunk {chunk_count}",
                input_rows=input_rows,
                cumulative_input=total_input_rows,
            )

            try:
                # Process this chunk
                result = process_fn(chunk_df, reference_data, chunk_idx)

                if result is not None and not result.empty:
                    processed_chunks.append(result)
                    total_output_rows += len(result)

                    self.logger.debug(f"Chunk {chunk_count} processed (output_rows={len(result)})")

                # Free memory immediately
                del chunk_df
                gc.collect()

            except Exception as e:
                self.logger.error(f"Failed to process chunk {chunk_count} (error={e})")
                raise

        self.logger.info(
            f"All chunks processed (serial) (chunks={chunk_count}, "
            f"total_input_rows={total_input_rows}, total_output_rows={total_output_rows})"
        )

        # Combine results
        if not processed_chunks:
            return pd.DataFrame()

        combined = combine_fn(processed_chunks)

        # Free chunk list
        del processed_chunks
        gc.collect()

        return combined

    def _process_parallel(
        self,
        chunks: Iterator[pd.DataFrame],
        reference_data: Dict[str, Any],
        process_fn: Callable,
        combine_fn: Callable,
    ) -> pd.DataFrame:
        """Process chunks in parallel (multi-threaded)."""
        self.logger.info(f"Using PARALLEL chunk processing (workers={self.max_workers})")

        # Collect chunks first (required for parallel distribution)
        # Note: This means parallel mode uses more memory during collection
        chunk_list = list(chunks)
        chunk_count = len(chunk_list)
        total_input_rows = sum(len(c) for c in chunk_list)

        self.logger.info(
            f"Collected {chunk_count} chunks for parallel processing",
            total_input_rows=total_input_rows,
        )

        processed_chunks = []
        total_output_rows = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all chunks
            future_to_idx = {
                executor.submit(process_fn, chunk, reference_data, idx): idx for idx, chunk in enumerate(chunk_list)
            }

            # Collect results as they complete
            for future in as_completed(future_to_idx):
                chunk_idx = future_to_idx[future]
                try:
                    result = future.result()

                    if result is not None and not result.empty:
                        processed_chunks.append(result)
                        total_output_rows += len(result)

                    self.logger.info(
                        f"Chunk {chunk_idx + 1}/{chunk_count} completed",
                        output_rows=len(result) if result is not None else 0,
                    )

                except Exception as e:
                    self.logger.error(f"Chunk {chunk_idx} failed (error={e})")
                    raise

        # Free chunk list
        del chunk_list
        gc.collect()

        self.logger.info(
            f"All chunks processed (parallel) (chunks={chunk_count}, "
            f"total_input_rows={total_input_rows}, total_output_rows={total_output_rows})"
        )

        # Combine results
        if not processed_chunks:
            return pd.DataFrame()

        combined = combine_fn(processed_chunks)

        # Free chunk list
        del processed_chunks
        gc.collect()

        return combined

    def create_chunks(self, df: pd.DataFrame, chunk_size: Optional[int] = None) -> Iterator[pd.DataFrame]:
        """
        Create a chunk iterator from a DataFrame.

        Useful when you have a full DataFrame but want to process it
        in chunks to control memory.

        Args:
            df: DataFrame to chunk
            chunk_size: Size of each chunk (default: self.chunk_size)

        Yields:
            DataFrame chunks
        """
        chunk_size = chunk_size or self.chunk_size

        for i in range(0, len(df), chunk_size):
            yield df.iloc[i : i + chunk_size].copy()

    @staticmethod
    def log_memory_stats(logger, prefix: str = ""):
        """Log current memory statistics."""
        import resource
        import sys

        max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            max_rss_mb = max_rss_bytes / (1024 * 1024)
        else:
            max_rss_mb = max_rss_bytes / 1024

        logger.info(
            f"{prefix}Memory stats" if prefix else "Memory stats",
            peak_rss_mb=f"{max_rss_mb:.2f} MB",
        )


def make_chunk_processor(
    process_single_row_fn: Callable[[pd.Series, Dict[str, Any]], Dict[str, Any]],
) -> Callable[[pd.DataFrame, Dict[str, Any], int], pd.DataFrame]:
    """
    Factory function to create a chunk processor from a row processor.

    Use this when your logic is naturally row-based but you want to
    benefit from vectorized chunk processing.

    Args:
        process_single_row_fn: Function(row, reference_data) -> dict

    Returns:
        A chunk processor function suitable for StreamingProcessor.process_chunks()
    """

    def chunk_processor(chunk_df: pd.DataFrame, reference_data: Dict[str, Any], chunk_idx: int) -> pd.DataFrame:
        results = []
        for _, row in chunk_df.iterrows():
            result = process_single_row_fn(row, reference_data)
            if result:
                results.append(result)
        return pd.DataFrame(results) if results else pd.DataFrame()

    return chunk_processor
