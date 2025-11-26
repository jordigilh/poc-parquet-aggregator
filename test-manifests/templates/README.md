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
# Copy for a new OCP-on-AWS scenario
cp templates/ocp_aws_template.yml ocp-on-aws/ocp_aws_scenario_XX_my_test.yml
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
# Quick smoke test
./scripts/run_ocp_aws_scenario_tests.sh test-manifests/templates/minimal_test.yml
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

### Step 2: Copy to Appropriate Directory

```bash
# For OCP-on-AWS scenarios
cp templates/ocp_aws_template.yml ocp-on-aws/ocp_aws_scenario_XX_description.yml

# For OCP-only scenarios
cp templates/ocp_template.yml ocp-only/ocp_scenario_XX_description.yml
```

### Step 3: Customize the Scenario

Edit your new YAML file and update:

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

### Step 4: Test Your Scenario

```bash
# Run your new scenario
./scripts/run_ocp_aws_scenario_tests.sh test-manifests/ocp-on-aws/your_scenario.yml
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

1. **Use meaningful names**
   - Scenario files: `ocp_aws_scenario_##_descriptive_name.yml`
   - Cluster IDs: `test-cluster-###`
   - Resource IDs: `i-test-resource-###`

2. **Keep scenarios focused**
   - Test one concept per scenario
   - Use variations for different data sizes

3. **Document expected outcomes**
   - Always include `expected_outcome` section
   - Explain why costs should match

4. **Use realistic data**
   - Real AWS pricing (varied decimal precision)
   - Typical CPU/memory usage patterns
   - Standard time ranges (24h, 7d, 30d)

5. **Version variations**
   - Original: `ocp_aws_scenario_05_storage_ebs.yml`
   - Variation: `ocp_aws_scenario_05_variation.yml`
   - Fixed: `ocp_aws_scenario_05_storage_ebs_fixed.yml`

---

## 🔗 Related Documentation

- **Trino Migration Guide**: [`../../docs/methodology/TRINO_MIGRATION_METHODOLOGY.md`](../../docs/methodology/TRINO_MIGRATION_METHODOLOGY.md)
- **E2E Testing Guide**: [`../../docs/testing/E2E_TESTING_GUIDE.md`](../../docs/testing/E2E_TESTING_GUIDE.md)
- **Nise Documentation**: [nise GitHub](https://github.com/project-koku/nise)

---

**Last Updated**: November 25, 2025
