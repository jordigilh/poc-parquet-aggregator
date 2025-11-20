"""Utility functions for OCP aggregation."""

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog


def setup_logging(level: str = "INFO", log_format: str = "console"):
    """Set up structured logging.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_format: Format type ("console" or "json")
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if log_format == "json":
        processors = [
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    else:
        processors = [
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name

    Returns:
        Structured logger
    """
    return structlog.get_logger(name)


def parse_json_labels(labels_str: Optional[str]) -> Dict[str, str]:
    """Parse labels string into dictionary.

    Handles two formats:
    1. Pipe-delimited: "label_app:test|label_tier:frontend"
    2. JSON: '{"app": "nginx", "env": "prod"}'

    Args:
        labels_str: Labels string in either format

    Returns:
        Dictionary of labels
    """
    if not labels_str or labels_str == 'null' or labels_str == '':
        return {}

    labels_str = str(labels_str).strip()

    # Handle pipe-delimited format (from nise CSV)
    if '|' in labels_str or (':' in labels_str and '{' not in labels_str):
        result = {}
        pairs = labels_str.split('|') if '|' in labels_str else [labels_str]
        for pair in pairs:
            pair = pair.strip()
            if ':' in pair:
                key, value = pair.split(':', 1)
                # Remove 'label_' prefix if present
                key = key.replace('label_', '').strip()
                result[key] = value.strip()
        return result

    # Handle JSON format
    try:
        return json.loads(labels_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def filter_labels_by_enabled_keys(labels: Dict[str, str], enabled_keys: List[str]) -> Dict[str, str]:
    """Filter labels to only include enabled keys.

    Args:
        labels: Full label dictionary
        enabled_keys: List of enabled tag keys

    Returns:
        Filtered label dictionary
    """
    if not enabled_keys:
        return {}

    return {k: v for k, v in labels.items() if k in enabled_keys}


def merge_label_dicts(*label_dicts: Dict[str, str]) -> Dict[str, str]:
    """Merge multiple label dictionaries (later dicts override earlier ones).

    Args:
        *label_dicts: Variable number of label dictionaries

    Returns:
        Merged label dictionary
    """
    result = {}
    for labels in label_dicts:
        if labels:
            result.update(labels)
    return result


def labels_to_json_string(labels: Dict[str, str]) -> str:
    """Convert label dictionary to JSON string.

    Replicates Trino SQL line 229: json_format(cast(pua.pod_labels as json))

    The output must be compatible with PostgreSQL JSONB type.

    Args:
        labels: Label dictionary

    Returns:
        JSON string representation (sorted keys, UTF-8, no extra whitespace)
    """
    if not labels:
        return '{}'

    # json.dumps with sort_keys=True matches Trino's json_format() behavior:
    # - Sorted keys for deterministic output
    # - UTF-8 encoding
    # - Compact format (no extra whitespace) - use separators=(',', ':')
    # - Proper escaping of special characters
    result = json.dumps(labels, sort_keys=True, ensure_ascii=False, separators=(',', ':'))

    # Validate it's valid JSON
    try:
        json.loads(result)
    except json.JSONDecodeError as e:
        logger = get_logger("json_validation")
        logger.error(f"Generated invalid JSON: {result}, error: {e}")
        return '{}'

    return result


def convert_bytes_to_gigabytes(bytes_value: float) -> float:
    """Convert bytes to gigabytes (binary: 1 GB = 2^30 bytes).

    Args:
        bytes_value: Value in bytes

    Returns:
        Value in gigabytes
    """
    return bytes_value * pow(2, -30)


def convert_seconds_to_hours(seconds: float) -> float:
    """Convert seconds to hours.

    Args:
        seconds: Value in seconds

    Returns:
        Value in hours
    """
    return seconds / 3600.0


def safe_max(*values: Optional[float]) -> Optional[float]:
    """Get maximum value, ignoring None values.

    Args:
        *values: Variable number of numeric values or None

    Returns:
        Maximum value or None if all are None
    """
    filtered = [v for v in values if v is not None]
    return max(filtered) if filtered else None


def safe_sum(*values: Optional[float]) -> float:
    """Sum values, treating None as 0.

    Args:
        *values: Variable number of numeric values or None

    Returns:
        Sum of values
    """
    return sum(v for v in values if v is not None)


def safe_greatest(*values: Optional[float]) -> Optional[float]:
    """Get the greatest value (SQL GREATEST equivalent).

    Args:
        *values: Variable number of numeric values or None

    Returns:
        Greatest value or None if all are None
    """
    return safe_max(*values)


def coalesce(*values: Any) -> Any:
    """Return the first non-None value (SQL COALESCE equivalent).

    Args:
        *values: Variable number of values

    Returns:
        First non-None value or None if all are None
    """
    for v in values:
        if v is not None:
            return v
    return None


def date_to_string(d: date, format: str = "%Y-%m-%d") -> str:
    """Convert date to string.

    Args:
        d: Date object
        format: Date format string

    Returns:
        Formatted date string
    """
    return d.strftime(format)


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format.

    Args:
        date_str: Date string

    Returns:
        Date object
    """
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def calculate_effective_usage(usage: Optional[float], request: Optional[float]) -> Optional[float]:
    """Calculate effective usage (max of usage and request).

    This replicates Trino's GREATEST(usage, request) logic.

    Args:
        usage: Actual usage value
        request: Requested value

    Returns:
        Effective usage (greater of the two)
    """
    return safe_greatest(usage, request)


def round_decimal(value: float, precision: int = 9) -> Decimal:
    """Round float to Decimal with specified precision.

    Args:
        value: Float value
        precision: Number of decimal places

    Returns:
        Decimal value
    """
    if value is None:
        return Decimal('0')
    return Decimal(str(round(value, precision)))


class PerformanceTimer:
    """Context manager for timing code execution."""

    def __init__(self, name: str, logger: Optional[structlog.BoundLogger] = None):
        """Initialize timer.

        Args:
            name: Name of the timed operation
            logger: Logger instance (optional)
        """
        self.name = name
        self.logger = logger or get_logger("performance")
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        """Start timer."""
        self.start_time = datetime.now()
        self.logger.info(f"Starting: {self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timer and log duration."""
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()

        if exc_type is None:
            self.logger.info(
                f"Completed: {self.name}",
                duration_seconds=round(duration, 3)
            )
        else:
            self.logger.error(
                f"Failed: {self.name}",
                duration_seconds=round(duration, 3),
                error=str(exc_val)
            )

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get duration in seconds.

        Returns:
            Duration in seconds or None if timer hasn't finished
        """
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


def format_bytes(bytes_value: int) -> str:
    """Format bytes as human-readable string.

    Args:
        bytes_value: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 MB", "2.3 GB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2.3s", "1m 30s", "1h 15m")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"



def optimize_dataframe_memory(df, categorical_columns=None, logger=None):
    """Optimize DataFrame memory usage.

    Args:
        df: pandas DataFrame
        categorical_columns: List of columns to convert to categorical
        logger: Optional logger

    Returns:
        Optimized DataFrame
    """
    import pandas as pd
    import gc
    
    if df.empty:
        return df
    
    initial_memory = df.memory_usage(deep=True).sum()
    
    # Convert string columns to categorical if specified
    if categorical_columns:
        for col in categorical_columns:
            if col in df.columns and df[col].dtype == 'object':
                df[col] = df[col].astype('category')
    
    # Downcast numeric columns
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='float')
    
    for col in df.select_dtypes(include=['int64']).columns:
        df[col] = pd.to_numeric(df[col], downcast='integer')
    
    final_memory = df.memory_usage(deep=True).sum()
    reduction = (1 - final_memory / initial_memory) * 100
    
    if logger:
        logger.info(
            "Memory optimization complete",
            initial=format_bytes(initial_memory),
            final=format_bytes(final_memory),
            reduction_percent=f"{reduction:.1f}%"
        )
    
    # Force garbage collection
    gc.collect()
    
    return df


def cleanup_memory(logger=None):
    """Force garbage collection to free memory.

    Args:
        logger: Optional logger
    """
    import gc
    
    collected = gc.collect()
    
    if logger:
        logger.debug(f"Garbage collection: freed {collected} objects")


def get_memory_usage():
    """Get current process memory usage.

    Returns:
        Memory usage in bytes
    """
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    return process.memory_info().rss


def log_memory_usage(logger, context=""):
    """Log current memory usage.

    Args:
        logger: Logger instance
        context: Optional context string
    """
    try:
        memory_bytes = get_memory_usage()
        logger.info(
            f"Memory usage{': ' + context if context else ''}",
            memory=format_bytes(memory_bytes)
        )
    except ImportError:
        # psutil not available
        pass
