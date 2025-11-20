"""Calculate expected aggregation results from nise static YAML.

This module parses nise OCP static YAML configurations and calculates
the expected daily aggregation results that would be produced by the
Trino SQL or the Parquet aggregator.

Edge cases handled:
- Date fields can be strings, datetime.date objects, or templates ({{start_date}})
- Namespaces can have pods, volumes, or both
- Volumes can have empty or missing volume_claims
- All numeric fields (cpu_request, mem_request_gig, etc.)
- YAML structure: `- node:` creates {'node': None, 'node_name': 'xxx', ...}
"""

from datetime import datetime, timedelta, date as date_type
from typing import Dict, List, Optional
import yaml
import pandas as pd
from pathlib import Path
import re

from .utils import get_logger


class ExpectedResultsCalculator:
    """Calculate expected aggregation results from nise static YAML configuration."""

    def __init__(self, yaml_path: str):
        """Initialize calculator with YAML path.

        Args:
            yaml_path: Path to nise static YAML file
        """
        self.yaml_path = Path(yaml_path)
        self.logger = get_logger("expected_results")
        self.config = self._load_yaml()

    def _load_yaml(self) -> Dict:
        """Load and parse YAML file.

        Returns:
            Parsed YAML configuration
        """
        with open(self.yaml_path, 'r') as f:
            config = yaml.safe_load(f)

        self.logger.info(f"Loaded YAML configuration: {self.yaml_path}")
        return config

    def _parse_date(self, date_value) -> Optional[date_type]:
        """Parse date from various formats.

        Args:
            date_value: String, date object, or template

        Returns:
            date object or None if template
        """
        if date_value is None:
            return None

        # Already a date object
        if isinstance(date_value, date_type):
            return date_value

        # String
        if isinstance(date_value, str):
            # Template (e.g., {{start_date}})
            if '{{' in date_value:
                self.logger.warning(f"Skipping template date: {date_value}")
                return None

            # Parse YYYY-MM-DD
            try:
                return datetime.strptime(date_value, '%Y-%m-%d').date()
            except ValueError:
                self.logger.error(f"Invalid date format: {date_value}")
                return None

        return None

    def calculate_expected_aggregations(self) -> pd.DataFrame:
        """Calculate expected daily aggregations from YAML configuration.

        Returns:
            DataFrame with expected results
        """
        results = []

        # Extract OCP generator config
        for generator in self.config.get('generators', []):
            if 'OCPGenerator' not in generator:
                continue

            ocp_gen = generator['OCPGenerator']

            # Parse dates
            start_date = self._parse_date(ocp_gen.get('start_date'))
            end_date = self._parse_date(ocp_gen.get('end_date'))

            if not start_date or not end_date:
                self.logger.warning("Skipping generator with template dates")
                continue

            # Generate results for each day in range
            current_date = start_date
            while current_date <= end_date:
                # Process each node
                for node in ocp_gen.get('nodes', []):
                    node_results = self._process_node(node, current_date)
                    results.extend(node_results)

                current_date += timedelta(days=1)

        if not results:
            self.logger.warning("No results generated")
            return pd.DataFrame()

        df = pd.DataFrame(results)

        self.logger.info(
            f"Calculated expected results",
            total_rows=len(df),
            namespaces=df['namespace'].nunique() if not df.empty else 0,
            nodes=df['node'].nunique() if not df.empty else 0
        )

        return df

    def _process_node(self, node: Dict, date: date_type) -> List[Dict]:
        """Process a node configuration for a specific date.

        Args:
            node: Node configuration dictionary
            date: Date for aggregation

        Returns:
            List of expected result dictionaries (one per namespace)
        """
        results = []

        # YAML structure: `- node:` creates {'node': None, 'node_name': 'xxx', ...}
        # All node properties are at the root level
        node_name = node.get('node_name')
        cpu_cores = node.get('cpu_cores', 0)
        memory_gig = node.get('memory_gig', 0)
        resource_id = node.get('resource_id', 0)

        if not node_name:
            self.logger.warning(f"Skipping node without node_name: {node}")
            return results

        # Node capacity (full day = 24 hours)
        node_capacity_cpu_core_hours = float(cpu_cores) * 24.0
        node_capacity_memory_gigabyte_hours = float(memory_gig) * 24.0

        # Process each namespace
        namespaces = node.get('namespaces', {})
        for namespace_name, namespace_config in namespaces.items():
            # Initialize aggregates for this namespace-node combination
            agg = {
                'usage_start': date,
                'usage_end': date,
                'namespace': namespace_name,
                'node': node_name,
                'resource_id': str(resource_id),
                'pod_usage_cpu_core_hours': 0.0,
                'pod_request_cpu_core_hours': 0.0,
                'pod_effective_usage_cpu_core_hours': 0.0,
                'pod_limit_cpu_core_hours': 0.0,
                'pod_usage_memory_gigabyte_hours': 0.0,
                'pod_request_memory_gigabyte_hours': 0.0,
                'pod_effective_usage_memory_gigabyte_hours': 0.0,
                'pod_limit_memory_gigabyte_hours': 0.0,
                'node_capacity_cpu_cores': float(cpu_cores),
                'node_capacity_cpu_core_hours': node_capacity_cpu_core_hours,
                'node_capacity_memory_gigabytes': float(memory_gig),
                'node_capacity_memory_gigabyte_hours': node_capacity_memory_gigabyte_hours,
                'data_source': 'Pod',
            }

            # Sum across all pods in this namespace
            pods = namespace_config.get('pods', [])
            for pod in pods:
                # YAML structure: `- pod:` creates {'pod': None, 'pod_name': 'xxx', ...}
                self._aggregate_pod(pod, agg)

            # Only add if there are pods in this namespace
            # (storage-only namespaces are skipped as POC only handles Pod data)
            if pods:
                results.append(agg)

        return results

    def _aggregate_pod(self, pod: Dict, agg: Dict):
        """Aggregate a single pod's metrics into the accumulator.

        Replicates Trino SQL lines 275-288:
        - CPU: sum(seconds) / 3600.0
        - Memory: sum(byte_seconds) / 3600.0 * power(2, -30)
        - Effective: coalesce(field, greatest(usage, request))

        Args:
            pod: Pod configuration dictionary
            agg: Accumulator dictionary (modified in place)
        """
        # Skip pods with missing pod_seconds
        pod_seconds = pod.get('pod_seconds', 0)
        if not pod_seconds:
            return

        # Convert pod_seconds to hours
        pod_hours = float(pod_seconds) / 3600.0

        # CPU metrics
        cpu_request = float(pod.get('cpu_request', 0))
        cpu_limit = float(pod.get('cpu_limit', 0))

        # For nise data, usage = request (no separate usage field)
        cpu_usage = cpu_request

        agg['pod_usage_cpu_core_hours'] += cpu_usage * pod_hours
        agg['pod_request_cpu_core_hours'] += cpu_request * pod_hours
        agg['pod_limit_cpu_core_hours'] += cpu_limit * pod_hours

        # Effective usage = max(usage, request)
        cpu_effective = max(cpu_usage, cpu_request)
        agg['pod_effective_usage_cpu_core_hours'] += cpu_effective * pod_hours

        # Memory metrics
        mem_request_gig = float(pod.get('mem_request_gig', 0))
        mem_limit_gig = float(pod.get('mem_limit_gig', 0))

        # For nise data, usage = request
        mem_usage_gig = mem_request_gig

        agg['pod_usage_memory_gigabyte_hours'] += mem_usage_gig * pod_hours
        agg['pod_request_memory_gigabyte_hours'] += mem_request_gig * pod_hours
        agg['pod_limit_memory_gigabyte_hours'] += mem_limit_gig * pod_hours

        # Effective usage = max(usage, request)
        mem_effective_gig = max(mem_usage_gig, mem_request_gig)
        agg['pod_effective_usage_memory_gigabyte_hours'] += mem_effective_gig * pod_hours

    def print_summary(self, df: pd.DataFrame):
        """Print a summary of expected results.

        Args:
            df: DataFrame with expected results
        """
        if df.empty:
            print("No results to display")
            return

        print("\n" + "=" * 80)
        print("EXPECTED RESULTS SUMMARY")
        print("=" * 80)
        print(f"YAML Configuration: {self.yaml_path.name}")
        print(f"Total Rows: {len(df)}")
        print(f"Date Range: {df['usage_start'].min()} to {df['usage_start'].max()}")
        print(f"Days: {df['usage_start'].nunique()}")
        print(f"Nodes: {df['node'].nunique()} ({', '.join(sorted(df['node'].unique()))})")
        print(f"Namespaces: {df['namespace'].nunique()} ({', '.join(sorted(df['namespace'].unique()))})")
        print()

        print("Total Metrics Across All Days:")
        print(f"  CPU Request:      {df['pod_request_cpu_core_hours'].sum():>10.2f} core-hours")
        print(f"  CPU Effective:    {df['pod_effective_usage_cpu_core_hours'].sum():>10.2f} core-hours")
        print(f"  Memory Request:   {df['pod_request_memory_gigabyte_hours'].sum():>10.2f} GB-hours")
        print(f"  Memory Effective: {df['pod_effective_usage_memory_gigabyte_hours'].sum():>10.2f} GB-hours")
        print(f"  Node CPU Capacity:{df['node_capacity_cpu_core_hours'].sum():>10.2f} core-hours")
        print(f"  Node Mem Capacity:{df['node_capacity_memory_gigabyte_hours'].sum():>10.2f} GB-hours")
        print()

        print("Per-Day Breakdown:")
        for date in sorted(df['usage_start'].unique()):
            day_df = df[df['usage_start'] == date]
            print(f"\n  {date}:")
            print(f"    Namespace-Node Combinations: {len(day_df)}")
            print(f"    CPU Request:    {day_df['pod_request_cpu_core_hours'].sum():>8.2f} core-hours")
            print(f"    Memory Request: {day_df['pod_request_memory_gigabyte_hours'].sum():>8.2f} GB-hours")

            # Show detail for first day only
            if date == sorted(df['usage_start'].unique())[0]:
                print(f"\n    Details:")
                for _, row in day_df.iterrows():
                    print(f"      {row['namespace']:20s} @ {row['node']:20s}: "
                          f"CPU={row['pod_request_cpu_core_hours']:6.2f}, "
                          f"Mem={row['pod_request_memory_gigabyte_hours']:6.2f}")

        print("\n" + "=" * 80)
        print()

    def save_to_csv(self, df: pd.DataFrame, output_path: str):
        """Save expected results to CSV.

        Args:
            df: DataFrame with expected results
            output_path: Path to output CSV file
        """
        df.to_csv(output_path, index=False)
        self.logger.info(f"Saved expected results to: {output_path}")


def compare_results(expected_df: pd.DataFrame, actual_df: pd.DataFrame, tolerance: float = 0.0001) -> Dict:
    """Compare expected vs actual aggregation results.

    Args:
        expected_df: DataFrame with expected results
        actual_df: DataFrame with actual POC results
        tolerance: Acceptable relative difference (default 0.01%)

    Returns:
        Dictionary with comparison results
    """
    logger = get_logger("compare_results")

    # Merge on key columns
    merge_keys = ['usage_start', 'namespace', 'node']

    comparison = expected_df.merge(
        actual_df,
        on=merge_keys,
        how='outer',
        suffixes=('_expected', '_actual'),
        indicator=True
    )

    # Metrics to compare
    metrics = [
        'pod_usage_cpu_core_hours',
        'pod_request_cpu_core_hours',
        'pod_effective_usage_cpu_core_hours',
        'pod_limit_cpu_core_hours',
        'pod_usage_memory_gigabyte_hours',
        'pod_request_memory_gigabyte_hours',
        'pod_effective_usage_memory_gigabyte_hours',
        'pod_limit_memory_gigabyte_hours',
        'node_capacity_cpu_core_hours',
        'node_capacity_memory_gigabyte_hours',
    ]

    issues = []
    match_count = 0
    total_comparisons = 0

    # Check for missing rows
    missing_in_actual = comparison[comparison['_merge'] == 'left_only']
    missing_in_expected = comparison[comparison['_merge'] == 'right_only']

    if not missing_in_actual.empty:
        issues.append(f"Missing in actual: {len(missing_in_actual)} rows")
        for _, row in missing_in_actual.iterrows():
            issues.append(f"  - {row['usage_start']}, {row['namespace']}, {row['node']}")

    if not missing_in_expected.empty:
        issues.append(f"Extra in actual: {len(missing_in_expected)} rows")
        for _, row in missing_in_expected.iterrows():
            issues.append(f"  - {row['usage_start']}, {row['namespace']}, {row['node']}")

    # Compare values for matching rows
    both = comparison[comparison['_merge'] == 'both']

    for metric in metrics:
        expected_col = f"{metric}_expected"
        actual_col = f"{metric}_actual"

        if expected_col not in both.columns or actual_col not in both.columns:
            continue

        for _, row in both.iterrows():
            expected_val = row[expected_col]
            actual_val = row[actual_col]

            total_comparisons += 1

            # Handle None/NaN
            if pd.isna(expected_val) and pd.isna(actual_val):
                match_count += 1
                continue

            if pd.isna(expected_val) or pd.isna(actual_val):
                issues.append(
                    f"Null mismatch: {row['usage_start']}, {row['namespace']}, {row['node']}, "
                    f"{metric}: expected={expected_val}, actual={actual_val}"
                )
                continue

            # Calculate relative difference
            if expected_val != 0:
                rel_diff = abs(actual_val - expected_val) / abs(expected_val)
            else:
                rel_diff = abs(actual_val - expected_val)

            if rel_diff <= tolerance:
                match_count += 1
            else:
                issues.append(
                    f"Value mismatch: {row['usage_start']}, {row['namespace']}, {row['node']}, "
                    f"{metric}: expected={expected_val:.6f}, actual={actual_val:.6f}, "
                    f"diff={rel_diff:.2%}"
                )

    result = {
        'all_match': len(issues) == 0,
        'match_count': match_count,
        'total_comparisons': total_comparisons,
        'match_percentage': (match_count / total_comparisons * 100) if total_comparisons > 0 else 0,
        'issues': issues,
        'missing_in_actual_count': len(missing_in_actual),
        'extra_in_actual_count': len(missing_in_expected),
    }

    # Log summary
    if result['all_match']:
        logger.info("✅ ALL RESULTS MATCH EXPECTED VALUES!")
        logger.info(f"   {match_count}/{total_comparisons} comparisons passed")
    else:
        logger.error(f"❌ FOUND {len(issues)} DISCREPANCIES")
        logger.error(f"   {match_count}/{total_comparisons} comparisons passed ({result['match_percentage']:.1f}%)")
        for issue in issues[:10]:  # Show first 10
            logger.error(f"   {issue}")
        if len(issues) > 10:
            logger.error(f"   ... and {len(issues) - 10} more issues")

    return result


if __name__ == '__main__':
    """Run as standalone script to generate expected results."""
    import argparse

    parser = argparse.ArgumentParser(description="Calculate expected results from nise YAML")
    parser.add_argument('yaml_file', help='Path to nise static YAML file')
    parser.add_argument('--output', '-o', help='Output CSV file path')
    parser.add_argument('--print', '-p', action='store_true', help='Print summary to console')

    args = parser.parse_args()

    calculator = ExpectedResultsCalculator(args.yaml_file)
    df = calculator.calculate_expected_aggregations()

    if args.print:
        calculator.print_summary(df)

    if args.output:
        calculator.save_to_csv(df, args.output)
    else:
        # Default output
        output_path = Path(args.yaml_file).parent / 'expected_results.csv'
        calculator.save_to_csv(df, str(output_path))
