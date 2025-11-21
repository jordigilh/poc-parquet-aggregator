# Koku → POC Integration Visual Diagram

**Date**: November 21, 2025
**Purpose**: Visual representation of how the POC integrates into Koku

---

## Current Architecture (With Trino)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          KOKU ARCHITECTURE                                │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    1. DATA INGESTION (MASU)                      │    │
│  │                                                                  │    │
│  │  Cloud Providers (AWS, Azure, GCP) + OpenShift Clusters         │    │
│  │           ↓                                                      │    │
│  │  Download Cost/Usage Reports + Metrics                          │    │
│  │           ↓                                                      │    │
│  │  Convert to Parquet                                             │    │
│  │           ↓                                                      │    │
│  │  Upload to S3 (Hive-compatible structure)                       │    │
│  └──────────────────────────┬───────────────────────────────────────┘    │
│                             │                                             │
│  ┌──────────────────────────┴───────────────────────────────────────┐    │
│  │              2. AGGREGATION (MASU) ← TRINO                       │    │
│  │                                                                  │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │  Task Orchestration (processor/tasks.py)                 │   │    │
│  │  │                                                           │   │    │
│  │  │  Provider Type?                                          │   │    │
│  │  │    ├─ OCP Only                                           │   │    │
│  │  │    │   └─> OCPReportParquetSummaryUpdater               │   │    │
│  │  │    │                                                     │   │    │
│  │  │    └─ OCP on Cloud                                      │   │    │
│  │  │        └─> OCPCloudParquetReportSummaryUpdater          │   │    │
│  │  │            ├─ AWS                                        │   │    │
│  │  │            ├─ Azure                                      │   │    │
│  │  │            └─ GCP                                        │   │    │
│  │  └──────────────────────┬───────────────────────────────────┘   │    │
│  │                         │                                        │    │
│  │  ┌──────────────────────┴───────────────────────────────────┐   │    │
│  │  │  DB Accessors                                            │   │    │
│  │  │    ├─ OCPReportDBAccessor                                │   │    │
│  │  │    ├─ AWSReportDBAccessor                                │   │    │
│  │  │    ├─ AzureReportDBAccessor                              │   │    │
│  │  │    └─ GCPReportDBAccessor                                │   │    │
│  │  └──────────────────────┬───────────────────────────────────┘   │    │
│  │                         │                                        │    │
│  │                         ↓                                        │    │
│  │  ┌───────────────────────────────────────────────────────────┐  │    │
│  │  │  TRINO + HIVE METASTORE                                   │  │    │
│  │  │                                                            │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Trino Coordinator                                │    │  │    │
│  │  │  │    ├─ Query Planning                              │    │  │    │
│  │  │  │    ├─ Query Optimization                          │    │  │    │
│  │  │  │    └─ Result Aggregation                          │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  │                         ↓                                 │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Trino Workers (3-5 nodes)                        │    │  │    │
│  │  │  │    ├─ Read Parquet from S3                        │    │  │    │
│  │  │  │    ├─ Execute SQL (JOIN, GROUP BY, AGG)           │    │  │    │
│  │  │  │    └─ Return Results                              │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  │                         ↓                                 │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Hive Metastore                                   │    │  │    │
│  │  │  │    ├─ Table Schemas                               │    │  │    │
│  │  │  │    ├─ Partition Metadata                          │    │  │    │
│  │  │  │    └─ S3 File Locations                           │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  └───────────────────────┬───────────────────────────────────┘  │    │
│  │                          │                                       │    │
│  │                          ↓                                       │    │
│  │  ┌───────────────────────────────────────────────────────────┐  │    │
│  │  │  Write Results to PostgreSQL                              │  │    │
│  │  │    ├─ reporting_ocpusagelineitem_daily_summary_p          │  │    │
│  │  │    ├─ reporting_ocpawscostlineitem_project_daily_summary_p│  │    │
│  │  │    ├─ reporting_ocpaws_cost_summary_p                     │  │    │
│  │  │    └─ ... (20+ summary tables)                            │  │    │
│  │  └───────────────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    3. API LAYER (KOKU)                           │    │
│  │                                                                  │    │
│  │  Django REST Framework                                          │    │
│  │           ↓                                                      │    │
│  │  Query Handlers (OCP, AWS, Azure, GCP)                          │    │
│  │           ↓                                                      │    │
│  │  Read from PostgreSQL Summary Tables                            │    │
│  │           ↓                                                      │    │
│  │  Return JSON to UI                                              │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Future Architecture (With POC)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          KOKU ARCHITECTURE                                │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    1. DATA INGESTION (MASU)                      │    │
│  │                                                                  │    │
│  │  Cloud Providers (AWS, Azure, GCP) + OpenShift Clusters         │    │
│  │           ↓                                                      │    │
│  │  Download Cost/Usage Reports + Metrics                          │    │
│  │           ↓                                                      │    │
│  │  Convert to Parquet                                             │    │
│  │           ↓                                                      │    │
│  │  Upload to S3 (Hive-compatible structure)                       │    │
│  └──────────────────────────┬───────────────────────────────────────┘    │
│                             │                                             │
│  ┌──────────────────────────┴───────────────────────────────────────┐    │
│  │              2. AGGREGATION (MASU) ← POC                         │    │
│  │                                                                  │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │  Task Orchestration (processor/tasks.py)                 │   │    │
│  │  │                                                           │   │    │
│  │  │  Provider Type?                                          │   │    │
│  │  │    ├─ OCP Only                                           │   │    │
│  │  │    │   └─> OCPReportParquetSummaryUpdater               │   │    │
│  │  │    │                                                     │   │    │
│  │  │    └─ OCP on Cloud                                      │   │    │
│  │  │        └─> OCPCloudParquetReportSummaryUpdater          │   │    │
│  │  │            ├─ AWS                                        │   │    │
│  │  │            ├─ Azure                                      │   │    │
│  │  │            └─ GCP                                        │   │    │
│  │  └──────────────────────┬───────────────────────────────────┘   │    │
│  │                         │                                        │    │
│  │  ┌──────────────────────┴───────────────────────────────────┐   │    │
│  │  │  DB Accessors (WITH POC INTEGRATION)                     │   │    │
│  │  │                                                           │   │    │
│  │  │  if USE_POC_AGGREGATOR:                                  │   │    │
│  │  │    ├─ OCPReportDBAccessor → POC OCP Pipeline            │   │    │
│  │  │    ├─ AWSReportDBAccessor → POC OCP-AWS Pipeline        │   │    │
│  │  │    ├─ AzureReportDBAccessor → POC OCP-Azure Pipeline    │   │    │
│  │  │    └─ GCPReportDBAccessor → POC OCP-GCP Pipeline        │   │    │
│  │  │  else:                                                   │   │    │
│  │  │    └─ Use Trino (fallback)                              │   │    │
│  │  └──────────────────────┬───────────────────────────────────┘   │    │
│  │                         │                                        │    │
│  │                         ↓                                        │    │
│  │  ┌───────────────────────────────────────────────────────────┐  │    │
│  │  │  POC PARQUET AGGREGATOR                                   │  │    │
│  │  │                                                            │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Pipeline Router                                  │    │  │    │
│  │  │  │    ├─ OCPPipeline (standalone OCP)                │    │  │    │
│  │  │  │    ├─ OCPAWSPipeline (OCP on AWS)                 │    │  │    │
│  │  │  │    ├─ OCPAzurePipeline (OCP on Azure)             │    │  │    │
│  │  │  │    └─ OCPGCPPipeline (OCP on GCP)                 │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  │                         ↓                                 │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Data Loading                                     │    │  │    │
│  │  │  │    ├─ S3FS (Read Parquet from S3)                 │    │  │    │
│  │  │  │    ├─ PyArrow (Parse Parquet)                     │    │  │    │
│  │  │  │    ├─ Pandas (DataFrames)                         │    │  │    │
│  │  │  │    └─ Streaming/Parallel Reading                  │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  │                         ↓                                 │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Processing (Python/Pandas/PyArrow)               │    │  │    │
│  │  │  │                                                    │    │  │    │
│  │  │  │  For OCP:                                         │    │  │    │
│  │  │  │    ├─ Label Precedence (Pod > NS > Node)         │    │  │    │
│  │  │  │    ├─ Capacity Calculation                        │    │  │    │
│  │  │  │    └─ Aggregation by Cluster/NS/Pod/Node         │    │  │    │
│  │  │  │                                                    │    │  │    │
│  │  │  │  For OCP on AWS:                                  │    │  │    │
│  │  │  │    ├─ Resource Matching (ID + Tags)               │    │  │    │
│  │  │  │    ├─ Cost Attribution                            │    │  │    │
│  │  │  │    ├─ Disk Capacity Calculation                   │    │  │    │
│  │  │  │    └─ Multi-level Aggregation                     │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  │                         ↓                                 │  │    │
│  │  │  ┌──────────────────────────────────────────────────┐    │  │    │
│  │  │  │  Optimizations                                    │    │  │    │
│  │  │  │    ├─ Columnar Filtering                          │    │  │    │
│  │  │  │    ├─ Categorical Types                           │    │  │    │
│  │  │  │    ├─ Memory Management                           │    │  │    │
│  │  │  │    └─ Garbage Collection                          │    │  │    │
│  │  │  └──────────────────────────────────────────────────┘    │  │    │
│  │  └───────────────────────┬───────────────────────────────────┘  │    │
│  │                          │                                       │    │
│  │                          ↓                                       │    │
│  │  ┌───────────────────────────────────────────────────────────┐  │    │
│  │  │  Write Results to PostgreSQL (SAME TABLES)                │  │    │
│  │  │    ├─ reporting_ocpusagelineitem_daily_summary_p          │  │    │
│  │  │    ├─ reporting_ocpawscostlineitem_project_daily_summary_p│  │    │
│  │  │    ├─ reporting_ocpaws_cost_summary_p                     │  │    │
│  │  │    └─ ... (20+ summary tables)                            │  │    │
│  │  └───────────────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    3. API LAYER (KOKU) - NO CHANGE               │    │
│  │                                                                  │    │
│  │  Django REST Framework                                          │    │
│  │           ↓                                                      │    │
│  │  Query Handlers (OCP, AWS, Azure, GCP)                          │    │
│  │           ↓                                                      │    │
│  │  Read from PostgreSQL Summary Tables                            │    │
│  │           ↓                                                      │    │
│  │  Return JSON to UI                                              │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Integration Flow: OCP Standalone

```
┌────────────────────────────────────────────────────────────────────┐
│  KOKU: OCPReportParquetSummaryUpdater.update_daily_tables()       │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  KOKU: OCPReportDBAccessor.populate_line_item_daily_summary_table_│
│        trino(start_date, end_date, report_period_id, ...)         │
│                                                                    │
│  if settings.USE_POC_AGGREGATOR:                                  │
│      return self._populate_using_poc_ocp(...)                     │
│  else:                                                             │
│      return self._populate_using_trino_ocp(...)                   │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: OCPPipeline.run(source_uuid, cluster_id, year, month, ...)  │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: ParquetReader.read_parquet()                                 │
│    ├─ Read: openshift_pod_usage_line_items_daily                  │
│    ├─ Read: openshift_storage_usage_line_items_daily              │
│    └─ Read: openshift_node_labels_line_items_daily                │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: LabelPrecedenceResolver.resolve()                            │
│    └─ Apply Pod > Namespace > Node precedence                     │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: CapacityCalculator.calculate()                               │
│    └─ Calculate node capacity, pod requests/limits                │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: OCPAggregator.aggregate()                                    │
│    └─ Group by cluster, namespace, pod, node                      │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: PostgresWriter.write()                                       │
│    └─ Write to: reporting_ocpusagelineitem_daily_summary_p        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Integration Flow: OCP on AWS

```
┌────────────────────────────────────────────────────────────────────┐
│  KOKU: OCPCloudParquetReportSummaryUpdater.update_aws_summary_    │
│        tables(ocp_uuid, aws_uuid, start_date, end_date)           │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  KOKU: AWSReportDBAccessor.populate_ocp_on_aws_cost_daily_summary_│
│        trino(start_date, end_date, ocp_uuid, aws_uuid, ...)       │
│                                                                    │
│  if settings.USE_POC_AGGREGATOR:                                  │
│      return self._populate_using_poc_ocpaws(...)                  │
│  else:                                                             │
│      return self._populate_using_trino_ocpaws(...)                │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: OCPAWSPipeline.run(aws_uuid, ocp_uuid, year, month, ...)    │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: AWSDataLoader.load()                                         │
│    ├─ Read: aws_line_items_daily (Parquet)                        │
│    ├─ Read: openshift_pod_usage_line_items_daily                  │
│    └─ Read: openshift_node_labels_line_items_daily                │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: ResourceMatcher.match()                                      │
│    ├─ Match by Resource ID (EC2 instance → Node)                  │
│    ├─ Match by Tags (openshift_cluster, openshift_node, ...)      │
│    └─ Handle network direction (in/out)                           │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: CostAttributor.attribute()                                   │
│    ├─ Calculate disk capacity                                     │
│    ├─ Attribute costs to namespaces/pods                          │
│    └─ Apply label precedence                                      │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: OCPAWSAggregator.aggregate()                                 │
│    ├─ Daily summary (by project)                                  │
│    ├─ Cost summary (overall)                                      │
│    ├─ Cost by account                                             │
│    ├─ Cost by service                                             │
│    ├─ Cost by region                                              │
│    ├─ Compute summary                                             │
│    ├─ Storage summary                                             │
│    ├─ Network summary                                             │
│    └─ Database summary                                            │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
                          ↓
┌────────────────────────────────────────────────────────────────────┐
│  POC: PostgresWriter.write()                                       │
│    ├─ Write to: reporting_ocpawscostlineitem_project_daily_summary│
│    ├─ Write to: reporting_ocpaws_cost_summary_p                   │
│    ├─ Write to: reporting_ocpaws_cost_summary_by_account_p        │
│    └─ ... (9 tables total)                                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Key Integration Points Summary

| **Component** | **File** | **Method** | **Action** |
|---------------|----------|------------|------------|
| **OCP Entry** | `ocp_report_parquet_summary_updater.py` | `update_daily_tables()` | Calls DB accessor |
| **OCP DB Accessor** | `ocp_report_db_accessor.py` | `populate_line_item_daily_summary_table_trino()` | **REPLACE with POC call** |
| **OCP on AWS Entry** | `ocp_cloud_parquet_summary_updater.py` | `update_aws_summary_tables()` | Calls DB accessor |
| **AWS DB Accessor** | `aws_report_db_accessor.py` | `populate_ocp_on_aws_cost_daily_summary_trino()` | **REPLACE with POC call** |
| **Azure DB Accessor** | `azure_report_db_accessor.py` | `populate_ocp_on_azure_cost_daily_summary_trino()` | **REPLACE with POC call** |
| **GCP DB Accessor** | `gcp_report_db_accessor.py` | `populate_ocp_on_gcp_cost_daily_summary_trino()` | **REPLACE with POC call** |

---

## Infrastructure Comparison

### Current (Trino + Hive)

```
┌─────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE REQUIREMENTS                                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Trino Coordinator                                   │   │
│  │    - 1 instance                                      │   │
│  │    - 8 GB RAM                                        │   │
│  │    - 4 vCPUs                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Trino Workers                                       │   │
│  │    - 3-5 instances                                   │   │
│  │    - 16 GB RAM each                                  │   │
│  │    - 8 vCPUs each                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Hive Metastore                                      │   │
│  │    - 1 instance                                      │   │
│  │    - 4 GB RAM                                        │   │
│  │    - 2 vCPUs                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Metastore Database (PostgreSQL)                     │   │
│  │    - 1 instance                                      │   │
│  │    - 4 GB RAM                                        │   │
│  │    - 2 vCPUs                                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  TOTAL: 6-8 instances, 60-92 GB RAM, 26-42 vCPUs           │
└─────────────────────────────────────────────────────────────┘
```

### Future (POC)

```
┌─────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE REQUIREMENTS                                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  MASU Workers (existing, no change)                  │   │
│  │    - N instances                                     │   │
│  │    - 4-8 GB RAM each (+ POC overhead)                │   │
│  │    - 2-4 vCPUs each                                  │   │
│  │                                                       │   │
│  │  POC runs as library within MASU workers             │   │
│  │    - No additional instances required                │   │
│  │    - Memory overhead: ~500 MB - 2 GB per task        │   │
│  │    - CPU overhead: same vCPUs                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  TOTAL: 0 additional instances                              │
│  SAVINGS: 6-8 instances, 60-92 GB RAM, 26-42 vCPUs         │
└─────────────────────────────────────────────────────────────┘
```

---

## Migration Timeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: PARALLEL DEPLOYMENT (1-2 months)                          │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ Deploy POC alongside Trino                                      │
│  ├─ Run both for same data                                          │
│  ├─ Compare results                                                 │
│  └─ Build confidence                                                │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: GRADUAL ROLLOUT (2-3 months)                              │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ Enable POC for 10% of customers                                 │
│  ├─ Monitor performance and accuracy                                │
│  ├─ Increase to 25%, 50%, 75%                                       │
│  └─ Trino remains fallback                                          │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 3: FULL MIGRATION (1-2 months)                               │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ POC becomes default                                             │
│  ├─ Trino only for fallback                                         │
│  ├─ Monitor for any issues                                          │
│  └─ Prepare for Trino decommission                                  │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 4: TRINO REMOVAL (1 month)                                   │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ Remove Trino code paths                                         │
│  ├─ Decommission Trino infrastructure                               │
│  ├─ Remove Hive metastore                                           │
│  └─ Cost savings realized                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

**Document**: INTEGRATION_DIAGRAM.md
**Status**: ✅ Complete
**Date**: November 21, 2025
**Next**: Review with team and plan implementation

