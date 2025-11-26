#!/usr/bin/env python3
"""
Compare POC vs Trino results.

Usage:
    python scripts/compare_poc_vs_trino.py \
        --trino baselines/trino_baseline_2025-10-15.json \
        --poc results/poc_results_2025-10-15.json \
        --output reports/comparison_report_2025-10-15.md
"""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal


def load_json(file_path):
    """Load JSON file."""
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {file_path}: {e}")
        sys.exit(1)


def calculate_diff(trino_value, poc_value):
    """Calculate absolute and percentage difference."""
    diff = abs(poc_value - trino_value)
    diff_pct = (diff / trino_value * 100) if trino_value > 0 else 0
    return diff, diff_pct


def compare(trino, poc, output_file=None, tolerance_pct=1.0):
    """Compare Trino and POC results."""
    
    print(f"\n{'=' * 80}")
    print(f"POC vs Trino Comparison")
    print(f"{'=' * 80}\n")
    
    # Extract totals
    trino_totals = trino['totals']
    poc_totals = poc['totals']
    
    # Compare totals
    cost_diff, cost_diff_pct = calculate_diff(
        trino_totals['total_cost'],
        poc_totals['total_cost']
    )
    
    row_diff, row_diff_pct = calculate_diff(
        trino_totals['row_count'],
        poc_totals['row_count']
    )
    
    ns_diff = abs(poc_totals['namespaces'] - trino_totals['namespaces'])
    cluster_diff = abs(poc_totals['clusters'] - trino_totals['clusters'])
    
    # Determine pass/fail
    passed = cost_diff_pct < tolerance_pct
    status_emoji = "✅" if passed else "❌"
    status_text = "PASS" if passed else "FAIL"
    
    # Build report
    report_lines = []
    report_lines.append(f"# POC vs Trino Comparison Report")
    report_lines.append(f"")
    report_lines.append(f"## Summary")
    report_lines.append(f"")
    report_lines.append(f"**Date:** {trino['date']}  ")
    report_lines.append(f"**Compared At:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    report_lines.append(f"**Status:** {status_emoji} **{status_text}** (Tolerance: {tolerance_pct}%)  ")
    report_lines.append(f"**Cost Difference:** {cost_diff_pct:.2f}%  ")
    report_lines.append(f"")
    report_lines.append(f"## Total Cost Comparison")
    report_lines.append(f"")
    report_lines.append(f"| Metric | Trino | POC | Difference | % Diff | Status |")
    report_lines.append(f"|--------|-------|-----|------------|--------|--------|")
    report_lines.append(
        f"| Total Cost | ${trino_totals['total_cost']:.2f} | "
        f"${poc_totals['total_cost']:.2f} | ${cost_diff:.2f} | "
        f"{cost_diff_pct:.2f}% | {'✅' if cost_diff_pct < tolerance_pct else '❌'} |"
    )
    report_lines.append(
        f"| Blended Cost | ${trino_totals['total_blended_cost']:.2f} | "
        f"${poc_totals['total_blended_cost']:.2f} | - | - | - |"
    )
    report_lines.append(
        f"| Row Count | {trino_totals['row_count']:,} | {poc_totals['row_count']:,} | "
        f"{row_diff:,} | {row_diff_pct:.2f}% | {'✅' if row_diff_pct < 10 else '⚠️'} |"
    )
    report_lines.append(
        f"| Namespaces | {trino_totals['namespaces']} | {poc_totals['namespaces']} | "
        f"{ns_diff} | - | {'✅' if ns_diff == 0 else '⚠️'} |"
    )
    report_lines.append(
        f"| Clusters | {trino_totals['clusters']} | {poc_totals['clusters']} | "
        f"{cluster_diff} | - | {'✅' if cluster_diff == 0 else '⚠️'} |"
    )
    report_lines.append(f"")
    
    # Per-Namespace Comparison
    report_lines.append(f"## Per-Namespace Comparison")
    report_lines.append(f"")
    report_lines.append(f"| Namespace | Trino Cost | POC Cost | Difference | % Diff | Status |")
    report_lines.append(f"|-----------|------------|----------|------------|--------|--------|")
    
    # Build namespace dictionaries
    trino_ns = {ns['namespace']: ns['cost'] for ns in trino['namespace_breakdown']}
    poc_ns = {ns['namespace']: ns['cost'] for ns in poc['namespace_breakdown']}
    
    all_namespaces = sorted(set(trino_ns.keys()) | set(poc_ns.keys()))
    
    ns_mismatches = 0
    for ns in all_namespaces:
        trino_cost = trino_ns.get(ns, 0)
        poc_cost = poc_ns.get(ns, 0)
        
        if trino_cost == 0 and poc_cost == 0:
            continue  # Skip empty namespaces
        
        diff, diff_pct = calculate_diff(trino_cost, poc_cost)
        
        # Per-namespace tolerance is higher (5%)
        ns_passed = diff_pct < 5.0
        if not ns_passed:
            ns_mismatches += 1
        
        status = "✅" if ns_passed else "⚠️"
        
        report_lines.append(
            f"| {ns[:40]} | ${trino_cost:.2f} | ${poc_cost:.2f} | "
            f"${diff:.2f} | {diff_pct:.2f}% | {status} |"
        )
    
    report_lines.append(f"")
    
    # Validation Status
    report_lines.append(f"## Validation Status")
    report_lines.append(f"")
    
    if passed:
        report_lines.append(f"{status_emoji} **PASS**: POC results match Trino within {tolerance_pct}% tolerance")
        report_lines.append(f"")
        report_lines.append(f"### Key Metrics")
        report_lines.append(f"- ✅ Total cost difference: {cost_diff_pct:.2f}% (< {tolerance_pct}%)")
        report_lines.append(f"- {'✅' if row_diff_pct < 10 else '⚠️'} Row count difference: {row_diff_pct:.2f}%")
        report_lines.append(f"- {'✅' if ns_diff == 0 else '⚠️'} Namespace count: {poc_totals['namespaces']} vs {trino_totals['namespaces']}")
        report_lines.append(f"- {'✅' if ns_mismatches == 0 else '⚠️'} Namespace cost mismatches: {ns_mismatches}")
    else:
        report_lines.append(f"{status_emoji} **FAIL**: POC results differ by {cost_diff_pct:.2f}% (> {tolerance_pct}%)")
        report_lines.append(f"")
        report_lines.append(f"### Issues Detected")
        report_lines.append(f"- ❌ Total cost difference: ${cost_diff:.2f} ({cost_diff_pct:.2f}%)")
        if row_diff_pct > 10:
            report_lines.append(f"- ⚠️  Row count difference: {row_diff:,} ({row_diff_pct:.2f}%)")
        if ns_diff > 0:
            report_lines.append(f"- ⚠️  Namespace count mismatch: {ns_diff}")
        if ns_mismatches > 0:
            report_lines.append(f"- ⚠️  {ns_mismatches} namespace(s) with >5% cost difference")
    
    report_lines.append(f"")
    
    # Next Steps
    report_lines.append(f"## Next Steps")
    report_lines.append(f"")
    
    if passed:
        report_lines.append(f"1. ✅ Document this validation success")
        report_lines.append(f"2. ✅ Run scale testing (larger date ranges)")
        report_lines.append(f"3. ✅ Test performance benchmarks")
        report_lines.append(f"4. ✅ Plan production rollout")
        report_lines.append(f"5. ✅ Present results to team")
    else:
        report_lines.append(f"1. ❌ Investigate cost discrepancies")
        report_lines.append(f"2. ❌ Check matching logic (resource_id, tags)")
        report_lines.append(f"3. ❌ Verify cost attribution formulas")
        report_lines.append(f"4. ❌ Compare intermediate steps (matching, attribution)")
        report_lines.append(f"5. ❌ Re-run comparison after fixes")
    
    report_lines.append(f"")
    
    # Detailed Diagnostics
    report_lines.append(f"## Detailed Diagnostics")
    report_lines.append(f"")
    report_lines.append(f"### Data Sources")
    report_lines.append(f"")
    report_lines.append(f"**Trino:**")
    report_lines.append(f"- Source: {trino.get('source', 'N/A')}")
    report_lines.append(f"- Exported: {trino.get('exported_at', 'N/A')}")
    if 'provider_uuids' in trino and trino['provider_uuids']:
        report_lines.append(f"- Provider UUIDs: {', '.join(trino['provider_uuids'][:2])}")
    report_lines.append(f"")
    report_lines.append(f"**POC:**")
    report_lines.append(f"- Source: {poc.get('source', 'N/A')}")
    report_lines.append(f"- Collected: {poc.get('collected_at', 'N/A')}")
    report_lines.append(f"- Schema: {poc.get('schema', 'N/A')}")
    report_lines.append(f"")
    
    # Top Cost Namespaces
    report_lines.append(f"### Top 10 Cost Namespaces")
    report_lines.append(f"")
    report_lines.append(f"**Trino:**")
    for ns in trino['namespace_breakdown'][:10]:
        report_lines.append(f"- {ns['namespace']}: ${ns['cost']:.2f}")
    report_lines.append(f"")
    report_lines.append(f"**POC:**")
    for ns in poc['namespace_breakdown'][:10]:
        report_lines.append(f"- {ns['namespace']}: ${ns['cost']:.2f}")
    report_lines.append(f"")
    
    report = "\n".join(report_lines)
    
    # Print to console
    print(report)
    
    # Save to file
    if output_file:
        try:
            with open(output_file, 'w') as f:
                f.write(report)
            print(f"\n{'=' * 80}")
            print(f"✓ Comparison report saved to: {output_file}")
            print(f"{'=' * 80}\n")
        except Exception as e:
            print(f"❌ Failed to save report: {e}")
    
    return passed


def main():
    parser = argparse.ArgumentParser(description='Compare POC vs Trino results')
    parser.add_argument('--trino', type=str, required=True, help='Trino baseline JSON file')
    parser.add_argument('--poc', type=str, required=True, help='POC results JSON file')
    parser.add_argument('--output', type=str, help='Output report file (markdown)')
    parser.add_argument('--tolerance', type=float, default=1.0, help='Tolerance percentage for pass/fail (default: 1.0)')
    
    args = parser.parse_args()
    
    # Load data
    trino = load_json(args.trino)
    poc = load_json(args.poc)
    
    # Compare
    passed = compare(trino, poc, args.output, args.tolerance)
    
    # Exit code
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()

