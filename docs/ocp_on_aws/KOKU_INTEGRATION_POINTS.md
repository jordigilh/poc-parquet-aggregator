# Koku Integration Points: Where the POC Replaces Trino

**Date**: November 21, 2025
**Purpose**: Explain how Koku currently uses Trino and where the POC will be integrated

---

## The Question

> "How does Koku know which flow to use? Since our goal is to replace Trino with this POC, show me where the POC would be integrated into Koku?"

This document explains:
1. **Current Koku Architecture** - How Koku uses Trino today
2. **Decision Points** - Where Koku decides to use Trino
3. **Integration Points** - Where to plug in the POC
4. **Migration Strategy** - How to transition from Trino to POC

---

## Current Koku Architecture

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATA INGESTION (MASU)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Data Collection                                             │
│     ├─> Download cost/usage reports from cloud providers        │
│     ├─> Download OpenShift metrics from clusters                │
│     └─> Store raw data in S3                                    │
│                                                                  │
│  2. Parquet Conversion                                          │
│     ├─> Convert raw data to Parquet format                      │
│     ├─> Partition by source, year, month                        │
│     └─> Upload to S3 (Hive-compatible structure)               │
│                                                                  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────────┐
│              AGGREGATION (MASU) ← POC REPLACES THIS             │
├─────────────────────────┼───────────────────────────────────────┤
│                         │                                        │
│  3. Trino Aggregation (CURRENT)                                 │
│     ├─> Trino reads Parquet from S3 via Hive metastore         │
│     ├─> Executes SQL queries to aggregate data                 │
│     ├─> Writes results to PostgreSQL summary tables            │
│     └─> Used for: OCP, OCP on AWS, OCP on Azure, OCP on GCP    │
│                         │                                        │
│                         ▼                                        │
│  4. PostgreSQL Summary Tables                                   │
│     ├─> reporting_ocpusagelineitem_daily_summary_p (OCP)       │
│     ├─> reporting_ocpawscostlineitem_project_daily_summary_p   │
│     ├─> reporting_ocpaws_cost_summary_p                         │
│     ├─> ... (9 tables for OCP on AWS)                          │
│     └─> Similar tables for Azure and GCP                       │
│                                                                  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────────┐
│                    API LAYER (KOKU)                              │
├─────────────────────────┼───────────────────────────────────────┤
│                         │                                        │
│  5. API Query Handlers                                          │
│     ├─> Read from PostgreSQL summary tables                     │
│     ├─> Apply filters, grouping, ordering                       │
│     └─> Return JSON responses to UI                            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Key Insight

**The POC replaces Step 3 (Trino Aggregation)** while keeping everything else the same:
- ✅ Step 1-2 (Data Ingestion) - No change
- ❌ Step 3 (Trino Aggregation) - **REPLACED by POC**
- ✅ Step 4 (PostgreSQL Tables) - No change (same tables)
- ✅ Step 5 (API Layer) - No change

---

## How Koku Currently Decides to Use Trino

### Decision Point 1: Provider Type Detection

**Location**: `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py`

```python
class OCPCloudParquetReportSummaryUpdater:
    """Class to update OCP report summary data."""
    
    def update_summary_tables(self, start_date, end_date, ocp_provider_uuid, 
                              infra_provider_uuid, infra_provider_type):
        """
        Populate the summary tables for reporting.
        
        This is THE KEY DECISION POINT for provider routing.
        """
        # Decision based on infrastructure provider type
        if infra_provider_type in (Provider.PROVIDER_AWS, Provider.PROVIDER_AWS_LOCAL):
            self.update_aws_summary_tables(ocp_provider_uuid, infra_provider_uuid, 
                                          start_date, end_date)
        
        elif infra_provider_type in (Provider.PROVIDER_AZURE, Provider.PROVIDER_AZURE_LOCAL):
            self.update_azure_summary_tables(ocp_provider_uuid, infra_provider_uuid, 
                                            start_date, end_date)
        
        elif infra_provider_type in (Provider.PROVIDER_GCP, Provider.PROVIDER_GCP_LOCAL):
            self.update_gcp_summary_tables(ocp_provider_uuid, infra_provider_uuid, 
                                          start_date, end_date)
```

**How it knows**:
- Koku maintains a `Provider` model in PostgreSQL
- Each provider has a `type` field (e.g., "AWS", "Azure", "GCP", "OCP")
- For OCP on Cloud, there's also an `infrastructure` relationship linking OCP to the cloud provider
- The `infra_provider_type` is passed from the task orchestration layer

---

### Decision Point 2: OCP on AWS Trino Execution

**Location**: `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py`

```python
def update_aws_summary_tables(self, openshift_provider_uuid, aws_provider_uuid, 
                               start_date, end_date):
    """Update operations specifically for OpenShift on AWS."""
    
    # Get cluster info
    cluster_id = get_cluster_id_from_provider(openshift_provider_uuid)
    cluster_alias = get_cluster_alias_from_cluster_id(cluster_id)
    
    # Get report period and bill IDs
    with OCPReportDBAccessor(self._schema) as accessor:
        report_period = accessor.report_periods_for_provider_uuid(
            openshift_provider_uuid, start_date
        )
        report_period_id = report_period.id
    
    with AWSReportDBAccessor(self._schema) as accessor:
        bills = accessor.get_cost_entry_bills_by_date(aws_provider_uuid)
        bill_id = bills.first().id
        
        # THIS IS WHERE TRINO IS CALLED
        accessor.populate_ocp_on_aws_cost_daily_summary_trino(
            start_date,
            end_date,
            openshift_provider_uuid,
            aws_provider_uuid,
            report_period_id,
            bill_id
        )
```

---

### Decision Point 3: Trino SQL Execution

**Location**: `koku/masu/database/aws_report_db_accessor.py`

```python
class AWSReportDBAccessor:
    
    def populate_ocp_on_aws_cost_daily_summary_trino(
        self,
        start_date,
        end_date,
        openshift_provider_uuid,
        aws_provider_uuid,
        report_period_id,
        bill_id,
    ):
        """
        Populate the daily cost aggregated summary for OCP on AWS.
        
        THIS METHOD EXECUTES TRINO SQL QUERIES.
        """
        # Prepare SQL metadata
        sql_metadata = SummarySqlMetadata(
            self.schema,
            openshift_provider_uuid,
            aws_provider_uuid,
            start_date,
            end_date,
            matched_tags,
            bill_id,
            report_period_id,
        )
        
        # Path to Trino SQL files
        managed_path = "trino_sql/aws/openshift/populate_daily_summary"
        
        # Step 1: Prepare tables
        prepare_sql, prepare_params = sql_metadata.prepare_template(
            f"{managed_path}/0_prepare_daily_summary_tables.sql"
        )
        self._execute_trino_multipart_sql_query(prepare_sql, bind_params=prepare_params)
        
        # Step 2: Resource matching
        resource_matching_sql, resource_matching_params = sql_metadata.prepare_template(
            f"{managed_path}/1_resource_matching_by_cluster.sql",
            {"matched_tag_array": self.find_openshift_keys_expected_values(sql_metadata)}
        )
        self._execute_trino_multipart_sql_query(resource_matching_sql, 
                                               bind_params=resource_matching_params)
        
        # Step 3: Summarize data
        summarize_sql, summarize_params = sql_metadata.prepare_template(
            f"{managed_path}/2_summarize_data_by_cluster.sql"
        )
        self._execute_trino_multipart_sql_query(summarize_sql, bind_params=summarize_params)
        
        # Step 4: Finalize
        finalize_sql, finalize_params = sql_metadata.prepare_template(
            f"{managed_path}/3_reporting_ocpawscostlineitem_project_daily_summary_p.sql"
        )
        self._execute_trino_multipart_sql_query(finalize_sql, bind_params=finalize_params)
        
        # Execute 9 aggregation queries
        for sql_file in [
            "reporting_ocpaws_cost_summary_p.sql",
            "reporting_ocpaws_cost_summary_by_account_p.sql",
            "reporting_ocpaws_cost_summary_by_service_p.sql",
            # ... 6 more files
        ]:
            sql, params = sql_metadata.prepare_template(f"trino_sql/aws/openshift/{sql_file}")
            self._execute_trino_multipart_sql_query(sql, bind_params=params)
```

---

## Standalone OCP Flow (For Reference)

### Where OCP-Only Aggregation Happens

**Location**: `koku/masu/processor/ocp/ocp_report_parquet_summary_updater.py`

```python
class OCPReportParquetSummaryUpdater:
    """Update OCP report summary tables."""
    
    def update_daily_tables(self, start_date, end_date):
        """Update OCP daily summary tables."""
        
        with OCPReportDBAccessor(self._schema) as accessor:
            # Get report period
            report_period = accessor.report_periods_for_provider_uuid(
                self._provider.uuid, start_date
            )
            report_period_id = report_period.id
            
            # Populate cluster information
            accessor.populate_openshift_cluster_information_tables(
                self._provider, self._cluster_id, self._cluster_alias, 
                start_date, end_date
            )
            
            # THIS IS WHERE TRINO IS CALLED FOR OCP
            for start, end in date_range_pair(start_date, end_date, 
                                             step=settings.TRINO_DATE_STEP):
                # Delete existing data
                accessor.delete_all_except_infrastructure_raw_cost_from_daily_summary(
                    self._provider.uuid, report_period_id, start, end
                )
                
                # Aggregate using Trino
                accessor.populate_line_item_daily_summary_table_trino(
                    start, end, report_period_id, self._cluster_id, 
                    self._cluster_alias, self._provider.uuid
                )
                
                # Populate UI tables
                accessor.populate_ui_summary_tables(start, end, self._provider.uuid)
```

**DB Accessor**: `koku/masu/database/ocp_report_db_accessor.py`

```python
class OCPReportDBAccessor:
    
    def populate_line_item_daily_summary_table_trino(
        self, start_date, end_date, report_period_id, cluster_id, 
        cluster_alias, source
    ):
        """
        Populate the daily aggregate of line items table.
        
        THIS METHOD EXECUTES TRINO SQL FOR OCP.
        """
        # Prepare parameters
        year = start_date.strftime("%Y")
        month = start_date.strftime("%m")
        days = self.date_helper.list_days(start_date, end_date)
        days_tup = tuple(str(day.day) for day in days)
        
        # Delete Hive partitions
        self.delete_ocp_hive_partition_by_day(days_tup, source, year, month)
        
        # Load Trino SQL
        sql = pkgutil.get_data(
            "masu.database", 
            "trino_sql/reporting_ocpusagelineitem_daily_summary.sql"
        )
        sql = sql.decode("utf-8")
        
        # Execute Trino query
        sql_params = {
            "uuid": source,
            "start_date": start_date,
            "end_date": end_date,
            "report_period_id": report_period_id,
            "cluster_id": cluster_id,
            "cluster_alias": cluster_alias,
            "schema": self.schema,
            "source": str(source),
            "year": year,
            "month": month,
            "days": days_tup,
            "storage_exists": trino_table_exists(
                self.schema, "openshift_storage_usage_line_items_daily"
            ),
        }
        
        self._execute_trino_multipart_sql_query(sql, bind_params=sql_params)
```

**Trino SQL**: `koku/masu/database/trino_sql/reporting_ocpusagelineitem_daily_summary.sql`

This is a **415-line SQL file** that:
1. Reads from Hive tables: `openshift_pod_usage_line_items_daily`, `openshift_storage_usage_line_items_daily`, `openshift_node_labels_line_items_daily`
2. Applies label precedence (Pod > Namespace > Node)
3. Calculates capacity, usage, requests, limits
4. Aggregates by cluster, namespace, pod, node
5. Writes to PostgreSQL: `reporting_ocpusagelineitem_daily_summary_p`

---

## POC Integration Points

### Integration Strategy: Drop-in Replacement

The POC should be a **drop-in replacement** for the Trino execution, maintaining the same interface.

### Option 1: Replace at the DB Accessor Level (Recommended)

**Where**: `koku/masu/database/aws_report_db_accessor.py`

**Current Code**:
```python
def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """Uses Trino to aggregate."""
    # Execute Trino SQL queries
    self._execute_trino_multipart_sql_query(...)
```

**New Code**:
```python
def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """
    Populate OCP on AWS summary tables.
    
    Uses POC aggregator instead of Trino.
    """
    # Check if POC is enabled
    if settings.USE_POC_AGGREGATOR:
        return self._populate_using_poc_aggregator(
            start_date, end_date, openshift_provider_uuid, 
            aws_provider_uuid, report_period_id, bill_id
        )
    else:
        # Fallback to Trino (for gradual migration)
        return self._populate_using_trino(
            start_date, end_date, openshift_provider_uuid, 
            aws_provider_uuid, report_period_id, bill_id
        )

def _populate_using_poc_aggregator(self, ...):
    """Use POC aggregator to populate summary tables."""
    from poc_aggregator.main_ocpaws import OCPAWSPipeline
    
    # Initialize POC pipeline
    pipeline = OCPAWSPipeline(
        config=self._get_poc_config(),
        logger=LOG,
        postgres_conn=self._get_db_connection()
    )
    
    # Run aggregation
    pipeline.run(
        aws_source_uuid=str(aws_provider_uuid),
        ocp_source_uuid=str(openshift_provider_uuid),
        year=start_date.strftime("%Y"),
        month=start_date.strftime("%m"),
        start_date=str(start_date),
        end_date=str(end_date),
        schema=self.schema,
        markup=self._get_markup_for_provider(aws_provider_uuid)
    )

def _populate_using_trino(self, ...):
    """Original Trino implementation (for fallback)."""
    # Existing Trino code
    sql_metadata = SummarySqlMetadata(...)
    # ... rest of existing code
```

**Pros**:
- ✅ Minimal changes to Koku codebase
- ✅ Easy to toggle between Trino and POC
- ✅ Gradual migration path
- ✅ Same interface for callers

**Cons**:
- ⚠️ POC code needs to be importable by Koku
- ⚠️ Need to handle POC configuration

---

### Option 2: Replace at the Updater Level

**Where**: `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py`

**Current Code**:
```python
def update_aws_summary_tables(self, openshift_provider_uuid, aws_provider_uuid, 
                               start_date, end_date):
    """Update operations specifically for OpenShift on AWS."""
    # ... get cluster info, report period, bill ID ...
    
    with AWSReportDBAccessor(self._schema) as accessor:
        accessor.populate_ocp_on_aws_cost_daily_summary_trino(...)
```

**New Code**:
```python
def update_aws_summary_tables(self, openshift_provider_uuid, aws_provider_uuid, 
                               start_date, end_date):
    """Update operations specifically for OpenShift on AWS."""
    # ... get cluster info, report period, bill ID ...
    
    if settings.USE_POC_AGGREGATOR:
        self._update_using_poc(openshift_provider_uuid, aws_provider_uuid, 
                              start_date, end_date)
    else:
        with AWSReportDBAccessor(self._schema) as accessor:
            accessor.populate_ocp_on_aws_cost_daily_summary_trino(...)

def _update_using_poc(self, openshift_provider_uuid, aws_provider_uuid, 
                      start_date, end_date):
    """Use POC aggregator."""
    from poc_aggregator.main_ocpaws import OCPAWSPipeline
    # ... same as Option 1
```

**Pros**:
- ✅ Cleaner separation
- ✅ Easier to maintain both paths

**Cons**:
- ⚠️ More code duplication
- ⚠️ Need to replicate some DB accessor logic

---

### Option 3: Separate Task (Most Flexible)

**Where**: Create new Celery task

**New File**: `koku/masu/processor/tasks.py`

```python
@celery_app.task(name="masu.processor.tasks.run_poc_aggregation")
def run_poc_aggregation(
    schema_name,
    provider_type,
    ocp_provider_uuid,
    infra_provider_uuid,
    start_date,
    end_date,
    manifest_id=None,
    tracing_id=None
):
    """
    Run POC aggregation for OCP on Cloud.
    
    This is a new task that runs the POC aggregator.
    """
    from poc_aggregator.main_ocpaws import OCPAWSPipeline
    from poc_aggregator.main_ocpazure import OCPAzurePipeline
    from poc_aggregator.main_ocpgcp import OCPGCPPipeline
    
    # Route to appropriate POC pipeline
    if provider_type in (Provider.PROVIDER_AWS, Provider.PROVIDER_AWS_LOCAL):
        pipeline_class = OCPAWSPipeline
    elif provider_type in (Provider.PROVIDER_AZURE, Provider.PROVIDER_AZURE_LOCAL):
        pipeline_class = OCPAzurePipeline
    elif provider_type in (Provider.PROVIDER_GCP, Provider.PROVIDER_GCP_LOCAL):
        pipeline_class = OCPGCPPipeline
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    
    # Initialize and run
    pipeline = pipeline_class(
        config=get_poc_config(),
        logger=LOG,
        postgres_conn=get_db_connection(schema_name)
    )
    
    pipeline.run(
        aws_source_uuid=str(infra_provider_uuid),
        ocp_source_uuid=str(ocp_provider_uuid),
        year=start_date.strftime("%Y"),
        month=start_date.strftime("%m"),
        start_date=str(start_date),
        end_date=str(end_date),
        schema=schema_name
    )
```

**Modify**: `koku/masu/processor/ocp/ocp_cloud_parquet_summary_updater.py`

```python
def update_summary_tables(self, start_date, end_date, ocp_provider_uuid, 
                          infra_provider_uuid, infra_provider_type):
    """Populate the summary tables for reporting."""
    
    if settings.USE_POC_AGGREGATOR:
        # Use new POC task
        run_poc_aggregation.delay(
            schema_name=self._schema,
            provider_type=infra_provider_type,
            ocp_provider_uuid=ocp_provider_uuid,
            infra_provider_uuid=infra_provider_uuid,
            start_date=start_date,
            end_date=end_date
        )
    else:
        # Existing Trino path
        if infra_provider_type in (Provider.PROVIDER_AWS, Provider.PROVIDER_AWS_LOCAL):
            self.update_aws_summary_tables(...)
        # ... etc
```

**Pros**:
- ✅ Clean separation of concerns
- ✅ POC runs as independent task
- ✅ Easy to monitor and debug
- ✅ Can run in parallel with other tasks

**Cons**:
- ⚠️ More infrastructure changes
- ⚠️ Need to handle task orchestration

---

## Configuration: How to Enable POC

### Django Settings

**File**: `koku/koku/settings.py`

```python
# POC Aggregator Configuration
USE_POC_AGGREGATOR = env.bool("USE_POC_AGGREGATOR", default=False)

POC_AGGREGATOR_CONFIG = {
    "s3": {
        "bucket": env.str("S3_BUCKET_NAME"),
        "endpoint": env.str("S3_ENDPOINT"),
        "access_key": env.str("S3_ACCESS_KEY"),
        "secret_key": env.str("S3_SECRET_KEY"),
    },
    "performance": {
        "parallel_readers": env.int("POC_PARALLEL_READERS", default=4),
        "use_streaming": env.bool("POC_USE_STREAMING", default=False),
        "chunk_size": env.int("POC_CHUNK_SIZE", default=50000),
        "use_categorical": env.bool("POC_USE_CATEGORICAL", default=True),
        "column_filtering": env.bool("POC_COLUMN_FILTERING", default=True),
    },
    "logging": {
        "level": env.str("POC_LOG_LEVEL", default="INFO"),
    }
}
```

### Environment Variables

```bash
# Enable POC aggregator
export USE_POC_AGGREGATOR=true

# POC performance settings
export POC_PARALLEL_READERS=4
export POC_USE_STREAMING=false
export POC_CHUNK_SIZE=50000
export POC_USE_CATEGORICAL=true
export POC_COLUMN_FILTERING=true
export POC_LOG_LEVEL=INFO
```

---

## Migration Strategy

### Phase 1: Parallel Deployment (Validation)

**Goal**: Run both Trino and POC, compare results

```python
def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """Run both Trino and POC, compare results."""
    
    # Run Trino (existing)
    trino_results = self._populate_using_trino(...)
    
    # Run POC
    if settings.POC_VALIDATION_MODE:
        try:
            poc_results = self._populate_using_poc_aggregator(...)
            
            # Compare results
            self._compare_trino_vs_poc(trino_results, poc_results)
        except Exception as e:
            LOG.error(f"POC aggregation failed: {e}")
            # Continue with Trino results
    
    return trino_results
```

**Duration**: 1-2 months
**Outcome**: Confidence in POC accuracy

---

### Phase 2: Gradual Rollout (Feature Flag)

**Goal**: Enable POC for subset of customers

```python
def should_use_poc_aggregator(schema_name):
    """Determine if POC should be used for this customer."""
    
    if not settings.USE_POC_AGGREGATOR:
        return False
    
    # Feature flag per customer
    if schema_name in settings.POC_ENABLED_SCHEMAS:
        return True
    
    # Percentage-based rollout
    if settings.POC_ROLLOUT_PERCENTAGE > 0:
        # Use hash of schema name for consistent routing
        hash_val = int(hashlib.md5(schema_name.encode()).hexdigest(), 16)
        if (hash_val % 100) < settings.POC_ROLLOUT_PERCENTAGE:
            return True
    
    return False
```

**Duration**: 2-3 months
**Outcome**: POC running in production for subset

---

### Phase 3: Full Migration

**Goal**: POC becomes default, Trino is fallback

```python
def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """Use POC by default, Trino as fallback."""
    
    try:
        return self._populate_using_poc_aggregator(...)
    except Exception as e:
        LOG.error(f"POC aggregation failed, falling back to Trino: {e}")
        return self._populate_using_trino(...)
```

**Duration**: 1-2 months
**Outcome**: POC is primary, Trino is safety net

---

### Phase 4: Trino Removal

**Goal**: Remove Trino completely

```python
def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """Use POC only."""
    return self._populate_using_poc_aggregator(...)
```

**Duration**: 1 month
**Outcome**: Trino infrastructure can be decommissioned

---

## POC Packaging for Koku Integration

### Option A: Python Package

**Structure**:
```
poc-parquet-aggregator/
├── setup.py
├── poc_aggregator/
│   ├── __init__.py
│   ├── main_ocp.py
│   ├── main_ocpaws.py
│   ├── main_ocpazure.py
│   ├── main_ocpgcp.py
│   ├── aws_data_loader.py
│   ├── resource_matcher.py
│   ├── cost_attributor.py
│   ├── aggregator_ocpaws.py
│   └── ... (all other modules)
└── requirements.txt
```

**Installation**:
```bash
# In Koku's requirements.txt
poc-parquet-aggregator @ git+https://github.com/insights-onprem/poc-parquet-aggregator.git@main
```

**Import in Koku**:
```python
from poc_aggregator.main_ocpaws import OCPAWSPipeline
```

---

### Option B: Microservice

**Structure**:
```
POC runs as separate service
Koku calls POC via HTTP API
```

**API Endpoint**:
```
POST /api/v1/aggregate
{
    "provider_type": "OCP_AWS",
    "ocp_source_uuid": "...",
    "aws_source_uuid": "...",
    "start_date": "2025-11-01",
    "end_date": "2025-11-30",
    "schema": "org1234567"
}
```

**Pros**:
- ✅ Complete isolation
- ✅ Independent scaling
- ✅ Can be deployed separately

**Cons**:
- ⚠️ More infrastructure
- ⚠️ Network overhead
- ⚠️ More complex deployment

---

## Complete Integration Picture

### Both OCP and OCP on AWS Integration Points

Here's a side-by-side comparison of where the POC integrates for both use cases:

| Aspect | **OCP (Standalone)** | **OCP on AWS** |
|--------|---------------------|----------------|
| **Entry Point** | `OCPReportParquetSummaryUpdater.update_daily_tables()` | `OCPCloudParquetReportSummaryUpdater.update_aws_summary_tables()` |
| **DB Accessor** | `OCPReportDBAccessor` | `AWSReportDBAccessor` |
| **Trino Method** | `populate_line_item_daily_summary_table_trino()` | `populate_ocp_on_aws_cost_daily_summary_trino()` |
| **Trino SQL Files** | 1 file (415 lines) | 13 files (1,500+ lines) |
| **Input Tables** | `openshift_pod_usage_line_items_daily`<br>`openshift_storage_usage_line_items_daily`<br>`openshift_node_labels_line_items_daily` | Same OCP tables +<br>`aws_line_items_daily` |
| **Output Tables** | `reporting_ocpusagelineitem_daily_summary_p` (1 table) | `reporting_ocpawscostlineitem_project_daily_summary_p` + 9 aggregation tables |
| **Complexity** | Medium (label precedence, capacity calc) | High (resource matching, cost attribution, tag matching) |
| **POC Module** | `src/main.py` (existing POC) | `src/main_ocpaws.py` (to be implemented) |

### Integration Points Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                      KOKU TASK ORCHESTRATION                     │
│                  (masu/processor/tasks.py)                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ├─> Is this OCP only?
                         │   └─> OCPReportParquetSummaryUpdater
                         │       └─> OCPReportDBAccessor
                         │           └─> populate_line_item_daily_summary_table_trino()
                         │               ├─ CURRENT: Execute Trino SQL
                         │               └─ POC: Call POC OCP Pipeline
                         │
                         └─> Is this OCP on Cloud?
                             └─> OCPCloudParquetReportSummaryUpdater
                                 ├─> AWS? → update_aws_summary_tables()
                                 │          └─> AWSReportDBAccessor
                                 │              └─> populate_ocp_on_aws_cost_daily_summary_trino()
                                 │                  ├─ CURRENT: Execute 13 Trino SQL files
                                 │                  └─ POC: Call POC OCP-AWS Pipeline
                                 │
                                 ├─> Azure? → update_azure_summary_tables()
                                 │           └─> AzureReportDBAccessor
                                 │               └─> populate_ocp_on_azure_cost_daily_summary_trino()
                                 │
                                 └─> GCP? → update_gcp_summary_tables()
                                            └─> GCPReportDBAccessor
                                                └─> populate_ocp_on_gcp_cost_daily_summary_trino()
```

### Recommended Integration Approach

**For OCP Standalone**:
```python
# File: koku/masu/database/ocp_report_db_accessor.py

def populate_line_item_daily_summary_table_trino(self, ...):
    """Populate OCP daily summary using Trino or POC."""
    
    if settings.USE_POC_AGGREGATOR:
        return self._populate_using_poc_ocp(...)
    else:
        return self._populate_using_trino_ocp(...)

def _populate_using_poc_ocp(self, start_date, end_date, report_period_id, 
                            cluster_id, cluster_alias, source):
    """Use POC for OCP aggregation."""
    from poc_aggregator.main import OCPPipeline
    
    pipeline = OCPPipeline(
        config=self._get_poc_config(),
        logger=LOG,
        postgres_conn=self._get_db_connection()
    )
    
    pipeline.run(
        source_uuid=str(source),
        cluster_id=cluster_id,
        cluster_alias=cluster_alias,
        year=start_date.strftime("%Y"),
        month=start_date.strftime("%m"),
        start_date=str(start_date),
        end_date=str(end_date),
        schema=self.schema,
        report_period_id=report_period_id
    )
```

**For OCP on AWS**:
```python
# File: koku/masu/database/aws_report_db_accessor.py

def populate_ocp_on_aws_cost_daily_summary_trino(self, ...):
    """Populate OCP on AWS summary using Trino or POC."""
    
    if settings.USE_POC_AGGREGATOR:
        return self._populate_using_poc_ocpaws(...)
    else:
        return self._populate_using_trino_ocpaws(...)

def _populate_using_poc_ocpaws(self, start_date, end_date, 
                                openshift_provider_uuid, aws_provider_uuid,
                                report_period_id, bill_id):
    """Use POC for OCP on AWS aggregation."""
    from poc_aggregator.main_ocpaws import OCPAWSPipeline
    
    pipeline = OCPAWSPipeline(
        config=self._get_poc_config(),
        logger=LOG,
        postgres_conn=self._get_db_connection()
    )
    
    pipeline.run(
        aws_source_uuid=str(aws_provider_uuid),
        ocp_source_uuid=str(openshift_provider_uuid),
        year=start_date.strftime("%Y"),
        month=start_date.strftime("%m"),
        start_date=str(start_date),
        end_date=str(end_date),
        schema=self.schema,
        markup=self._get_markup_for_provider(aws_provider_uuid)
    )
```

---

## Summary

### How Koku Knows Which Flow to Use

1. **Provider Type** stored in PostgreSQL `Provider` model
2. **Infrastructure Relationship** links OCP to cloud provider
3. **Task Orchestration** passes provider type to updater
4. **Updater Routes** based on provider type (AWS, Azure, GCP)
5. **DB Accessor Executes** Trino SQL queries

### Where POC Integrates

**Primary Integration Point**: `AWSReportDBAccessor.populate_ocp_on_aws_cost_daily_summary_trino()`

**This method**:
- ❌ Currently executes Trino SQL
- ✅ Will be replaced with POC aggregator call
- ✅ Maintains same interface for callers
- ✅ Writes to same PostgreSQL tables

### Integration Strategy

**Recommended**: **Option 1** (Replace at DB Accessor Level)

**Why**:
- Minimal Koku code changes
- Easy toggle between Trino and POC
- Gradual migration path
- Same interface maintained

### Migration Path

1. **Phase 1**: Parallel deployment (validation)
2. **Phase 2**: Gradual rollout (feature flag)
3. **Phase 3**: Full migration (POC default)
4. **Phase 4**: Trino removal

### Key Takeaway

The POC is a **drop-in replacement** for Trino execution. Koku's decision logic (which provider type to process) remains unchanged. Only the **execution method** changes from Trino SQL to Python/PyArrow.

---

**Document**: KOKU_INTEGRATION_POINTS.md
**Status**: ✅ Complete
**Date**: November 21, 2025
**Next**: Review integration strategy with team

