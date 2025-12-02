# Test Manifests - Organized by Use Case

## 📁 Directory Structure

```
test-manifests/
├── ocp-on-aws/          # OCP on AWS cost attribution scenarios
│   ├── 01-resource-matching/
│   │   ├── README.md
│   │   └── manifest.yml
│   ├── 02-tag-matching/
│   │   └── ...
│   └── ... (23 scenarios)
├── ocp-only/            # OCP-only cost scenarios
│   ├── 01-basic-pod/
│   │   ├── README.md
│   │   └── manifest.yml
│   └── ... (20 scenarios)
├── templates/           # Template files and examples
└── README.md            # This file
```

## 🎯 Use Case Categories

### 1. OCP on AWS (`ocp-on-aws/`)

**Description**: Cost attribution scenarios for OpenShift Container Platform (OCP) running on Amazon Web Services (AWS). These scenarios test the mapping of AWS infrastructure costs to OCP workloads.

**Test Coverage**:
- Resource ID matching (EC2 instance to OCP node)
- Tag-based matching (cluster, node, namespace tags)
- Storage cost attribution (EBS volumes to PVs)
- Network costs
- Multi-cluster scenarios
- Edge cases (zero usage, partial matching, unmatched resources)

**Current Scenarios**: 23 test scenarios covering Trino SQL parity

**Status**: ✅ All scenarios passing

See [`ocp-on-aws/README.md`](ocp-on-aws/README.md) for detailed scenario documentation.

---

### 2. OCP Only (`ocp-only/`)

**Description**: Cost scenarios for standalone OCP clusters without cloud provider integration. These scenarios test internal cost allocation, chargeback, and showback within OCP.

**Test Coverage**:
- Pod-level resource usage and cost allocation (CPU, memory)
- Storage usage and PVC costs
- Unallocated capacity (Platform/Worker)
- Label handling and edge cases
- Node capacity and cluster capacity

**Current Scenarios**: 20 scenarios

**Status**: ✅ Implemented

See [`ocp-only/README.md`](ocp-only/README.md) for detailed scenario documentation.

---

### 3. Templates (`templates/`)

**Description**: Template files and minimal examples for creating new test scenarios.

**Contents**:
- `ocp_aws_template.yml` - Template for OCP-on-AWS scenarios
- `minimal_test.yml` - Minimal scenario for quick validation

**Usage**: Copy and modify these templates when creating new test scenarios.

---

## 🚀 Usage

### Running OCP-on-AWS Scenarios

```bash
# Run all OCP-on-AWS scenarios
./scripts/run_ocp_aws_scenario_tests.sh

# Run a specific scenario directory
./scripts/run_ocp_aws_scenario_tests.sh 01-resource-matching
```

### Running OCP-Only Scenarios

```bash
# Run all OCP-only scenarios
./scripts/run_ocp_scenario_tests.sh

# Run a specific scenario
./scripts/run_ocp_scenario_tests.sh --scenario 01
```

### Creating New Scenarios

1. **Choose the appropriate directory** based on use case:
   - `ocp-on-aws/` for cloud provider integration scenarios
   - `ocp-only/` for standalone OCP scenarios

2. **Create a new scenario directory**:
   ```bash
   mkdir test-manifests/ocp-on-aws/XX-my-scenario
   cp test-manifests/templates/ocp_aws_template.yml test-manifests/ocp-on-aws/XX-my-scenario/manifest.yml
   ```

3. **Add a README.md** describing the scenario

4. **Follow naming conventions**:
   - Directory: `XX-descriptive-name/`
   - Main manifest: `manifest.yml`
   - Variations: `variation.yml`

---

## 📊 Test Manifest Format

Each test manifest follows the **nise** format and contains:

```yaml
scenario:
  name: "Scenario Name"
  description: "What this scenario tests"

providers:
  - OCP:
      generators:
        - OCPGenerator:
            # OCP cluster, namespace, pod configuration

  - AWS:
      generators:
        - EC2Generator:
            # AWS EC2 instance configuration
        - EBSGenerator:
            # AWS EBS volume configuration

expected_outcome:
  resource_matches: X
  tag_matches: Y
  attributed_cost: "$Z.ZZ"
```

---

## 🔍 Validation

Test scenarios are validated using:

1. **Nise data generation**: Generates CSV files for OCP and AWS
2. **POC aggregation**: Processes data through the POC pipeline
3. **Cost comparison**: Compares POC output against expected outcomes
4. **Trino parity validation**: Ensures POC matches Trino SQL logic

See the scenario READMEs for detailed validation methodology.

---

## 📚 Documentation

- **OCP-on-AWS Scenarios**: See [`ocp-on-aws/README.md`](ocp-on-aws/README.md)
- **OCP-Only Scenarios**: See [`ocp-only/README.md`](ocp-only/README.md)
- **Matching Labels Reference**: See [`../docs/MATCHING_LABELS.md`](../docs/MATCHING_LABELS.md)

---

## 🎯 Future Additions

As we migrate more Trino queries to the POC, additional use case directories will be added:

- `ocp-on-azure/` - OCP on Microsoft Azure
- `ocp-on-gcp/` - OCP on Google Cloud Platform
- `ocp-on-oci/` - OCP on Oracle Cloud Infrastructure
- `multi-cloud/` - Multi-cloud scenarios

Each directory will follow the same structure and documentation pattern established here.
