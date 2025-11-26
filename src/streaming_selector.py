"""Automatic streaming mode selection based on data size and available memory."""

import psutil
from typing import Optional, Dict, Any
from .logger import get_logger

logger = get_logger("streaming_selector")


def determine_streaming_mode(
    config: Dict[str, Any],
    estimated_rows: Optional[int] = None,
    force_mode: Optional[bool] = None
) -> bool:
    """
    Automatically determine if streaming should be used based on data size and available memory.

    Decision Logic:
    1. If force_mode is provided, use it (manual override via CLI or explicit config)
    2. If use_streaming is explicitly True/False in config, use it (manual config)
    3. If use_streaming is 'auto' or not set, use auto-detection:
       a. Check estimated row count vs streaming_threshold_rows
       b. Check available system memory vs streaming_memory_threshold_gb
       c. Default to in-memory if both checks pass

    Args:
        config: Configuration dictionary
        estimated_rows: Estimated number of rows to process (if known)
        force_mode: Force a specific mode (True=streaming, False=in-memory)

    Returns:
        True if streaming should be used, False for in-memory
    """
    perf_config = config.get('performance', {})

    # 1. Check for force override (highest priority)
    if force_mode is not None:
        mode_str = "streaming" if force_mode else "in-memory"
        logger.info(f"🎯 Streaming mode FORCED: {mode_str}", force_mode=force_mode)
        return force_mode

    # 2. Check for explicit manual configuration
    use_streaming_config = perf_config.get('use_streaming', 'auto')

    # Handle string "true"/"false" from environment variables
    if isinstance(use_streaming_config, str):
        if use_streaming_config.lower() == 'true':
            use_streaming_config = True
        elif use_streaming_config.lower() == 'false':
            use_streaming_config = False
        # else keep as string (e.g., 'auto')

    if isinstance(use_streaming_config, bool):
        # Explicit True or False
        mode_str = "streaming" if use_streaming_config else "in-memory"
        logger.info(f"🎯 Streaming mode SET manually: {mode_str}",
                   use_streaming=use_streaming_config)
        return use_streaming_config

    # 3. Auto-detection mode
    if use_streaming_config == 'auto' or use_streaming_config not in [True, False]:
        logger.info("🤖 Auto-detecting optimal streaming mode...")

        # Get thresholds from config
        row_threshold = perf_config.get('streaming_threshold_rows', 500000)
        memory_threshold_gb = perf_config.get('streaming_memory_threshold_gb', 2.0)

        reasons = []
        should_stream = False

        # Check A: Row count threshold
        if estimated_rows is not None:
            if estimated_rows > row_threshold:
                should_stream = True
                reasons.append(
                    f"estimated {estimated_rows:,} rows > {row_threshold:,} threshold"
                )
                logger.info(
                    "📊 Row count exceeds threshold",
                    estimated_rows=estimated_rows,
                    threshold=row_threshold
                )
            else:
                reasons.append(
                    f"estimated {estimated_rows:,} rows <= {row_threshold:,} threshold"
                )
                logger.debug(
                    "📊 Row count within threshold",
                    estimated_rows=estimated_rows,
                    threshold=row_threshold
                )
        else:
            logger.debug("📊 Row count unknown, checking memory only")

        # Check B: Available memory
        try:
            vm = psutil.virtual_memory()
            available_memory_gb = vm.available / (1024**3)
            total_memory_gb = vm.total / (1024**3)
            memory_percent = vm.percent

            logger.info(
                "💾 System memory status",
                available_gb=f"{available_memory_gb:.2f}",
                total_gb=f"{total_memory_gb:.2f}",
                used_percent=f"{memory_percent:.1f}%"
            )

            if available_memory_gb < memory_threshold_gb:
                should_stream = True
                reasons.append(
                    f"available memory {available_memory_gb:.1f} GB < {memory_threshold_gb} GB threshold"
                )
                logger.warning(
                    "⚠️  Low memory detected, enabling streaming",
                    available_gb=f"{available_memory_gb:.2f}",
                    threshold_gb=memory_threshold_gb
                )
            else:
                reasons.append(
                    f"available memory {available_memory_gb:.1f} GB >= {memory_threshold_gb} GB"
                )
                logger.debug(
                    "✅ Sufficient memory available",
                    available_gb=f"{available_memory_gb:.2f}",
                    threshold_gb=memory_threshold_gb
                )
        except Exception as e:
            logger.warning(
                f"Could not check system memory: {e}. Defaulting based on row count only."
            )
            reasons.append("memory check unavailable")

        # Make decision
        if should_stream:
            logger.info(
                f"✅ AUTO-SELECTED: Streaming mode (reasons: {'; '.join(reasons)})"
            )
        else:
            logger.info(
                f"✅ AUTO-SELECTED: In-memory mode (reasons: {'; '.join(reasons)})"
            )

        return should_stream

    # 4. Fallback (shouldn't reach here)
    logger.warning(
        f"Unknown use_streaming value: {use_streaming_config}. Defaulting to in-memory."
    )
    return False


def estimate_parquet_rows(
    s3_filesystem,
    bucket: str,
    prefix: str,
    sample_files: int = 5
) -> Optional[int]:
    """
    Estimate total row count by sampling Parquet files.

    Args:
        s3_filesystem: s3fs filesystem instance
        bucket: S3 bucket name
        prefix: Path prefix to Parquet files
        sample_files: Number of files to sample (default: 5)

    Returns:
        Estimated total row count, or None if cannot estimate
    """
    try:
        import pyarrow.parquet as pq

        # List Parquet files
        path = f"{bucket}/{prefix}"
        files = s3_filesystem.glob(f"{path}/**/*.parquet")

        if not files:
            logger.debug(f"No Parquet files found at {path}")
            return None

        total_files = len(files)
        logger.debug(f"Found {total_files} Parquet files, sampling {min(sample_files, total_files)}")

        # Sample a few files to estimate average rows per file
        sample_count = min(sample_files, total_files)
        sampled_files = files[:sample_count]

        total_rows_sampled = 0
        for file_path in sampled_files:
            try:
                with s3_filesystem.open(file_path, 'rb') as f:
                    parquet_file = pq.ParquetFile(f)
                    rows = parquet_file.metadata.num_rows
                    total_rows_sampled += rows
            except Exception as e:
                logger.debug(f"Could not read {file_path}: {e}")
                continue

        if total_rows_sampled == 0:
            return None

        # Estimate total rows
        avg_rows_per_file = total_rows_sampled / sample_count
        estimated_total = int(avg_rows_per_file * total_files)

        logger.info(
            f"📊 Estimated row count: {estimated_total:,} "
            f"(avg {avg_rows_per_file:.0f} rows/file × {total_files} files)"
        )

        return estimated_total

    except Exception as e:
        logger.warning(f"Could not estimate row count: {e}")
        return None


def log_streaming_decision(
    use_streaming: bool,
    estimated_rows: Optional[int] = None,
    chunk_size: Optional[int] = None
) -> None:
    """
    Log the final streaming mode decision with context.

    Args:
        use_streaming: Whether streaming mode is enabled
        estimated_rows: Estimated row count (if known)
        chunk_size: Chunk size for streaming (if applicable)
    """
    if use_streaming:
        msg = "🌊 STREAMING MODE ENABLED"
        details = {
            "mode": "streaming",
            "memory_usage": "constant (~20-50 MB)",
            "performance": "10-20% slower than in-memory",
            "chunk_size": chunk_size
        }
        if estimated_rows:
            details["estimated_rows"] = f"{estimated_rows:,}"

        logger.info(msg, **details)
    else:
        msg = "💾 IN-MEMORY MODE ENABLED"
        details = {
            "mode": "in-memory",
            "memory_usage": "proportional to data size",
            "performance": "fastest for small/medium data"
        }
        if estimated_rows:
            details["estimated_rows"] = f"{estimated_rows:,}"
            # Rough estimate: 60 bytes per row on average
            estimated_mb = (estimated_rows * 60) / (1024 * 1024)
            details["estimated_memory_mb"] = f"~{estimated_mb:.0f}"

        logger.info(msg, **details)

