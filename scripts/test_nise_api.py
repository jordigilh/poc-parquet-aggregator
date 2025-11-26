#!/usr/bin/env python3
"""
Test if we can control resource IDs using nise's Python API directly.
"""

import os
import tempfile
from datetime import datetime, timedelta
from nise.generators.ocp import OCPGenerator
from nise.generators.aws import EC2Generator

# Test: Can we control resource IDs?
print("=" * 60)
print("Testing nise API with controlled resource IDs")
print("=" * 60)

# Create temp output directory
output_dir = tempfile.mkdtemp(prefix="nise-api-test-")
print(f"\n📁 Output directory: {output_dir}\n")

# Test 1: OCP Generator with controlled resource_id
print("1️⃣  Testing OCP Generator...")
ocp_config = {
    "start_date": datetime(2025, 10, 1),
    "end_date": datetime(2025, 10, 2),
    "nodes": [
        {
            "node_name": "test-node-001",
            "resource_id": "CONTROLLED_OCP_ID_12345",  # ← We control this!
            "cpu_cores": 4,
            "memory_gig": 16,
            "namespaces": {
                "backend": {
                    "pods": [
                        {
                            "pod_name": "test-pod",
                            "cpu_request": 2,
                            "mem_request_gig": 4,
                            "pod_seconds": 3600,
                        }
                    ]
                }
            }
        }
    ]
}

try:
    ocp_gen = OCPGenerator(
        start_date=ocp_config["start_date"],
        end_date=ocp_config["end_date"],
        attributes=ocp_config
    )
    ocp_gen.generate_data(output_dir=output_dir)
    print("   ✓ OCP data generated")
except Exception as e:
    print(f"   ❌ OCP generation failed: {e}")
    import traceback
    traceback.print_exc()

# Test 2: AWS EC2 Generator with controlled resource_id
print("\n2️⃣  Testing AWS EC2 Generator...")
aws_config = {
    "start_date": datetime(2025, 10, 1),
    "end_date": datetime(2025, 10, 2),
    "generators": [
        {
            "EC2Generator": {
                "resource_id": "i-CONTROLLED_AWS_ID_12345",  # ← We control this!
                "amount": 24,
                "rate": 0.192,
            }
        }
    ]
}

try:
    ec2_gen = EC2Generator(
        start_date=aws_config["start_date"],
        end_date=aws_config["end_date"],
        attributes=aws_config["generators"][0]["EC2Generator"]
    )
    ec2_gen.generate_data(output_dir=output_dir)
    print("   ✓ AWS data generated")
except Exception as e:
    print(f"   ❌ AWS generation failed: {e}")
    import traceback
    traceback.print_exc()

# Verify the resource IDs in generated files
print("\n3️⃣  Verifying resource IDs in generated files...")
import glob
import csv

csv_files = glob.glob(f"{output_dir}/**/*.csv", recursive=True)
print(f"   Found {len(csv_files)} CSV files\n")

for csv_file in csv_files:
    print(f"   📄 {os.path.basename(csv_file)}")
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i > 2:  # Just show first 3 rows
                    break
                if 'resource_id' in row:
                    print(f"      Row {i+1} resource_id: {row['resource_id']}")
                elif 'lineItem/ResourceId' in row:
                    print(f"      Row {i+1} resource_id: {row['lineItem/ResourceId']}")
    except Exception as e:
        print(f"      ⚠️  Error reading: {e}")

print(f"\n{'=' * 60}")
print("Test Complete!")
print(f"{'=' * 60}")
print(f"\n🎯 If you see our controlled IDs above, the API works!")
print(f"   Expected OCP: CONTROLLED_OCP_ID_12345")
print(f"   Expected AWS: i-CONTROLLED_AWS_ID_12345")

