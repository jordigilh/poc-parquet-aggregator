#!/usr/bin/env python3
"""
Align nise-generated test data with manifest expectations.

PROBLEM: Nise generates random resource_ids even with --static-report-file
SOLUTION: Post-process CSVs to replace random IDs with manifest-specified IDs

Usage:
    python3 align_test_data.py \
        --manifest test-manifests/ocp_aws_scenario_01.yml \
        --ocp-dir /tmp/scenario/ocp \
        --aws-file /tmp/scenario/aws.csv
"""

import argparse
import csv
import yaml
from pathlib import Path
import re


def load_manifest(manifest_path):
    """Load test manifest and extract expected resource IDs, tags, and cluster info."""
    with open(manifest_path, 'r') as f:
        data = yaml.safe_load(f)

    expected = {
        'ocp_nodes': {},      # node_name -> resource_id
        'aws_resources': set(), #  resource_ids
        'aws_tags': {},       # Expected AWS tags (openshift_cluster, openshift_node)
        'cluster_id': None    # Expected cluster ID
    }

    # Extract OCP node resource IDs
    if 'ocp' in data and 'generators' in data['ocp']:
        for gen in data['ocp']['generators']:
            if 'OCPGenerator' in gen:
                nodes = gen['OCPGenerator'].get('nodes', [])
                for node_spec in nodes:
                    node_data = node_spec.get('node', {})
                    node_name = node_data.get('node_name', '')
                    resource_id = node_data.get('resource_id', '')
                    if node_name and resource_id:
                        expected['ocp_nodes'][node_name] = resource_id

    # Extract AWS resource IDs and tags
    if 'aws' in data and 'generators' in data['aws']:
        for gen in data['aws']['generators']:
            for gen_type, attrs in gen.items():
                resource_id = attrs.get('resource_id', '')
                if resource_id:
                    expected['aws_resources'].add(resource_id)

                # Extract AWS tags (for tag matching scenarios)
                if 'tags' in attrs:
                    tags = attrs['tags']
                    if 'openshift_cluster' in tags:
                        expected['aws_tags']['openshift_cluster'] = tags['openshift_cluster']
                    if 'openshift_node' in tags:
                        expected['aws_tags']['openshift_node'] = tags['openshift_node']

    return expected


def align_ocp_pod_usage(csv_path, expected_nodes):
    """Align OCP pod usage CSV with expected node resource IDs."""
    if not expected_nodes:
        return

    # Get the first (usually only) expected resource_id
    # Nise generates random node_names too, so we can't match by name
    # Instead, replace ALL resource_ids with the expected one
    expected_ids = list(expected_nodes.values())
    if not expected_ids:
        return

    expected_id = expected_ids[0]

    temp_path = csv_path.with_suffix('.tmp')
    updated = 0

    with open(csv_path, 'r') as infile, open(temp_path, 'w') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            # Replace ALL resource_ids (nise generates random node names too)
            if row.get('resource_id'):
                row['resource_id'] = expected_id
                updated += 1

            writer.writerow(row)

    temp_path.replace(csv_path)
    print(f"  ✓ Aligned {updated} rows in {csv_path.name} (resource_id -> {expected_id})")


def align_aws_cur(csv_path, expected_resources, expected_tags=None):
    """Align AWS CUR CSV with expected resource IDs and tags."""
    if not expected_resources:
        return

    # For AWS, we typically have one resource ID per scenario
    # Replace all resource IDs with the first expected one
    if len(expected_resources) != 1:
        print(f"  ⚠️  Expected 1 AWS resource, found {len(expected_resources)}")
        return

    expected_id = list(expected_resources)[0]
    if expected_tags is None:
        expected_tags = {}
    temp_path = csv_path.with_suffix('.tmp')
    updated = 0

    with open(csv_path, 'r') as infile, open(temp_path, 'w') as outfile:
        reader = csv.DictReader(infile)

        # Find resource_id column (might be lineItem/ResourceId or lineitem_resourceid)
        resource_col = None
        for col in reader.fieldnames:
            if 'resource' in col.lower() and 'id' in col.lower():
                resource_col = col
                break

        if not resource_col:
            print(f"  ⚠️  No resource_id column found in AWS CSV")
            return

        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()

        for row in reader:
            # Fix resource ID
            if row.get(resource_col):
                row[resource_col] = expected_id
                updated += 1

            # Fix OpenShift tags (for tag matching scenarios)
            if expected_tags:
                if 'openshift_cluster' in expected_tags:
                    # Direct column
                    if 'openshift_cluster' in row:
                        row['openshift_cluster'] = expected_tags['openshift_cluster']
                    # ResourceTag column
                    if 'resourceTags/user:openshift_cluster' in row:
                        row['resourceTags/user:openshift_cluster'] = expected_tags['openshift_cluster']

                if 'openshift_node' in expected_tags:
                    # Direct column
                    if 'openshift_node' in row:
                        row['openshift_node'] = expected_tags['openshift_node']
                    # ResourceTag column
                    if 'resourceTags/user:openshift_node' in row:
                        row['resourceTags/user:openshift_node'] = expected_tags['openshift_node']

            writer.writerow(row)

    temp_path.replace(csv_path)
    tag_info = f", tags={list(expected_tags.keys())}" if expected_tags else ""
    print(f"  ✓ Aligned {updated} rows in {csv_path.name} ({resource_col} -> {expected_id}{tag_info})")


def main():
    parser = argparse.ArgumentParser(description='Align test data with manifest')
    parser.add_argument('--manifest', required=True, help='Test manifest file')
    parser.add_argument('--ocp-dir', help='OCP CSV directory')
    parser.add_argument('--aws-file', help='AWS CSV file')
    args = parser.parse_args()

    print(f"Loading manifest: {args.manifest}")
    expected = load_manifest(args.manifest)

    print(f"Expected OCP nodes: {list(expected['ocp_nodes'].keys())}")
    print(f"Expected AWS resources: {expected['aws_resources']}")
    if expected['aws_tags']:
        print(f"Expected AWS tags: {expected['aws_tags']}")

    # Align OCP files
    if args.ocp_dir and expected['ocp_nodes']:
        ocp_path = Path(args.ocp_dir)
        print(f"\nAligning OCP data in {ocp_path}...")

        # Find all pod usage CSVs recursively
        for csv_file in ocp_path.rglob('*openshift_report*.csv'):
            # Check if it's pod usage (has resource_id column)
            with open(csv_file, 'r') as f:
                first_line = f.readline()
                if 'resource_id' in first_line and 'persistentvolume' not in first_line:
                    align_ocp_pod_usage(csv_file, expected['ocp_nodes'])

    # Align AWS file
    if args.aws_file and expected['aws_resources']:
        aws_path = Path(args.aws_file)
        if aws_path.exists():
            print(f"\nAligning AWS data in {aws_path}...")
            align_aws_cur(aws_path, expected['aws_resources'], expected['aws_tags'])

    print("\n✅ Data alignment complete")


if __name__ == '__main__':
    main()

