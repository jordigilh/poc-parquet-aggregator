#!/usr/bin/env python3
"""
Cost Distribution Comparison Tool

Compares cost allocation between different distribution methods (cpu, memory, weighted).
Helps estimate the impact of switching from one method to another.

Usage:
    python scripts/cost_distribution_comparison.py --input data.parquet
    python scripts/cost_distribution_comparison.py --sample  # Use sample data
"""

import argparse
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List


def calculate_attribution_ratios(
    cpu_usage: float,
    cpu_capacity: float,
    memory_usage: float,
    memory_capacity: float,
    cpu_weight: float = 0.73,
    memory_weight: float = 0.27
) -> Dict[str, float]:
    """
    Calculate attribution ratios for all distribution methods.

    Args:
        cpu_usage: Pod CPU usage
        cpu_capacity: Node CPU capacity
        memory_usage: Pod memory usage
        memory_capacity: Node memory capacity
        cpu_weight: Weight for CPU in weighted method (default: AWS M5 = 0.73)
        memory_weight: Weight for memory in weighted method (default: AWS M5 = 0.27)

    Returns:
        Dictionary with ratios for each method
    """
    cpu_ratio = min(cpu_usage / cpu_capacity, 1.0) if cpu_capacity > 0 else 0
    memory_ratio = min(memory_usage / memory_capacity, 1.0) if memory_capacity > 0 else 0

    return {
        'cpu': cpu_ratio,
        'memory': memory_ratio,
        'weighted': cpu_ratio * cpu_weight + memory_ratio * memory_weight,
        'max': max(cpu_ratio, memory_ratio),  # Legacy POC method
    }


def calculate_cost_impact(
    aws_cost: float,
    ratios: Dict[str, float],
    from_method: str,
    to_method: str
) -> Tuple[float, float, float]:
    """
    Calculate the cost impact of switching methods.

    Returns:
        Tuple of (from_cost, to_cost, percent_change)
    """
    from_cost = aws_cost * ratios[from_method]
    to_cost = aws_cost * ratios[to_method]

    if from_cost > 0:
        percent_change = ((to_cost - from_cost) / from_cost) * 100
    else:
        percent_change = 0 if to_cost == 0 else float('inf')

    return from_cost, to_cost, percent_change


def analyze_workload(
    name: str,
    cpu_pct: float,
    memory_pct: float,
    aws_cost: float = 100.0,
    cpu_weight: float = 0.73,
    memory_weight: float = 0.27
) -> Dict:
    """
    Analyze cost distribution for a workload.

    Args:
        name: Workload name
        cpu_pct: CPU usage as percentage of capacity (0-1)
        memory_pct: Memory usage as percentage of capacity (0-1)
        aws_cost: AWS cost to distribute (default: $100 for easy %)
        cpu_weight: CPU weight for weighted method
        memory_weight: Memory weight for weighted method

    Returns:
        Analysis dictionary
    """
    ratios = calculate_attribution_ratios(
        cpu_pct, 1.0, memory_pct, 1.0, cpu_weight, memory_weight
    )

    costs = {method: aws_cost * ratio for method, ratio in ratios.items()}

    # Calculate changes from CPU-only (Trino default)
    changes = {}
    for method in ['memory', 'weighted', 'max']:
        _, _, pct_change = calculate_cost_impact(aws_cost, ratios, 'cpu', method)
        changes[f'cpu_to_{method}'] = pct_change

    return {
        'name': name,
        'cpu_pct': cpu_pct,
        'memory_pct': memory_pct,
        'ratios': ratios,
        'costs': costs,
        'changes': changes
    }


def simple_table(headers: List[str], rows: List[List[str]]) -> str:
    """Simple table formatter without external dependencies."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    # Build table
    lines = []

    # Header
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines.append(header_line)
    lines.append("-" * len(header_line))

    # Rows
    for row in rows:
        row_line = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(row_line)

    return "\n".join(lines)


def print_comparison_table(analyses: list, aws_cost: float = 100.0):
    """Print a formatted comparison table."""

    print("\n" + "=" * 80)
    print("COST DISTRIBUTION COMPARISON")
    print("=" * 80)
    print(f"\nBase AWS Cost: ${aws_cost:.2f}")
    print(f"Weights: CPU={0.73*100:.0f}%, Memory={0.27*100:.0f}% (AWS M5 family)")

    # Table 1: Cost by Method
    print("\n" + "-" * 80)
    print("COST BY DISTRIBUTION METHOD")
    print("-" * 80)

    headers = ['Workload', 'CPU %', 'Mem %', 'CPU-only', 'Memory-only', 'Weighted', 'Max (POC)']
    rows = []
    for a in analyses:
        rows.append([
            a['name'],
            f"{a['cpu_pct']*100:.0f}%",
            f"{a['memory_pct']*100:.0f}%",
            f"${a['costs']['cpu']:.2f}",
            f"${a['costs']['memory']:.2f}",
            f"${a['costs']['weighted']:.2f}",
            f"${a['costs']['max']:.2f}",
        ])

    print(simple_table(headers, rows))

    # Table 2: Impact of Switching from CPU-only
    print("\n" + "-" * 80)
    print("IMPACT OF SWITCHING FROM CPU-ONLY (Trino default)")
    print("-" * 80)

    headers = ['Workload', 'To Memory', 'To Weighted', 'To Max (POC)']
    rows = []
    for a in analyses:
        rows.append([
            a['name'],
            f"{a['changes']['cpu_to_memory']:+.1f}%",
            f"{a['changes']['cpu_to_weighted']:+.1f}%",
            f"{a['changes']['cpu_to_max']:+.1f}%",
        ])

    print(simple_table(headers, rows))

    # Summary
    print("\n" + "-" * 80)
    print("SUMMARY")
    print("-" * 80)

    print("""
Key Observations:
- CPU-heavy workloads: Cost DECREASES when switching to weighted/memory
- Memory-heavy workloads: Cost INCREASES when switching to weighted/memory
- Balanced workloads: Minimal change when switching to weighted

Recommendations:
- For Trino parity: Use 'cpu' method
- For economic accuracy: Use 'weighted' method (industry standard)
- Memory-only should rarely be used (undercharges CPU-heavy workloads)
""")


def main():
    parser = argparse.ArgumentParser(description='Compare cost distribution methods')
    parser.add_argument('--input', type=str, help='Input parquet file with usage data')
    parser.add_argument('--sample', action='store_true', help='Use sample workloads')
    parser.add_argument('--aws-cost', type=float, default=100.0, help='AWS cost to distribute')
    args = parser.parse_args()

    if args.sample or not args.input:
        # Sample workloads representing common patterns
        sample_workloads = [
            ('Web frontend', 0.25, 0.50),      # Memory-heavy
            ('API server', 0.50, 0.50),        # Balanced
            ('ML training', 0.90, 0.30),       # CPU-heavy
            ('Database cache', 0.20, 0.80),    # Memory-heavy
            ('Batch processor', 0.75, 0.25),   # CPU-heavy
            ('Message queue', 0.40, 0.60),     # Slightly memory-heavy
        ]

        analyses = [
            analyze_workload(name, cpu, mem, args.aws_cost)
            for name, cpu, mem in sample_workloads
        ]

        print_comparison_table(analyses, args.aws_cost)

    else:
        # Load from parquet file
        print(f"Loading data from {args.input}...")
        df = pd.read_parquet(args.input)

        # Aggregate by namespace
        if 'namespace' in df.columns:
            grouped = df.groupby('namespace').agg({
                'pod_usage_cpu_core_hours': 'sum',
                'node_capacity_cpu_core_hours': 'sum',
                'pod_usage_memory_gigabyte_hours': 'sum',
                'node_capacity_memory_gigabyte_hours': 'sum',
            }).reset_index()

            analyses = []
            for _, row in grouped.iterrows():
                cpu_pct = row['pod_usage_cpu_core_hours'] / row['node_capacity_cpu_core_hours'] if row['node_capacity_cpu_core_hours'] > 0 else 0
                mem_pct = row['pod_usage_memory_gigabyte_hours'] / row['node_capacity_memory_gigabyte_hours'] if row['node_capacity_memory_gigabyte_hours'] > 0 else 0

                analyses.append(analyze_workload(
                    row['namespace'],
                    min(cpu_pct, 1.0),
                    min(mem_pct, 1.0),
                    args.aws_cost
                ))

            print_comparison_table(analyses, args.aws_cost)
        else:
            print("Error: Input file must have 'namespace' column")


if __name__ == '__main__':
    main()

