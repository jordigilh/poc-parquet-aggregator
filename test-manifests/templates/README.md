# Test Manifest Templates

## 📌 Overview

This directory contains template files and minimal examples for creating new test scenarios.

## 📄 Available Templates

### 1. `ocp_aws_template.yml`

**Purpose**: Template for OCP-on-AWS scenarios following the Trino SQL test patterns.

**Includes**:
- OCP cluster configuration
- AWS EC2 and EBS generators
- Expected outcome structure
- Common tag configurations

**Usage**:
```bash
# Create a new OCP-on-AWS scenario directory
mkdir ../ocp-on-aws/XX-my-scenario
cp ocp_aws_template.yml ../ocp-on-aws/XX-my-scenario/manifest.yml
```

**Best for**:
- OCP on AWS cost attribution tests
- Resource ID matching scenarios
- Tag-based matching scenarios
- Storage (EBS) attribution tests

---

### 2. `minimal_test.yml`

**Purpose**: Minimal test scenario for quick validation and debugging.

**Includes**:
- Simplest possible OCP + AWS configuration
- 1 cluster, 1 namespace, 1 pod
- 1 AWS EC2 instance
- Short time range (24 hours)

**Usage**:
```bash
# Quick smoke test using minimal manifest
python src/main.py --manifest test-manifests/templates/minimal_test.yml
```

**Best for**:
- Smoke testing the POC pipeline
- Debugging data flow issues
- Verifying basic functionality
- Quick iteration during development

---

## 🎯 Creating New Scenarios

### Step 1: Choose the Right Template

| Scenario Type | Template to Use |
|---------------|-----------------|
| OCP on AWS | `ocp_aws_template.yml` |
| Quick test | `minimal_test.yml` |
| OCP only | `ocp_template.yml` |

### Step 2: Create Scenario Directory

```bash
# For OCP-on-AWS scenarios
mkdir test-manifests/ocp-on-aws/XX-my-scenario
cp test-manifests/templates/ocp_aws_template.yml test-manifests/ocp-on-aws/XX-my-scenario/manifest.yml

# For OCP-only scenarios
mkdir test-manifests/ocp-only/XX-my-scenario
cp test-manifests/templates/ocp_template.yml test-manifests/ocp-only/XX-my-scenario/manifest.yml
```

### Step 3: Add a README

Create a `README.md` in your scenario directory explaining:
- What the scenario tests
- Expected outcomes
- How to run and validate

### Step 4: Customize the Scenario

Edit your `manifest.yml` and update:

1. **Scenario metadata**
   ```yaml
   scenario:
     name: "Descriptive Name"
     description: "What this scenario tests"
   ```

2. **OCP configuration**
   - Cluster ID and alias
   - Namespaces and pods
   - Resource usage (CPU, memory, storage)

3. **AWS configuration** (if applicable)
   - EC2 instance types and costs
   - EBS volumes and rates
   - Resource IDs and tags

4. **Expected outcomes**
   - Number of matches (resource/tag)
   - Expected attributed costs
   - Any specific validation criteria

### Step 5: Test Your Scenario

```bash
# Run the full scenario test suite
./scripts/run_ocp_aws_scenario_tests.sh
```

---

## 📐 Template Structure

All templates follow the **nise** manifest format:

```yaml
scenario:
  name: string
  description: string

providers:
  - OCP:
      generators:
        - OCPGenerator:
            cluster_id: string
            cluster_alias: string
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            namespaces:
              - name: string
                pods:
                  - name: string
                    cpu_usage: float
                    mem_usage_gig: float
                    resource_id: string

  - AWS:  # Optional for OCP-only scenarios
      generators:
        - EC2Generator:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            resource_id: string
            instance_type:
              inst_type: string
              cost: float  # per hour
              physical_cores: int
              storage: int
              family: string
              saving: int
            tags:
              key: value

        - EBSGenerator:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            resource_id: string
            amount: float  # GB
            rate: float  # per GB per hour
            tags:
              key: value

expected_outcome:
  resource_matches: int
  tag_matches: int
  attributed_cost: string  # "$X.XX"
```

---

## 💡 Best Practices

1. **Use meaningful directory names**
   - Directories: `XX-descriptive-name/`
   - Main manifest: `manifest.yml`
   - Variations: `variation.yml`

2. **Keep scenarios focused**
   - Test one concept per scenario
   - Use variations for different data sizes

3. **Document expected outcomes**
   - Always include `expected_outcome` section
   - Add a README explaining validation criteria

4. **Use realistic data**
   - Real AWS pricing (varied decimal precision)
   - Typical CPU/memory usage patterns
   - Standard time ranges (24h, 7d, 30d)

5. **Version variations**
   - Main: `manifest.yml`
   - Variation: `variation.yml`
   - Fixed version: `manifest_fixed.yml`

---

## 🔗 Related Documentation

- **OCP-on-AWS Scenarios**: [`../ocp-on-aws/README.md`](../ocp-on-aws/README.md)
- **OCP-Only Scenarios**: [`../ocp-only/README.md`](../ocp-only/README.md)
- **Nise Documentation**: [nise GitHub](https://github.com/project-koku/nise)

---

**Last Updated**: December 2, 2025
