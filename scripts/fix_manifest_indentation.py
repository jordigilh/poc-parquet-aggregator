#!/usr/bin/env python3
"""
Fix YAML manifest indentation to match Core/nise expectations.

Problem: Our manifests have:
  - node:
      node_name: ...  # ← Nested (wrong!)

Should be:
  - node:
    node_name: ...  # ← Same level (correct!)
"""

import sys
import re
from pathlib import Path

def fix_manifest(file_path):
    """Fix indentation in a single manifest file."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Pattern: After "- node:" or "- pod:" or "- volume:", reduce indentation by 2 spaces
    # This moves the properties to the same level as the key

    # Split into lines
    lines = content.split('\n')
    fixed_lines = []
    in_fix_zone = False
    base_indent = 0

    for i, line in enumerate(lines):
        # Check if this is a list item with a label (- node:, - pod:, - volume:, - volume_claim:)
        if re.match(r'^(\s*)-\s+(node|pod|volume|volume_claim):\s*$', line):
            fixed_lines.append(line)
            in_fix_zone = True
            # Calculate base indentation (indent of the '-')
            base_indent = len(line) - len(line.lstrip())
            continue

        # If we're in a fix zone and see a dedent or another list item, exit fix zone
        if in_fix_zone:
            current_indent = len(line) - len(line.lstrip()) if line.strip() else 0
            # Exit if we hit another list item at same or lower indent
            if line.strip() and (line.lstrip().startswith('-') or current_indent <= base_indent):
                in_fix_zone = False
            # Fix indentation: reduce by 2 spaces (but stay at least at base_indent + 2)
            elif line.strip():
                target_indent = base_indent + 2
                if current_indent > target_indent:
                    # Reduce indentation
                    fixed_line = ' ' * target_indent + line.lstrip()
                    fixed_lines.append(fixed_line)
                    continue

        fixed_lines.append(line)

    # Write back
    fixed_content = '\n'.join(fixed_lines)
    with open(file_path, 'w') as f:
        f.write(fixed_content)

    print(f"✓ Fixed {file_path}")

def main():
    # Fix all scenario manifests
    manifest_dir = Path('test-manifests')
    manifests = sorted(manifest_dir.glob('ocp_aws_scenario_*.yml'))

    if not manifests:
        print("❌ No manifests found!")
        sys.exit(1)

    print(f"Fixing {len(manifests)} manifests...\n")

    for manifest in manifests:
        fix_manifest(manifest)

    print(f"\n✓ Fixed {len(manifests)} manifests!")
    print("\nVerify with:")
    print("  python3 scripts/render_nise_manifests.py \\")
    print("    --template test-manifests/ocp_aws_scenario_01_resource_matching.yml \\")
    print("    --output /tmp/verify.yml")
    print("  python3 -c 'import yaml; d=yaml.safe_load(open(\"/tmp/verify.yml\")); print(\"resource_id\" in d[\"ocp\"][\"generators\"][0][\"OCPGenerator\"][\"nodes\"][0])'")

if __name__ == '__main__':
    main()

