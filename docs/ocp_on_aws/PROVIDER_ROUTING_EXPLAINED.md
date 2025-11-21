# Provider Routing: How the Code Determines Which Aggregation to Use

**Date**: November 21, 2025
**Purpose**: Explain how the POC determines whether to use OCP, OCP on AWS, or AWS aggregation logic

---

## The Question

> "How does the code know which aggregation to use? OCP or OCP on AWS or AWS?"

This is a critical design question. The answer involves understanding:
1. **Provider Types** - What data sources exist
2. **Source Detection** - How we identify which provider type we're processing
3. **Routing Logic** - How we dispatch to the correct aggregation pipeline
4. **Configuration** - How users specify what to process

---

## Provider Types Overview

### 1. **OCP (OpenShift Container Platform)**
**Data Sources**:
- OCP Parquet files only (pod usage, storage, labels)

**What it does**:
- Aggregates OCP resource usage
- Applies label precedence (Pod > Namespace > Node)
- Calculates capacity metrics
- Outputs: `reporting_ocpusagelineitem_daily_summary_p`

**When to use**:
- Standalone OpenShift clusters
- No cloud provider integration

---

### 2. **OCP on AWS (OpenShift on AWS)**
**Data Sources**:
- OCP Parquet files (pod usage, storage, labels)
- AWS Parquet files (Cost and Usage Report)

**What it does**:
- Matches AWS resources to OCP workloads
- Attributes AWS costs to OCP namespaces
- Applies label precedence (inherited from OCP)
- Outputs: 9 summary tables including AWS cost breakdown

**When to use**:
- OpenShift running on AWS
- Need to show AWS infrastructure costs per namespace

---

### 3. **AWS (Amazon Web Services)** ⚠️ Not in Current Scope
**Data Sources**:
- AWS Parquet files only (Cost and Usage Report)

**What it does**:
- Aggregates AWS costs without OCP context
- Standard AWS cost reporting

**When to use**:
- Pure AWS workloads (no OpenShift)
- AWS cost analysis without container attribution

**Note**: This is NOT part of the current POC. The POC focuses on OCP and OCP on AWS only.

---

## How Provider Type is Determined

### Method 1: Configuration-Based Routing (Recommended)

The provider type is **explicitly specified in configuration**:

```yaml
# config/config.yaml

aggregation:
  providers:
    - name: "production-ocp-cluster"
      type: "OCP"                    # ← Explicitly set
      enabled: true
      source_uuid: "abc-123-ocp"

    - name: "production-ocp-on-aws"
      type: "OCP_AWS"                # ← Explicitly set
      enabled: true
      ocp_source_uuid: "abc-123-ocp"
      aws_source_uuid: "xyz-789-aws"
      markup: 0.10
```

**How it works**:
1. User configures provider type in YAML
2. Main entry point reads configuration
3. Dispatches to appropriate pipeline based on `type` field
4. Each pipeline knows its own logic

**Pros**:
- ✅ Explicit and clear
- ✅ Easy to understand
- ✅ User has full control
- ✅ Can process multiple providers in one run

**Cons**:
- ⚠️ User must configure correctly
- ⚠️ Misconfiguration could cause errors

---

### Method 2: Auto-Detection Based on Data Sources (Alternative)

The provider type is **automatically detected** based on available data:

```python
def detect_provider_type(source_uuid: str, s3_bucket: str) -> str:
    """
    Auto-detect provider type based on available Parquet files.

    Logic:
    - If only OCP files exist → OCP
    - If both OCP and AWS files exist → OCP_AWS
    - If only AWS files exist → AWS (not supported yet)

    Returns:
        "OCP", "OCP_AWS", or "AWS"
    """
    has_ocp_data = check_s3_path_exists(f"{s3_bucket}/openshift_pod_usage_line_items_daily/source={source_uuid}/")
    has_aws_data = check_s3_path_exists(f"{s3_bucket}/aws_line_items_daily/source={source_uuid}/")

    if has_ocp_data and has_aws_data:
        return "OCP_AWS"
    elif has_ocp_data:
        return "OCP"
    elif has_aws_data:
        return "AWS"  # Not supported yet
    else:
        raise ValueError(f"No data found for source {source_uuid}")
```

**Pros**:
- ✅ Automatic - no configuration needed
- ✅ Prevents misconfiguration

**Cons**:
- ⚠️ Requires S3 API calls (slower)
- ⚠️ Less explicit
- ⚠️ Harder to debug
- ⚠️ What if user wants to process OCP only even when AWS data exists?

---

### Method 3: Hybrid Approach (Best of Both)

Combine configuration with validation:

```python
def validate_and_route(provider_config: dict) -> str:
    """
    Validate configured provider type against available data.

    1. Read provider type from config
    2. Validate that required data sources exist
    3. Return validated provider type

    Raises:
        ValueError if configuration doesn't match available data
    """
    configured_type = provider_config['type']

    # Validate based on configured type
    if configured_type == "OCP":
        # Ensure OCP data exists
        if not has_ocp_data(provider_config['source_uuid']):
            raise ValueError(f"OCP provider configured but no OCP data found")
        return "OCP"

    elif configured_type == "OCP_AWS":
        # Ensure both OCP and AWS data exist
        if not has_ocp_data(provider_config['ocp_source_uuid']):
            raise ValueError(f"OCP_AWS provider configured but no OCP data found")
        if not has_aws_data(provider_config['aws_source_uuid']):
            raise ValueError(f"OCP_AWS provider configured but no AWS data found")
        return "OCP_AWS"

    else:
        raise ValueError(f"Unknown provider type: {configured_type}")
```

**Pros**:
- ✅ Explicit configuration
- ✅ Validated against reality
- ✅ Clear error messages
- ✅ Best of both worlds

**Cons**:
- ⚠️ Slightly more complex

---

## Implementation: Main Entry Point

### Current Design (Recommended)

```python
# src/main.py

import yaml
from src.main_ocp import OCPPipeline
from src.main_ocpaws import OCPAWSPipeline

def main():
    """
    Main entry point - routes to appropriate pipeline based on provider type.
    """
    # Load configuration
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    logger = setup_logging(config)
    postgres_conn = get_postgres_connection(config)

    # Process each configured provider
    for provider in config['aggregation']['providers']:
        if not provider.get('enabled', True):
            logger.info(f"Skipping disabled provider: {provider['name']}")
            continue

        provider_type = provider['type']
        logger.info(f"Processing provider: {provider['name']} (type: {provider_type})")

        # Route to appropriate pipeline based on type
        if provider_type == "OCP":
            run_ocp_pipeline(provider, config, logger, postgres_conn)

        elif provider_type == "OCP_AWS":
            run_ocpaws_pipeline(provider, config, logger, postgres_conn)

        else:
            logger.error(f"Unknown provider type: {provider_type}")
            raise ValueError(f"Unsupported provider type: {provider_type}")

    logger.info("All providers processed successfully")


def run_ocp_pipeline(provider: dict, config: dict, logger, postgres_conn):
    """
    Run OCP-only aggregation pipeline.

    This is the EXISTING POC logic.
    """
    logger.info("=" * 80)
    logger.info(f"Running OCP Pipeline for {provider['name']}")
    logger.info("=" * 80)

    pipeline = OCPPipeline(config, logger, postgres_conn)
    pipeline.run(
        source_uuid=provider['source_uuid'],
        year=config['date_range']['year'],
        month=config['date_range']['month'],
        schema=config['database']['schema']
    )

    logger.info(f"OCP Pipeline complete for {provider['name']}")


def run_ocpaws_pipeline(provider: dict, config: dict, logger, postgres_conn):
    """
    Run OCP on AWS aggregation pipeline.

    This is the NEW logic from the implementation guide.
    """
    logger.info("=" * 80)
    logger.info(f"Running OCP on AWS Pipeline for {provider['name']}")
    logger.info("=" * 80)

    pipeline = OCPAWSPipeline(config, logger, postgres_conn)
    pipeline.run(
        aws_source_uuid=provider['aws_source_uuid'],
        ocp_source_uuid=provider['ocp_source_uuid'],
        year=config['date_range']['year'],
        month=config['date_range']['month'],
        start_date=config['date_range']['start_date'],
        end_date=config['date_range']['end_date'],
        schema=config['database']['schema'],
        markup=provider.get('markup', 0.0)
    )

    logger.info(f"OCP on AWS Pipeline complete for {provider['name']}")


if __name__ == "__main__":
    main()
```

---

## Configuration Examples

### Example 1: Single OCP Cluster

```yaml
# config/config.yaml

aggregation:
  providers:
    - name: "production-cluster"
      type: "OCP"
      enabled: true
      source_uuid: "550e8400-e29b-41d4-a716-446655440000"

date_range:
  year: "2025"
  month: "11"

database:
  schema: "org1234567"
```

**Result**: Runs OCP pipeline only, outputs to `reporting_ocpusagelineitem_daily_summary_p`

---

### Example 2: OCP on AWS

```yaml
# config/config.yaml

aggregation:
  providers:
    - name: "aws-production-cluster"
      type: "OCP_AWS"
      enabled: true
      ocp_source_uuid: "550e8400-e29b-41d4-a716-446655440000"
      aws_source_uuid: "660e8400-e29b-41d4-a716-446655440001"
      markup: 0.10  # 10% markup on AWS costs

date_range:
  year: "2025"
  month: "11"
  start_date: "2025-11-01"
  end_date: "2025-11-30"

database:
  schema: "org1234567"
```

**Result**: Runs OCP on AWS pipeline, outputs to 9 summary tables

---

### Example 3: Multiple Providers (Mixed)

```yaml
# config/config.yaml

aggregation:
  providers:
    # Standalone OCP cluster
    - name: "on-prem-cluster"
      type: "OCP"
      enabled: true
      source_uuid: "550e8400-e29b-41d4-a716-446655440000"

    # OCP on AWS cluster
    - name: "aws-east-cluster"
      type: "OCP_AWS"
      enabled: true
      ocp_source_uuid: "660e8400-e29b-41d4-a716-446655440001"
      aws_source_uuid: "770e8400-e29b-41d4-a716-446655440002"
      markup: 0.10

    # Another OCP on AWS cluster
    - name: "aws-west-cluster"
      type: "OCP_AWS"
      enabled: true
      ocp_source_uuid: "880e8400-e29b-41d4-a716-446655440003"
      aws_source_uuid: "990e8400-e29b-41d4-a716-446655440004"
      markup: 0.15  # Different markup

date_range:
  year: "2025"
  month: "11"
  start_date: "2025-11-01"
  end_date: "2025-11-30"

database:
  schema: "org1234567"
```

**Result**:
1. Runs OCP pipeline for on-prem cluster
2. Runs OCP on AWS pipeline for aws-east cluster
3. Runs OCP on AWS pipeline for aws-west cluster

All in one execution!

---

## Data Flow Visualization

```
┌─────────────────────────────────────────────────────────────────┐
│                         MAIN ENTRY POINT                         │
│                           (src/main.py)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    Read config.yaml
                             │
                             ▼
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌─────────────────┐         ┌─────────────────────┐
    │  Provider 1     │         │  Provider 2         │
    │  type: "OCP"    │         │  type: "OCP_AWS"    │
    └────────┬────────┘         └──────────┬──────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐         ┌─────────────────────┐
    │  OCP Pipeline   │         │  OCP on AWS Pipeline│
    │  (existing)     │         │  (new)              │
    └────────┬────────┘         └──────────┬──────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐         ┌─────────────────────┐
    │  Read OCP       │         │  Read OCP + AWS     │
    │  Parquet        │         │  Parquet            │
    └────────┬────────┘         └──────────┬──────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐         ┌─────────────────────┐
    │  Aggregate      │         │  Match Resources    │
    │  (label         │         │  ├─> Resource ID    │
    │   precedence)   │         │  └─> Tags           │
    └────────┬────────┘         └──────────┬──────────┘
             │                             │
             │                             ▼
             │                   ┌─────────────────────┐
             │                   │  Attribute Costs    │
             │                   │  ├─> Storage        │
             │                   │  ├─> Compute        │
             │                   │  └─> Network        │
             │                   └──────────┬──────────┘
             │                             │
             │                             ▼
             │                   ┌─────────────────────┐
             │                   │  Aggregate          │
             │                   │  (9 tables)         │
             │                   └──────────┬──────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐         ┌─────────────────────┐
    │  Write to       │         │  Write to           │
    │  PostgreSQL     │         │  PostgreSQL         │
    │  (1 table)      │         │  (9 tables)         │
    └─────────────────┘         └─────────────────────┘
```

---

## Key Design Decisions

### 1. **Explicit Configuration Over Auto-Detection**

**Decision**: Use explicit `type` field in configuration

**Rationale**:
- Clear and unambiguous
- User has full control
- Easy to debug
- Supports mixed environments
- No S3 API overhead

**Trade-off**: User must configure correctly, but validation catches errors

---

### 2. **Separate Pipelines, Shared Infrastructure**

**Decision**: `OCPPipeline` and `OCPAWSPipeline` are separate classes

**Rationale**:
- Clear separation of concerns
- Each pipeline has its own logic
- Easier to test independently
- Can evolve separately
- Shared components (ParquetReader, PostgreSQLWriter) are reused

**Trade-off**: Some code duplication, but cleaner architecture

---

### 3. **Provider-Level Configuration**

**Decision**: Each provider is configured independently

**Rationale**:
- Supports multiple clusters
- Different markup per provider
- Enable/disable per provider
- Flexible for complex deployments

**Trade-off**: More configuration, but more powerful

---

## How to Add a New Provider Type

If you wanted to add pure AWS support (no OCP) in the future:

### Step 1: Add to Configuration

```yaml
providers:
  - name: "pure-aws-account"
    type: "AWS"  # New type
    enabled: true
    source_uuid: "aws-only-uuid"
```

### Step 2: Create Pipeline

```python
# src/main_aws.py

class AWSPipeline:
    """Pipeline for pure AWS cost aggregation (no OCP)."""

    def run(self, source_uuid, year, month, schema):
        # AWS-only aggregation logic
        pass
```

### Step 3: Add to Router

```python
# src/main.py

def main():
    for provider in config['aggregation']['providers']:
        if provider['type'] == "OCP":
            run_ocp_pipeline(...)
        elif provider['type'] == "OCP_AWS":
            run_ocpaws_pipeline(...)
        elif provider['type'] == "AWS":  # New
            run_aws_pipeline(...)
```

That's it! The routing pattern makes it easy to extend.

---

## Summary

### How the Code Knows Which Aggregation to Use:

1. **Configuration File** (`config.yaml`) explicitly specifies provider `type`
2. **Main Entry Point** (`src/main.py`) reads configuration
3. **Router Logic** dispatches to appropriate pipeline based on `type`:
   - `"OCP"` → `OCPPipeline` (existing)
   - `"OCP_AWS"` → `OCPAWSPipeline` (new)
4. **Each Pipeline** contains its own aggregation logic
5. **Shared Infrastructure** (ParquetReader, PostgreSQLWriter) is reused

### Key Points:

✅ **Explicit Configuration**: User specifies provider type
✅ **Clear Routing**: Simple if/elif logic based on type
✅ **Separate Pipelines**: Each provider type has its own pipeline class
✅ **Shared Components**: Common infrastructure is reused
✅ **Extensible**: Easy to add new provider types
✅ **Flexible**: Supports multiple providers in one run

### Configuration is King:

The provider type is **not auto-detected** from data. It's **explicitly configured** by the user. This makes the system:
- Predictable
- Debuggable
- Flexible
- Fast (no S3 API calls to detect)

---

**Document**: PROVIDER_ROUTING_EXPLAINED.md
**Status**: ✅ Complete
**Date**: November 21, 2025
**Next**: Review and integrate into implementation plan

