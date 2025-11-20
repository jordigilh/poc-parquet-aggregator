#!/usr/bin/env python3
"""Empirical performance benchmarking script.

Measures actual memory usage, CPU consumption, and processing time
for different dataset sizes.
"""

import os
import sys
import time
import psutil
import gc
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import get_config
from src.utils import setup_logging, get_logger, format_bytes
from src.parquet_reader import ParquetReader
from src.aggregator_pod import PodAggregator, calculate_node_capacity
from src.db_writer import DatabaseWriter


class PerformanceBenchmark:
    """Benchmark POC performance with empirical measurements."""

    def __init__(self, config):
        self.config = config
        self.logger = get_logger("benchmark")
        self.process = psutil.Process(os.getpid())
        self.measurements = []

    def get_memory_usage(self):
        """Get current memory usage in bytes."""
        return self.process.memory_info().rss

    def get_cpu_percent(self):
        """Get current CPU usage percentage."""
        return self.process.cpu_percent(interval=0.1)

    def measure_phase(self, phase_name, func, *args, **kwargs):
        """Measure memory and CPU for a specific phase.

        Args:
            phase_name: Name of the phase
            func: Function to execute
            *args, **kwargs: Arguments for the function

        Returns:
            Tuple of (result, measurement_dict)
        """
        # Force garbage collection before measurement
        gc.collect()
        
        # Initial measurements
        mem_before = self.get_memory_usage()
        cpu_before = self.process.cpu_times()
        time_start = time.time()

        # Execute function
        result = func(*args, **kwargs)

        # Final measurements
        time_end = time.time()
        cpu_after = self.process.cpu_times()
        mem_after = self.get_memory_usage()
        mem_peak = self.process.memory_info().rss  # Peak during execution

        # Calculate metrics
        duration = time_end - time_start
        mem_used = mem_after - mem_before
        mem_delta = mem_peak - mem_before
        cpu_user = cpu_after.user - cpu_before.user
        cpu_system = cpu_after.system - cpu_before.system
        cpu_total = cpu_user + cpu_system

        measurement = {
            'phase': phase_name,
            'duration_seconds': duration,
            'memory_before_bytes': mem_before,
            'memory_after_bytes': mem_after,
            'memory_used_bytes': mem_used,
            'memory_peak_bytes': mem_peak,
            'memory_delta_bytes': mem_delta,
            'cpu_user_seconds': cpu_user,
            'cpu_system_seconds': cpu_system,
            'cpu_total_seconds': cpu_total,
        }

        self.measurements.append(measurement)

        self.logger.info(
            f"Phase: {phase_name}",
            duration=f"{duration:.2f}s",
            memory_before=format_bytes(mem_before),
            memory_after=format_bytes(mem_after),
            memory_used=format_bytes(mem_used),
            memory_peak=format_bytes(mem_peak),
            cpu_total=f"{cpu_total:.2f}s"
        )

        return result, measurement

    def run_benchmark(self, provider_uuid, year, month):
        """Run full benchmark for a specific dataset.

        Args:
            provider_uuid: Provider UUID
            year: Year
            month: Month

        Returns:
            Dictionary with benchmark results
        """
        self.logger.info("=" * 80)
        self.logger.info(f"Starting benchmark: {provider_uuid} {year}-{month}")
        self.logger.info("=" * 80)

        # Initialize components
        parquet_reader, _ = self.measure_phase(
            "Initialize ParquetReader",
            lambda: ParquetReader(self.config)
        )

        db_writer, _ = self.measure_phase(
            "Initialize DatabaseWriter",
            lambda: DatabaseWriter(self.config)
        )

        # Fetch enabled tag keys
        def fetch_tags():
            with db_writer:
                enabled_tags = db_writer.get_enabled_tag_keys()
                cost_category = db_writer.get_cost_category_namespaces()
            return enabled_tags, cost_category

        (enabled_tag_keys, cost_category_df), _ = self.measure_phase(
            "Fetch enabled tags",
            fetch_tags
        )

        # Read pod usage (daily)
        pod_usage_daily_df, read_daily_measurement = self.measure_phase(
            "Read pod usage (daily)",
            parquet_reader.read_pod_usage_line_items,
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            daily=True,
            streaming=False
        )

        daily_rows = len(pod_usage_daily_df)
        self.logger.info(f"Daily rows: {daily_rows:,}")

        # Read pod usage (hourly) for capacity
        pod_usage_hourly_df, read_hourly_measurement = self.measure_phase(
            "Read pod usage (hourly)",
            parquet_reader.read_pod_usage_line_items,
            provider_uuid=provider_uuid,
            year=year,
            month=month,
            daily=False,
            streaming=False
        )

        hourly_rows = len(pod_usage_hourly_df)
        self.logger.info(f"Hourly rows: {hourly_rows:,}")

        # Read node labels
        node_labels_df, _ = self.measure_phase(
            "Read node labels",
            parquet_reader.read_node_labels_line_items,
            provider_uuid=provider_uuid,
            year=year,
            month=month
        )

        # Read namespace labels
        namespace_labels_df, _ = self.measure_phase(
            "Read namespace labels",
            parquet_reader.read_namespace_labels_line_items,
            provider_uuid=provider_uuid,
            year=year,
            month=month
        )

        # Calculate capacity
        (node_capacity_df, cluster_capacity_df), capacity_measurement = self.measure_phase(
            "Calculate node/cluster capacity",
            calculate_node_capacity,
            pod_usage_hourly_df
        )

        # Aggregate pod usage
        aggregator = PodAggregator(self.config, enabled_tag_keys)
        
        aggregated_df, aggregation_measurement = self.measure_phase(
            "Aggregate pod usage",
            aggregator.aggregate,
            pod_usage_df=pod_usage_daily_df,
            node_capacity_df=node_capacity_df,
            node_labels_df=node_labels_df,
            namespace_labels_df=namespace_labels_df,
            cost_category_df=cost_category_df
        )

        output_rows = len(aggregated_df)
        self.logger.info(f"Output rows: {output_rows:,}")
        self.logger.info(f"Compression ratio: {daily_rows / output_rows if output_rows > 0 else 0:.1f}x")

        # Calculate totals
        total_duration = sum(m['duration_seconds'] for m in self.measurements)
        total_cpu = sum(m['cpu_total_seconds'] for m in self.measurements)
        peak_memory = max(m['memory_peak_bytes'] for m in self.measurements)
        final_memory = self.measurements[-1]['memory_after_bytes']

        # Calculate per-row metrics
        memory_per_1k_input = (peak_memory / daily_rows * 1000) if daily_rows > 0 else 0
        memory_per_1k_output = (peak_memory / output_rows * 1000) if output_rows > 0 else 0
        rows_per_second = daily_rows / total_duration if total_duration > 0 else 0

        summary = {
            'provider_uuid': provider_uuid,
            'year': year,
            'month': month,
            'timestamp': datetime.now().isoformat(),
            'input_rows_daily': daily_rows,
            'input_rows_hourly': hourly_rows,
            'output_rows': output_rows,
            'compression_ratio': daily_rows / output_rows if output_rows > 0 else 0,
            'total_duration_seconds': total_duration,
            'total_cpu_seconds': total_cpu,
            'peak_memory_bytes': peak_memory,
            'final_memory_bytes': final_memory,
            'memory_per_1k_input_rows_bytes': memory_per_1k_input,
            'memory_per_1k_output_rows_bytes': memory_per_1k_output,
            'rows_per_second': rows_per_second,
            'phases': self.measurements
        }

        self.logger.info("=" * 80)
        self.logger.info("BENCHMARK SUMMARY")
        self.logger.info("=" * 80)
        self.logger.info(f"Input rows (daily): {daily_rows:,}")
        self.logger.info(f"Input rows (hourly): {hourly_rows:,}")
        self.logger.info(f"Output rows: {output_rows:,}")
        self.logger.info(f"Compression ratio: {summary['compression_ratio']:.1f}x")
        self.logger.info(f"Total duration: {total_duration:.2f}s")
        self.logger.info(f"Total CPU time: {total_cpu:.2f}s")
        self.logger.info(f"Peak memory: {format_bytes(peak_memory)}")
        self.logger.info(f"Final memory: {format_bytes(final_memory)}")
        self.logger.info(f"Memory per 1K input rows: {format_bytes(int(memory_per_1k_input))}")
        self.logger.info(f"Processing rate: {rows_per_second:,.0f} rows/sec")
        self.logger.info("=" * 80)

        return summary


def main():
    """Main benchmark entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark POC performance")
    parser.add_argument(
        '--config',
        default='config/config.yaml',
        help='Configuration file path'
    )
    parser.add_argument(
        '--provider-uuid',
        help='Provider UUID (overrides config)'
    )
    parser.add_argument(
        '--year',
        help='Year (overrides config)'
    )
    parser.add_argument(
        '--month',
        help='Month (overrides config)'
    )
    parser.add_argument(
        '--output',
        help='Output JSON file for results'
    )

    args = parser.parse_args()

    # Load configuration
    config = get_config(args.config)

    # Setup logging
    setup_logging(
        level='INFO',
        log_format='console'
    )

    # Get parameters
    provider_uuid = args.provider_uuid or os.getenv('OCP_PROVIDER_UUID') or config['ocp']['provider_uuid']
    year = args.year or os.getenv('POC_YEAR') or config['ocp']['year']
    month = args.month or os.getenv('POC_MONTH') or config['ocp']['month']

    # Run benchmark
    benchmark = PerformanceBenchmark(config)
    results = benchmark.run_benchmark(provider_uuid, year, month)

    # Save results if requested
    if args.output:
        import json
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n✓ Results saved to: {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

