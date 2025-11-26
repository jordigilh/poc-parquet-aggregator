#!/usr/bin/env python3
"""
Fix all AWS test manifests to use Core's proven format.
"""

import yaml
from pathlib import Path

# Core's proven instance_type format
Core_INSTANCE_TYPE = {
    'inst_type': 'm5.large',
    'physical_cores': 0.5,      # Float, not string!
    'vcpu': '2',
    'memory': '8 GiB',
    'storage': 'EBS Only',
    'family': 'General Purpose',
    'cost': 0.67,               # Per-hour cost (will adjust per scenario)
    'rate': 0.67,               # Must match cost
    'saving': 0.2               # Numeric value (not null)
}

def fix_manifest(manifest_path):
    """Fix a single manifest to use Core format."""
    print(f"\n📝 Processing {manifest_path.name}...")

    # Read the file as text (to preserve Jinja2 templates)
    with open(manifest_path, 'r') as f:
        lines = f.readlines()

    # Find and replace the AWS EC2Generator section
    in_ec2_gen = False
    in_instance_type = False
    indent_level = 0
    fixed_lines = []
    skip_until_next_key = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect EC2Generator
        if 'EC2Generator:' in line:
            in_ec2_gen = True
            indent_level = len(line) - len(line.lstrip())
            fixed_lines.append(line)
            i += 1
            continue

        # Detect instance_type within EC2Generator
        if in_ec2_gen and 'instance_type:' in line:
            in_instance_type = True
            inst_indent = len(line) - len(line.lstrip())

            # Add the fixed instance_type block
            fixed_lines.append(line)
            fixed_lines.append(' ' * (inst_indent + 2) + f"inst_type: m5.large\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"physical_cores: 0.5\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"vcpu: '2'\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"memory: '8 GiB'\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"storage: 'EBS Only'\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"family: 'General Purpose'\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"cost: 0.67\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"rate: 0.67\n")
            fixed_lines.append(' ' * (inst_indent + 2) + f"saving: 0.2\n")

            # Skip existing instance_type content
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_indent = len(next_line) - len(next_line.lstrip())
                # Stop when we hit a key at same or lower indent level
                if next_line.strip() and next_indent <= inst_indent:
                    break
                i += 1
            in_instance_type = False
            continue

        # Fix resource_id format (remove i- prefix if present)
        if in_ec2_gen and 'resource_id:' in line and 'i-{{' in line:
            # Remove i- prefix
            fixed_line = line.replace('i-{{', '{{')
            fixed_lines.append(fixed_line)
            i += 1
            continue

        # End of EC2Generator section
        if in_ec2_gen and line.strip() and not line.startswith(' ' * (indent_level + 2)):
            in_ec2_gen = False

        fixed_lines.append(line)
        i += 1

    # Write back
    with open(manifest_path, 'w') as f:
        f.writelines(fixed_lines)

    print(f"  ✓ Fixed {manifest_path.name}")

def main():
    manifest_dir = Path('test-manifests')
    manifests = sorted(manifest_dir.glob('ocp_aws_scenario_*.yml'))

    # Skip the _iqe variant
    manifests = [m for m in manifests if '_iqe' not in m.name]

    print(f"Found {len(manifests)} manifests to fix")

    fixed_count = 0
    for manifest_path in manifests:
        try:
            fix_manifest(manifest_path)
            fixed_count += 1
        except Exception as e:
            print(f"  ❌ Error fixing {manifest_path.name}: {e}")

    print(f"\n✅ Fixed {fixed_count}/{len(manifests)} manifests")
    print("\nNext: Run E2E tests with:")
    print("  bash scripts/run_ocp_aws_scenario_tests.sh")

if __name__ == '__main__':
    main()

