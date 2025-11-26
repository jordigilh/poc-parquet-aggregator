#!/usr/bin/env python3
"""
Fix resource_id prefixes in OCP-AWS manifests to match Core pattern.

OCP sections: resource_id without i- prefix
AWS sections: resource_id with i- prefix
"""

import yaml
import sys
from pathlib import Path


def fix_manifest(manifest_path):
    """Fix resource_id format in a manifest file."""

    with open(manifest_path, 'r') as f:
        data = yaml.safe_load(f)

    changes = []

    # Fix OCP section - remove i- prefix
    if 'ocp' in data and 'generators' in data['ocp']:
        for gen in data['ocp']['generators']:
            if 'OCPGenerator' in gen:
                nodes = gen['OCPGenerator'].get('nodes', [])
                for node_wrapper in nodes:
                    if 'node' in node_wrapper:
                        node = node_wrapper['node']
                        if 'resource_id' in node:
                            old_val = node['resource_id']
                            if old_val.startswith('i-{{'):
                                # Change i-{{ resource_id_1 }} to {{ resource_id_1 }}
                                node['resource_id'] = old_val.replace('i-{{', '{{')
                                changes.append(f"OCP: {old_val} → {node['resource_id']}")

    # AWS section - keep i- prefix (already correct)
    if 'aws' in data and 'generators' in data['aws']:
        for gen in data['aws']['generators']:
            for gen_type in ['EC2Generator', 'EBSGenerator', 'DataTransferGenerator']:
                if gen_type in gen and 'resource_id' in gen[gen_type]:
                    old_val = gen[gen_type]['resource_id']
                    # Should have i- prefix - this is correct
                    if not old_val.startswith('i-'):
                        gen[gen_type]['resource_id'] = f"i-{old_val}"
                        changes.append(f"AWS: {old_val} → {gen[gen_type]['resource_id']}")

    if changes:
        # Write back
        with open(manifest_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        print(f"✓ Fixed {manifest_path}")
        for change in changes:
            print(f"  {change}")
        return True
    else:
        print(f"  No changes needed for {manifest_path}")
        return False


def main():
    manifest_dir = Path('test-manifests')
    manifests = list(manifest_dir.glob('ocp_aws_scenario_*.yml'))

    fixed_count = 0
    for manifest in sorted(manifests):
        if fix_manifest(manifest):
            fixed_count += 1

    print(f"\n✓ Fixed {fixed_count}/{len(manifests)} manifests")


if __name__ == '__main__':
    main()

