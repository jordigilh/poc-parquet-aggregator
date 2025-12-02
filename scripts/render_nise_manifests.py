#!/usr/bin/env python3
"""
Render Jinja2 templates in nise manifests with correlated resource IDs.

This solves the "nise random ID" problem by:
1. Generating a random resource ID once
2. Rendering all Jinja2 variables in manifests
3. Passing rendered (static) manifests to nise

Usage:
    python scripts/render_nise_manifests.py \
        --template test-manifests/ocp-on-aws/01-resource-matching/manifest.yml \
        --output test-data/rendered/scenario_01.yml
"""

import argparse
import random
import yaml
import sys
from pathlib import Path
from jinja2 import Template, StrictUndefined


def generate_correlated_ids(max_numeric=50):
    """
    Generate correlated resource IDs (like Core does).

    Auto-generates resource_id_1 through resource_id_N to prevent
    silent failures when new test scenarios are added.

    Args:
        max_numeric: Maximum numeric ID to generate (default: 50)

    Returns:
        Dict of IDs to use in templates, including:
        - resource_id_1 through resource_id_N (generic numeric IDs)
        - resource_id_6a, resource_id_6b (semantic multi-cluster IDs)
        - resource_id_alpha, resource_id_bravo (semantic cluster names)
    """
    # Generate random 10-digit number (like Core)
    base_id = random.randint(10**9, 10**10 - 1)

    # Auto-generate numeric IDs (resource_id_1 through resource_id_N)
    # This prevents silent failures when new scenarios use new IDs
    ids = {
        f'resource_id_{i}': str(base_id + i - 1)
        for i in range(1, max_numeric + 1)
    }

    # Add semantic multi-cluster IDs for better readability in manifests
    ids.update({
        'resource_id_6a': f'i-prod{str(base_id)[-4:]}',      # Scenario 06: prod cluster
        'resource_id_6b': f'i-staging{str(base_id)[-4:]}',   # Scenario 06: staging cluster
        'resource_id_alpha': f'i-alpha{str(base_id)[-4:]}',  # Multi-cluster: alpha
        'resource_id_bravo': f'i-bravo{str(base_id)[-4:]}',  # Multi-cluster: bravo
    })

    return ids


def render_manifest(template_path, output_path, context=None):
    """
    Render a Jinja2 template manifest.

    Args:
        template_path: Path to template YAML file
        output_path: Path to write rendered YAML
        context: Dict of variables to render (default: generated IDs)

    Returns:
        Dict of rendered context (so caller knows what IDs were used)
    """
    # Generate context if not provided
    if context is None:
        context = generate_correlated_ids()

    # Read template
    with open(template_path, 'r') as f:
        template_content = f.read()

    # Render with Jinja2 (StrictUndefined catches missing variables)
    template = Template(template_content, undefined=StrictUndefined)
    try:
        rendered = template.render(**context)
    except Exception as e:
        print(f"❌ Template rendering FAILED: {e}")
        print(f"   Template: {template_path}")
        print(f"   This usually means the template uses a variable that's not defined.")
        print(f"   Available variables: {sorted(context.keys())[:10]}... (showing first 10)")
        sys.exit(1)

    # Parse to ensure valid YAML (validation only)
    try:
        parsed = yaml.safe_load(rendered)
    except yaml.YAMLError as e:
        print(f"❌ Rendered YAML is invalid: {e}")
        sys.exit(1)

    # Write rendered YAML directly (DO NOT use yaml.dump - it restructures!)
    # We want to preserve the exact YAML structure from the template
    with open(output_path, 'w') as f:
        f.write(rendered)

    print(f"✓ Rendered {template_path} → {output_path}")
    print(f"  Context: {context}")

    return context


def update_manifest_with_templates(manifest_path):
    """
    Update existing manifest to use Jinja2 template variables.

    Converts hardcoded IDs like 'i-test0001' to '{{ resource_id_1 }}'
    """
    with open(manifest_path, 'r') as f:
        content = f.read()

    # Replace hardcoded resource IDs with template variables
    # For OCP: no i- prefix (just the number)
    # For AWS: with i- prefix
    # This matches Core's pattern and allows Trino suffix matching to work
    replacements = {
        'i-test0001': '{{ resource_id_1 }}',  # OCP format (will be replaced again for AWS)
        'i-test0002': '{{ resource_id_2 }}',
        'i-test0003': '{{ resource_id_3 }}',
        'i-test0004': '{{ resource_id_4 }}',
        'i-test0005': '{{ resource_id_5 }}',
    }

    updated = content
    for old, new in replacements.items():
        if old in updated:
            updated = updated.replace(old, new)
            print(f"  Replaced: {old} → {new}")

    # Write back
    with open(manifest_path, 'w') as f:
        f.write(updated)

    print(f"✓ Updated {manifest_path} with template variables")


def batch_render_manifests(manifest_dir, output_dir):
    """
    Render all manifests in a directory.

    Uses the same correlated IDs for all manifests in the batch.
    """
    manifest_dir = Path(manifest_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate IDs once for entire batch
    context = generate_correlated_ids()
    print(f"\n📝 Generated correlated IDs for batch:")
    print(f"   {context}\n")

    # Find all YAML manifests
    manifests = list(manifest_dir.glob('*/manifest.yml'))

    if not manifests:
        print(f"❌ No manifests found in {manifest_dir}")
        sys.exit(1)

    print(f"Found {len(manifests)} manifests to render:\n")

    # Render each
    for manifest in sorted(manifests):
        output_path = output_dir / manifest.name
        render_manifest(manifest, output_path, context)

    # Save context for reference
    context_file = output_dir / 'context.json'
    import json
    with open(context_file, 'w') as f:
        json.dump(context, f, indent=2)

    print(f"\n✓ Rendered {len(manifests)} manifests")
    print(f"✓ Saved context to {context_file}")

    return context


def main():
    parser = argparse.ArgumentParser(description='Render Jinja2 templates in nise manifests')
    parser.add_argument('--template', type=str, help='Single template file to render')
    parser.add_argument('--output', type=str, help='Output file for single template')
    parser.add_argument('--batch', type=str, help='Directory of templates to render')
    parser.add_argument('--batch-output', type=str, help='Output directory for batch render')
    parser.add_argument('--update', type=str, help='Update manifest to use template variables')

    args = parser.parse_args()

    if args.update:
        update_manifest_with_templates(args.update)

    elif args.template and args.output:
        render_manifest(args.template, args.output)

    elif args.batch and args.batch_output:
        batch_render_manifests(args.batch, args.batch_output)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()

