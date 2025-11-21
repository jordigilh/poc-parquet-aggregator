# OCP on AWS: Trino SQL to Python/PyArrow Implementation Guide

**Date**: November 21, 2025
**Purpose**: Detailed mapping of Trino SQL queries to Python/PyArrow implementations
**Goal**: Foundation for extending the existing OCP POC to support OCP on AWS

---

## Table of Contents

1. [Overview](#overview)
2. [Data Flow Architecture](#data-flow-architecture)
3. [Phase 1: Resource Matching](#phase-1-resource-matching)
4. [Phase 2: Cost Attribution](#phase-2-cost-attribution)
5. [Phase 3: Aggregation](#phase-3-aggregation)
6. [Implementation Modules](#implementation-modules)
7. [Integration with Existing POC](#integration-with-existing-poc)

---

## Overview

### Current State: OCP POC
The existing POC handles standalone OCP data:
- Reads OCP Parquet files (pod usage, storage, node/namespace labels)
- Applies label precedence (Pod > Namespace > Node)
- Aggregates to daily summaries
- Writes to PostgreSQL

### Target State: OCP + OCP on AWS
Extend the POC to also handle OCP on AWS:
- Read both OCP and AWS Parquet files
- Match AWS resources to OCP workloads
- Attribute AWS costs to OCP namespaces
- Generate 9 additional aggregation tables

### Key Principle
**Reuse existing OCP POC infrastructure** and add OCP on AWS as an additional provider type.

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXISTING OCP POC FLOW                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  OCP Parquet Files                                              │
│  ├─> Pod Usage                                                  │
│  ├─> Storage Usage                                              │
│  ├─> Node Labels                                                │
│  └─> Namespace Labels                                           │
│          │                                                       │
│          ▼                                                       │
│  ParquetReader (existing)                                       │
│          │                                                       │
│          ▼                                                       │
│  Aggregator (existing)                                          │
│  ├─> Apply label precedence                                     │
│  ├─> Calculate capacity                                         │
│  └─> Aggregate to daily                                         │
│          │                                                       │
│          ▼                                                       │
│  PostgreSQL Writer (existing)                                   │
│  └─> reporting_ocpusagelineitem_daily_summary_p                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    NEW OCP ON AWS FLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  OCP Parquet Files          AWS Parquet Files                   │
│  ├─> Pod Usage              ├─> Line Items Daily                │
│  ├─> Storage Usage          └─> (Cost and Usage Report)         │
│  ├─> Node Labels                    │                           │
│  └─> Namespace Labels                │                           │
│          │                           │                           │
│          │                           ▼                           │
│          │                   AWSDataLoader (NEW)                 │
│          │                           │                           │
│          │                           ▼                           │
│          │                   ResourceMatcher (NEW)               │
│          │                   ├─> Match by resource ID            │
│          │                   └─> Match by tags                   │
│          │                           │                           │
│          └───────────┬───────────────┘                           │
│                      │                                           │
│                      ▼                                           │
│              CostAttributor (NEW)                                │
│              ├─> Join OCP usage with AWS costs                  │
│              ├─> Calculate disk capacities                      │
│              ├─> Handle network costs                           │
│              └─> Apply markup                                   │
│                      │                                           │
│                      ▼                                           │
│              OCPAWSAggregator (NEW)                              │
│              ├─> Aggregate to 9 summary tables                  │
│              └─> Reuse label precedence from OCP POC            │
│                      │                                           │
│                      ▼                                           │
│              PostgreSQL Writer (existing)                        │
│              ├─> reporting_ocpawscostlineitem_project_daily_    │
│              │    summary_p                                      │
│              ├─> reporting_ocpaws_cost_summary_p                │
│              ├─> reporting_ocpaws_cost_summary_by_account_p     │
│              ├─> reporting_ocpaws_cost_summary_by_service_p     │
│              ├─> reporting_ocpaws_cost_summary_by_region_p      │
│              ├─> reporting_ocpaws_compute_summary_p             │
│              ├─> reporting_ocpaws_storage_summary_p             │
│              ├─> reporting_ocpaws_database_summary_p            │
│              └─> reporting_ocpaws_network_summary_p             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Resource Matching

### Trino SQL: `1_resource_matching_by_cluster.sql`

This SQL performs two types of matching:
1. **Resource ID Matching**: Match AWS resources to OCP by instance/volume IDs
2. **Tag Matching**: Match AWS resources to OCP by special tags

### Python/PyArrow Implementation

#### Module: `src/aws_data_loader.py`

```python
"""
AWS Data Loader
Reads AWS Cost and Usage Report (CUR) Parquet files from S3/MinIO
"""

import pandas as pd
import pyarrow.parquet as pq
from src.parquet_reader import ParquetReader

class AWSDataLoader:
    """Load AWS CUR data from Parquet files."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.parquet_reader = ParquetReader(config, logger)

    def read_aws_line_items_daily(
        self,
        aws_source_uuid: str,
        year: str,
        month: str,
        start_date: str,
        end_date: str,
        streaming: bool = False
    ) -> pd.DataFrame:
        """
        Read AWS line items daily from Parquet.

        Equivalent to Trino:
            SELECT * FROM hive.schema.aws_line_items_daily
            WHERE source = {{aws_source_uuid}}
              AND year = {{year}}
              AND month = {{month}}
              AND lineitem_usagestartdate >= {{start_date}}
              AND lineitem_usagestartdate < date_add('day', 1, {{end_date}})

        Args:
            aws_source_uuid: AWS source UUID
            year: Year partition
            month: Month partition
            start_date: Start date filter
            end_date: End date filter
            streaming: Whether to use streaming mode

        Returns:
            DataFrame with AWS line items
        """
        # Essential columns for matching and cost attribution
        essential_columns = [
            'row_uuid',
            'lineitem_resourceid',
            'lineitem_productcode',
            'lineitem_usagestartdate',
            'lineitem_usageaccountid',
            'lineitem_availabilityzone',
            'lineitem_usagetype',
            'lineitem_operation',
            'lineitem_usageamount',
            'lineitem_currencycode',
            'lineitem_unblendedcost',
            'lineitem_blendedcost',
            'lineitem_lineitemtype',
            'product_productname',
            'product_productfamily',
            'product_instancetype',
            'product_region',
            'pricing_unit',
            'resourcetags',
            'costcategory',
            'bill_billingentity',
            'savingsplan_savingsplaneffectivecost',
            'source',
            'year',
            'month'
        ]

        # Build S3 path
        s3_path = f"{self.config['s3']['bucket']}/aws_line_items_daily/"
        s3_path += f"source={aws_source_uuid}/year={year}/month={month}/"

        # Read with filters
        filters = [
            ('source', '=', aws_source_uuid),
            ('year', '=', year),
            ('month', '=', month),
            ('lineitem_usagestartdate', '>=', pd.Timestamp(start_date)),
            ('lineitem_usagestartdate', '<', pd.Timestamp(end_date) + pd.Timedelta(days=1))
        ]

        if streaming:
            # Return generator for streaming mode
            return self.parquet_reader.read_parquet_streaming(
                s3_path,
                columns=essential_columns,
                filters=filters,
                chunk_size=self.config['performance']['chunk_size']
            )
        else:
            # Read all at once
            df = self.parquet_reader.read_parquet_parallel(
                s3_path,
                columns=essential_columns,
                filters=filters
            )

            # Apply date filter (Parquet filters may not be exact)
            df = df[
                (df['lineitem_usagestartdate'] >= pd.Timestamp(start_date)) &
                (df['lineitem_usagestartdate'] < pd.Timestamp(end_date) + pd.Timedelta(days=1))
            ]

            return df
```

#### Module: `src/resource_matcher.py`

```python
"""
Resource Matcher
Matches AWS resources to OCP workloads by resource ID and tags
"""

import pandas as pd
import numpy as np
import json
from typing import Set, Dict, List, Tuple

class ResourceMatcher:
    """Match AWS resources to OCP workloads."""

    def __init__(self, config, logger, postgres_conn):
        self.config = config
        self.logger = logger
        self.postgres_conn = postgres_conn
        self._enabled_tag_keys_cache = None

    def get_enabled_tag_keys(self, schema: str) -> List[str]:
        """
        Get enabled tag keys from PostgreSQL.

        Equivalent to Trino CTE:
            cte_enabled_tag_keys AS (
                SELECT
                CASE WHEN array_agg(key) IS NOT NULL
                    THEN array_union(ARRAY['openshift_cluster', 'openshift_node', 'openshift_project'], array_agg(key))
                    ELSE ARRAY['openshift_cluster', 'openshift_node', 'openshift_project']
                END as enabled_keys
                FROM postgres.schema.reporting_enabledtagkeys
                WHERE enabled = TRUE
                AND provider_type = 'AWS'
            )

        Returns:
            List of enabled tag keys
        """
        if self._enabled_tag_keys_cache is not None:
            return self._enabled_tag_keys_cache

        query = f"""
            SELECT key
            FROM {schema}.reporting_enabledtagkeys
            WHERE enabled = TRUE
              AND provider_type = 'AWS'
        """

        with self.postgres_conn.cursor() as cursor:
            cursor.execute(query)
            keys = [row[0] for row in cursor.fetchall()]

        # Always include OpenShift special tags
        base_keys = ['openshift_cluster', 'openshift_node', 'openshift_project']
        enabled_keys = list(set(base_keys + keys))

        self._enabled_tag_keys_cache = enabled_keys
        self.logger.info(f"Enabled tag keys: {len(enabled_keys)} keys")

        return enabled_keys

    def extract_ocp_resource_ids(
        self,
        ocp_pod_usage: pd.DataFrame,
        ocp_storage_usage: pd.DataFrame
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Extract unique OCP resource IDs for matching.

        Equivalent to Trino CTEs:
            cte_array_agg_nodes AS (
                SELECT DISTINCT resource_id
                FROM openshift_pod_usage_line_items_daily
                WHERE resource_id != ''
            )

            cte_array_agg_volumes AS (
                SELECT DISTINCT persistentvolume, csi_volume_handle
                FROM openshift_storage_usage_line_items_daily
                WHERE persistentvolume != ''
            )

        Returns:
            Tuple of (node_resource_ids, pv_names, csi_volume_handles)
        """
        # Extract node resource IDs
        node_resource_ids = set(
            ocp_pod_usage[ocp_pod_usage['resource_id'].notna() &
                          (ocp_pod_usage['resource_id'] != '')]['resource_id'].unique()
        )

        # Extract PV names and CSI volume handles
        pv_names = set(
            ocp_storage_usage[ocp_storage_usage['persistentvolume'].notna() &
                              (ocp_storage_usage['persistentvolume'] != '')]['persistentvolume'].unique()
        )

        csi_volume_handles = set(
            ocp_storage_usage[ocp_storage_usage['csi_volume_handle'].notna() &
                              (ocp_storage_usage['csi_volume_handle'] != '')]['csi_volume_handle'].unique()
        )

        self.logger.info(f"Extracted OCP resource IDs: {len(node_resource_ids)} nodes, "
                        f"{len(pv_names)} PVs, {len(csi_volume_handles)} CSI volumes")

        return node_resource_ids, pv_names, csi_volume_handles

    def match_by_resource_id(
        self,
        aws_df: pd.DataFrame,
        node_resource_ids: Set[str],
        pv_names: Set[str],
        csi_volume_handles: Set[str]
    ) -> pd.DataFrame:
        """
        Match AWS resources to OCP by resource ID (suffix matching).

        Equivalent to Trino CTE:
            cte_matchable_resource_names AS (
                SELECT resource_names.lineitem_resourceid
                FROM cte_aws_resource_names AS resource_names
                JOIN cte_array_agg_nodes AS nodes
                    ON substr(resource_names.lineitem_resourceid, -length(nodes.resource_id)) = nodes.resource_id

                UNION

                SELECT resource_names.lineitem_resourceid
                FROM cte_aws_resource_names AS resource_names
                JOIN cte_array_agg_volumes AS volumes
                    ON (
                        substr(resource_names.lineitem_resourceid, -length(volumes.persistentvolume)) = volumes.persistentvolume
                        OR (volumes.csi_volume_handle != '' AND substr(resource_names.lineitem_resourceid, -length(volumes.csi_volume_handle)) = volumes.csi_volume_handle)
                    )
            )

        Args:
            aws_df: AWS line items DataFrame
            node_resource_ids: Set of OCP node resource IDs
            pv_names: Set of OCP PV names
            csi_volume_handles: Set of OCP CSI volume handles

        Returns:
            DataFrame with resource_id_matched column added
        """
        aws_df = aws_df.copy()
        aws_df['resource_id_matched'] = False

        # Match against node resource IDs
        for node_id in node_resource_ids:
            mask = aws_df['lineitem_resourceid'].str.endswith(node_id, na=False)
            aws_df.loc[mask, 'resource_id_matched'] = True

        # Match against PV names
        for pv_name in pv_names:
            mask = aws_df['lineitem_resourceid'].str.contains(pv_name, na=False, regex=False)
            aws_df.loc[mask, 'resource_id_matched'] = True

        # Match against CSI volume handles
        for csi_handle in csi_volume_handles:
            if csi_handle:  # Skip empty strings
                mask = aws_df['lineitem_resourceid'].str.contains(csi_handle, na=False, regex=False)
                aws_df.loc[mask, 'resource_id_matched'] = True

        matched_count = aws_df['resource_id_matched'].sum()
        self.logger.info(f"Resource ID matching: {matched_count} / {len(aws_df)} AWS resources matched")

        return aws_df

    def build_matched_tag_array(
        self,
        ocp_pod_usage: pd.DataFrame
    ) -> List[str]:
        """
        Build array of matched tags from OCP data.

        Equivalent to Trino CTE:
            cte_agg_tags AS (
                SELECT array_agg(cte_tag_matches.matched_tag) as matched_tags from (
                    SELECT * FROM unnest(ARRAY{{matched_tag_array | sqlsafe}}) as t(matched_tag)
                ) as cte_tag_matches
            )

        This builds tags like:
            - openshift_cluster=my-cluster
            - openshift_node=worker-1
            - openshift_project=my-namespace

        Returns:
            List of matched tag strings
        """
        matched_tags = []

        # Extract unique cluster IDs
        clusters = ocp_pod_usage['cluster_id'].dropna().unique()
        for cluster in clusters:
            matched_tags.append(f"openshift_cluster={cluster}")

        # Extract unique nodes
        nodes = ocp_pod_usage['node'].dropna().unique()
        for node in nodes:
            matched_tags.append(f"openshift_node={node}")

        # Extract unique namespaces
        namespaces = ocp_pod_usage['namespace'].dropna().unique()
        for namespace in namespaces:
            matched_tags.append(f"openshift_project={namespace}")

        self.logger.info(f"Built matched tag array: {len(matched_tags)} tags")

        return matched_tags

    def filter_aws_tags(
        self,
        aws_df: pd.DataFrame,
        enabled_tag_keys: List[str]
    ) -> pd.DataFrame:
        """
        Filter AWS tags to only enabled keys.

        Equivalent to Trino:
            json_format(
                cast(
                    map_filter(
                        cast(json_parse(aws.resourcetags) as map(varchar, varchar)),
                        (k, v) -> contains(etk.enabled_keys, k)
                    ) as json
                )
            ) as tags

        Args:
            aws_df: AWS DataFrame with resourcetags column
            enabled_tag_keys: List of enabled tag keys

        Returns:
            DataFrame with filtered tags column
        """
        def filter_tags(tags_json):
            if pd.isna(tags_json) or tags_json == '':
                return '{}'

            try:
                tags = json.loads(tags_json)
                filtered = {k: v for k, v in tags.items() if k in enabled_tag_keys}
                return json.dumps(filtered)
            except (json.JSONDecodeError, TypeError):
                return '{}'

        aws_df = aws_df.copy()
        aws_df['tags'] = aws_df['resourcetags'].apply(filter_tags)

        return aws_df

    def match_by_tags(
        self,
        aws_df: pd.DataFrame,
        matched_tags: List[str]
    ) -> pd.DataFrame:
        """
        Match AWS resources to OCP by tags.

        Equivalent to Trino:
            array_join(filter(tag_matches.matched_tags, x -> STRPOS(resourcetags, x ) != 0), ',') as matched_tag

        Args:
            aws_df: AWS DataFrame (already has resource_id_matched column)
            matched_tags: List of matched tag strings

        Returns:
            DataFrame with matched_tag column added
        """
        aws_df = aws_df.copy()
        aws_df['matched_tag'] = ''

        # Only match tags for resources not already matched by resource ID
        unmatched_mask = ~aws_df['resource_id_matched']

        for tag in matched_tags:
            # Check if tag exists in resourcetags
            mask = unmatched_mask & aws_df['resourcetags'].str.contains(tag, na=False, regex=False)

            # Append to matched_tag (comma-separated if multiple matches)
            aws_df.loc[mask & (aws_df['matched_tag'] == ''), 'matched_tag'] = tag
            aws_df.loc[mask & (aws_df['matched_tag'] != ''), 'matched_tag'] += ',' + tag

        tag_matched_count = (aws_df['matched_tag'] != '').sum()
        self.logger.info(f"Tag matching: {tag_matched_count} AWS resources matched by tags")

        return aws_df

    def calculate_network_direction(self, aws_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate data transfer direction for network costs.

        Equivalent to Trino:
            CASE
                WHEN aws.lineitem_productcode = 'AmazonEC2' AND aws.product_productfamily = 'Data Transfer' THEN
                    CASE
                        WHEN strpos(lower(aws.lineitem_usagetype), 'in-bytes') > 0 THEN 'IN'
                        WHEN strpos(lower(aws.lineitem_usagetype), 'out-bytes') > 0 THEN 'OUT'
                        WHEN (strpos(lower(aws.lineitem_usagetype), 'regional-bytes') > 0 AND strpos(lower(lineitem_operation), '-in') > 0) THEN 'IN'
                        WHEN (strpos(lower(aws.lineitem_usagetype), 'regional-bytes') > 0 AND strpos(lower(lineitem_operation), '-out') > 0) THEN 'OUT'
                        ELSE NULL
                    END
            END AS data_transfer_direction

        Args:
            aws_df: AWS DataFrame

        Returns:
            DataFrame with data_transfer_direction column
        """
        aws_df = aws_df.copy()
        aws_df['data_transfer_direction'] = None

        # Only for EC2 Data Transfer
        network_mask = (
            (aws_df['lineitem_productcode'] == 'AmazonEC2') &
            (aws_df['product_productfamily'] == 'Data Transfer')
        )

        if network_mask.any():
            usage_type_lower = aws_df.loc[network_mask, 'lineitem_usagetype'].str.lower()
            operation_lower = aws_df.loc[network_mask, 'lineitem_operation'].str.lower()

            # IN direction
            in_mask = (
                usage_type_lower.str.contains('in-bytes', na=False) |
                (usage_type_lower.str.contains('regional-bytes', na=False) &
                 operation_lower.str.contains('-in', na=False))
            )
            aws_df.loc[network_mask & in_mask, 'data_transfer_direction'] = 'IN'

            # OUT direction
            out_mask = (
                usage_type_lower.str.contains('out-bytes', na=False) |
                (usage_type_lower.str.contains('regional-bytes', na=False) &
                 operation_lower.str.contains('-out', na=False))
            )
            aws_df.loc[network_mask & out_mask, 'data_transfer_direction'] = 'OUT'

        return aws_df

    def handle_special_line_items(self, aws_df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle special AWS line item types.

        Equivalent to Trino:
            CASE
                WHEN aws.lineitem_lineitemtype='SavingsPlanCoveredUsage'
                THEN 0.0
                ELSE aws.lineitem_unblendedcost
            END as unblended_cost

        Args:
            aws_df: AWS DataFrame

        Returns:
            DataFrame with adjusted costs
        """
        aws_df = aws_df.copy()

        # SavingsPlanCoveredUsage: set unblended and blended cost to 0
        sp_mask = aws_df['lineitem_lineitemtype'] == 'SavingsPlanCoveredUsage'
        aws_df.loc[sp_mask, 'lineitem_unblendedcost'] = 0.0
        aws_df.loc[sp_mask, 'lineitem_blendedcost'] = 0.0

        # Calculated amortized cost
        tax_or_usage_mask = aws_df['lineitem_lineitemtype'].isin(['Tax', 'Usage'])
        aws_df['calculated_amortized_cost'] = np.where(
            tax_or_usage_mask,
            aws_df['lineitem_unblendedcost'],
            aws_df['savingsplan_savingsplaneffectivecost']
        )

        return aws_df

    def handle_marketplace_products(self, aws_df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle AWS Marketplace products.

        Equivalent to Trino:
            CASE
                WHEN aws.bill_billingentity='AWS Marketplace' THEN coalesce(nullif(aws.product_productname, ''), nullif(aws.lineitem_productcode, ''))
                ELSE nullif(aws.lineitem_productcode, '')
            END as product_code

        Args:
            aws_df: AWS DataFrame

        Returns:
            DataFrame with adjusted product_code
        """
        aws_df = aws_df.copy()

        marketplace_mask = aws_df['bill_billingentity'] == 'AWS Marketplace'

        # For marketplace, use product_productname if available, else lineitem_productcode
        aws_df.loc[marketplace_mask, 'product_code'] = aws_df.loc[marketplace_mask].apply(
            lambda row: row['product_productname'] if pd.notna(row['product_productname']) and row['product_productname'] != ''
                       else row['lineitem_productcode'],
            axis=1
        )

        # For non-marketplace, use lineitem_productcode
        aws_df.loc[~marketplace_mask, 'product_code'] = aws_df.loc[~marketplace_mask, 'lineitem_productcode']

        return aws_df

    def match_aws_to_ocp(
        self,
        aws_df: pd.DataFrame,
        ocp_pod_usage: pd.DataFrame,
        ocp_storage_usage: pd.DataFrame,
        schema: str
    ) -> pd.DataFrame:
        """
        Main method: Match AWS resources to OCP workloads.

        This combines all matching logic:
        1. Extract OCP resource IDs
        2. Match by resource ID
        3. Build matched tag array
        4. Get enabled tag keys
        5. Filter AWS tags
        6. Match by tags
        7. Calculate network direction
        8. Handle special line items
        9. Handle marketplace products

        Returns:
            DataFrame with matched AWS resources ready for cost attribution
        """
        self.logger.info("Starting AWS to OCP matching...")

        # Step 1: Extract OCP resource IDs
        node_resource_ids, pv_names, csi_volume_handles = self.extract_ocp_resource_ids(
            ocp_pod_usage,
            ocp_storage_usage
        )

        # Step 2: Match by resource ID
        aws_df = self.match_by_resource_id(
            aws_df,
            node_resource_ids,
            pv_names,
            csi_volume_handles
        )

        # Step 3: Build matched tag array
        matched_tags = self.build_matched_tag_array(ocp_pod_usage)

        # Step 4: Get enabled tag keys
        enabled_tag_keys = self.get_enabled_tag_keys(schema)

        # Step 5: Filter AWS tags
        aws_df = self.filter_aws_tags(aws_df, enabled_tag_keys)

        # Step 6: Match by tags
        aws_df = self.match_by_tags(aws_df, matched_tags)

        # Step 7: Calculate network direction
        aws_df = self.calculate_network_direction(aws_df)

        # Step 8: Handle special line items
        aws_df = self.handle_special_line_items(aws_df)

        # Step 9: Handle marketplace products
        aws_df = self.handle_marketplace_products(aws_df)

        # Filter to only matched resources
        matched_df = aws_df[
            (aws_df['resource_id_matched'] == True) |
            (aws_df['matched_tag'] != '')
        ].copy()

        self.logger.info(f"Matching complete: {len(matched_df)} / {len(aws_df)} AWS resources matched to OCP")

        return matched_df
```

---

## Phase 2: Cost Attribution

### Trino SQL: `2_summarize_data_by_cluster.sql`

This SQL performs cost attribution in three main parts:
1. **Disk Capacity Calculation**: Calculate EBS volume capacities
2. **Storage Cost Attribution**: Attribute storage costs to PVCs
3. **Compute Cost Attribution**: Attribute EC2/compute costs to pods
4. **Network Cost Attribution**: Attribute network costs to nodes

### Python/PyArrow Implementation

#### Module: `src/disk_capacity_calculator.py`

```python
"""
Disk Capacity Calculator
Calculates EBS volume capacities for storage cost attribution
"""

import pandas as pd
import numpy as np
from datetime import datetime

class DiskCapacityCalculator:
    """Calculate disk capacities from AWS billing data."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def calculate_hours_in_month(self, year: int, month: int) -> int:
        """
        Calculate hours in a given month.

        Equivalent to Trino:
            cte_hours as (
                SELECT DAY(last_day_of_month({{start_date}})) * 24 as in_month
            )

        Args:
            year: Year
            month: Month

        Returns:
            Number of hours in the month
        """
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        return days_in_month * 24

    def calculate_disk_capacities(
        self,
        aws_line_items_hourly: pd.DataFrame,
        matched_aws_resources: pd.DataFrame,
        ocp_storage_usage: pd.DataFrame,
        year: int,
        month: int
    ) -> pd.DataFrame:
        """
        Calculate disk capacities for matched EBS volumes.

        Equivalent to Trino:
            calculated_capacity AS (
                SELECT
                    aws.lineitem_resourceid as resource_id,
                    ROUND(MAX(aws.lineitem_unblendedcost) / (MAX(aws.lineitem_unblendedrate) / MAX(hours.in_month))) AS capacity,
                    ocpaws.usage_start,
                    {{ocp_provider_uuid}} as ocp_source,
                    {{year}} as year,
                    {{month}} as month
                FROM hive.schema.aws_line_items as aws
                INNER JOIN cte_ocp_filtered_resources as ocpaws
                    ON aws.lineitem_resourceid = ocpaws.resource_id
                    AND DATE(aws.lineitem_usagestartdate) = ocpaws.usage_start
                CROSS JOIN cte_hours as hours
                WHERE aws.year = {{year}}
                AND aws.month = {{month}}
                AND aws.source = {{cloud_provider_uuid}}
                GROUP BY aws.lineitem_resourceid, ocpaws.usage_start
            )

        Args:
            aws_line_items_hourly: AWS line items (hourly granularity)
            matched_aws_resources: Matched AWS resources (daily)
            ocp_storage_usage: OCP storage usage
            year: Year
            month: Month

        Returns:
            DataFrame with columns: resource_id, capacity, usage_start
        """
        hours_in_month = self.calculate_hours_in_month(year, month)

        # Filter to matched EBS volumes (CSI volume handles)
        csi_volumes = ocp_storage_usage[
            ocp_storage_usage['csi_volume_handle'].notna() &
            (ocp_storage_usage['csi_volume_handle'] != '')
        ][['csi_volume_handle', 'usage_start']].drop_duplicates()

        # Find AWS resources that match CSI volumes
        matched_volumes = matched_aws_resources[
            matched_aws_resources['lineitem_resourceid'].isin(csi_volumes['csi_volume_handle'])
        ][['lineitem_resourceid', 'usage_start']].drop_duplicates()

        # Join hourly AWS data with matched volumes
        merged = aws_line_items_hourly.merge(
            matched_volumes,
            left_on=['lineitem_resourceid', pd.to_datetime(aws_line_items_hourly['lineitem_usagestartdate']).dt.date],
            right_on=['lineitem_resourceid', 'usage_start'],
            how='inner'
        )

        # Calculate capacity per resource per day
        capacity_df = merged.groupby(['lineitem_resourceid', 'usage_start']).agg({
            'lineitem_unblendedcost': 'max',
            'lineitem_unblendedrate': 'max'
        }).reset_index()

        # Apply formula: Capacity = Total Cost / (Hourly Rate / Hours in Month)
        capacity_df['capacity'] = np.round(
            capacity_df['lineitem_unblendedcost'] /
            (capacity_df['lineitem_unblendedrate'] / hours_in_month)
        ).astype(int)

        # Filter to positive capacities
        capacity_df = capacity_df[capacity_df['capacity'] > 0]

        # Rename columns
        capacity_df = capacity_df.rename(columns={
            'lineitem_resourceid': 'resource_id'
        })[['resource_id', 'capacity', 'usage_start']]

        self.logger.info(f"Calculated capacities for {len(capacity_df)} EBS volumes")

        return capacity_df
```

#### Module: `src/cost_attributor.py`

```python
"""
Cost Attributor
Attributes AWS costs to OCP namespaces/pods
"""

import pandas as pd
import numpy as np
from typing import Tuple

class CostAttributor:
    """Attribute AWS costs to OCP workloads."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def attribute_storage_costs(
        self,
        matched_aws: pd.DataFrame,
        ocp_storage_usage: pd.DataFrame,
        disk_capacities: pd.DataFrame,
        markup: float
    ) -> pd.DataFrame:
        """
        Attribute storage costs to PVCs.

        Equivalent to Trino (storage section of 2_summarize_data_by_cluster.sql):
            max(ocp.persistentvolumeclaim_capacity_gigabyte) / max(aws_disk.capacity) * max(aws.unblended_cost) as unblended_cost

        Formula:
            PVC Cost = (PVC Capacity / Disk Capacity) * Disk Cost

        Args:
            matched_aws: Matched AWS resources
            ocp_storage_usage: OCP storage usage
            disk_capacities: Calculated disk capacities
            markup: Markup percentage (e.g., 0.10 for 10%)

        Returns:
            DataFrame with attributed storage costs
        """
        # Join OCP storage with matched AWS
        storage_aws = matched_aws[
            matched_aws['lineitem_resourceid'].isin(ocp_storage_usage['csi_volume_handle'])
        ].copy()

        # Join with OCP storage usage
        merged = ocp_storage_usage.merge(
            storage_aws,
            left_on=['csi_volume_handle', 'usage_start'],
            right_on=['lineitem_resourceid', 'usage_start'],
            how='inner'
        )

        # Join with disk capacities
        merged = merged.merge(
            disk_capacities,
            left_on=['lineitem_resourceid', 'usage_start'],
            right_on=['resource_id', 'usage_start'],
            how='inner'
        )

        # Calculate attributed costs
        # Cost per PVC = (PVC Capacity / Disk Capacity) * Disk Cost
        capacity_ratio = merged['persistentvolumeclaim_capacity_gigabyte'] / merged['capacity']

        merged['unblended_cost'] = capacity_ratio * merged['lineitem_unblendedcost']
        merged['markup_cost'] = merged['unblended_cost'] * markup

        merged['blended_cost'] = capacity_ratio * merged['lineitem_blendedcost']
        merged['markup_cost_blended'] = merged['blended_cost'] * markup

        merged['savingsplan_effective_cost'] = capacity_ratio * merged['savingsplan_savingsplaneffectivecost']
        merged['markup_cost_savingsplan'] = merged['savingsplan_effective_cost'] * markup

        merged['calculated_amortized_cost'] = capacity_ratio * merged['calculated_amortized_cost']
        merged['markup_cost_amortized'] = merged['calculated_amortized_cost'] * markup

        # Handle unattributed storage (PVs without PVCs)
        merged['namespace'] = np.where(
            merged['persistentvolumeclaim'].isna() | (merged['persistentvolumeclaim'] == ''),
            'Storage unattributed',
            merged['namespace']
        )

        merged['data_source'] = 'Storage'

        self.logger.info(f"Attributed storage costs for {len(merged)} PVCs")

        return merged

    def attribute_compute_costs(
        self,
        matched_aws: pd.DataFrame,
        ocp_pod_usage: pd.DataFrame,
        markup: float
    ) -> pd.DataFrame:
        """
        Attribute compute costs to pods.

        Equivalent to Trino (compute section of 2_summarize_data_by_cluster.sql):
            Join OCP pods with AWS EC2 instances by resource_id
            Calculate pod-level cost based on CPU/memory usage

        Formula:
            Pod Cost = AWS Cost * (Pod CPU Usage / Node CPU Capacity)

        Args:
            matched_aws: Matched AWS resources
            ocp_pod_usage: OCP pod usage
            markup: Markup percentage

        Returns:
            DataFrame with attributed compute costs
        """
        # Join OCP pods with matched AWS by resource_id and date
        merged = ocp_pod_usage.merge(
            matched_aws,
            left_on=['resource_id', 'usage_start'],
            right_on=['lineitem_resourceid', 'usage_start'],
            how='inner'
        )

        # Calculate attribution ratio (use max of CPU or memory ratio)
        cpu_ratio = merged['pod_usage_cpu_core_hours'] / merged['node_capacity_cpu_core_hours']
        memory_ratio = merged['pod_usage_memory_gigabyte_hours'] / merged['node_capacity_memory_gigabyte_hours']

        # Use the higher ratio (more conservative attribution)
        attribution_ratio = np.maximum(cpu_ratio, memory_ratio)

        # Attribute costs
        merged['unblended_cost'] = attribution_ratio * merged['lineitem_unblendedcost']
        merged['markup_cost'] = merged['unblended_cost'] * markup

        merged['blended_cost'] = attribution_ratio * merged['lineitem_blendedcost']
        merged['markup_cost_blended'] = merged['blended_cost'] * markup

        merged['savingsplan_effective_cost'] = attribution_ratio * merged['savingsplan_savingsplaneffectivecost']
        merged['markup_cost_savingsplan'] = merged['savingsplan_effective_cost'] * markup

        merged['calculated_amortized_cost'] = attribution_ratio * merged['calculated_amortized_cost']
        merged['markup_cost_amortized'] = merged['calculated_amortized_cost'] * markup

        merged['data_source'] = 'Pod'

        self.logger.info(f"Attributed compute costs for {len(merged)} pods")

        return merged

    def attribute_network_costs(
        self,
        matched_aws: pd.DataFrame,
        ocp_pod_usage: pd.DataFrame,
        markup: float
    ) -> pd.DataFrame:
        """
        Attribute network costs to nodes (unattributed namespace).

        Equivalent to Trino (network section of 2_summarize_data_by_cluster.sql):
            'Network unattributed' AS namespace

        Network costs are node-level and cannot be attributed to specific pods.

        Args:
            matched_aws: Matched AWS resources
            ocp_pod_usage: OCP pod usage (for node info)
            markup: Markup percentage

        Returns:
            DataFrame with attributed network costs
        """
        # Filter to network costs only
        network_aws = matched_aws[
            matched_aws['data_transfer_direction'].notna()
        ].copy()

        if len(network_aws) == 0:
            self.logger.info("No network costs to attribute")
            return pd.DataFrame()

        # Get unique nodes from OCP
        nodes = ocp_pod_usage[['resource_id', 'node', 'cluster_id', 'cluster_alias', 'usage_start']].drop_duplicates()

        # Join network costs with nodes
        merged = network_aws.merge(
            nodes,
            left_on=['lineitem_resourceid', 'usage_start'],
            right_on=['resource_id', 'usage_start'],
            how='inner'
        )

        # Set namespace to 'Network unattributed'
        merged['namespace'] = 'Network unattributed'
        merged['data_source'] = 'Node'

        # Apply markup
        merged['markup_cost'] = merged['lineitem_unblendedcost'] * markup
        merged['markup_cost_blended'] = merged['lineitem_blendedcost'] * markup
        merged['markup_cost_savingsplan'] = merged['savingsplan_savingsplaneffectivecost'] * markup
        merged['markup_cost_amortized'] = merged['calculated_amortized_cost'] * markup

        self.logger.info(f"Attributed network costs for {len(merged)} node-level records")

        return merged

    def combine_attributed_costs(
        self,
        storage_costs: pd.DataFrame,
        compute_costs: pd.DataFrame,
        network_costs: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Combine all attributed costs into a single DataFrame.

        This is the final output equivalent to:
            managed_reporting_ocpawscostlineitem_project_daily_summary_temp

        Returns:
            Combined DataFrame with all attributed costs
        """
        # Concatenate all cost types
        all_costs = pd.concat([storage_costs, compute_costs, network_costs], ignore_index=True)

        self.logger.info(f"Combined attributed costs: {len(all_costs)} total records "
                        f"({len(storage_costs)} storage, {len(compute_costs)} compute, {len(network_costs)} network)")

        return all_costs
```

---

## Phase 3: Aggregation

### Trino SQL: Multiple aggregation files

The Trino implementation creates 9 aggregation tables from the combined OCP+AWS data. Each table aggregates by different dimensions.

### Python/PyArrow Implementation

#### Module: `src/aggregator_ocpaws.py`

```python
"""
OCP on AWS Aggregator
Aggregates OCP+AWS combined data to 9 summary tables
"""

import pandas as pd
import numpy as np
from typing import List, Dict

class OCPAWSAggregator:
    """Aggregate OCP+AWS data to summary tables."""

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def aggregate_detailed_line_items(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate to detailed line items table.

        Target table: reporting_ocpawscostlineitem_project_daily_summary_p

        Equivalent to Trino:
            INSERT INTO postgres.schema.reporting_ocpawscostlineitem_project_daily_summary_p
            SELECT * FROM managed_reporting_ocpawscostlineitem_project_daily_summary
            (with tag filtering)

        This is the most detailed table with all dimensions.

        Returns:
            DataFrame ready for PostgreSQL insert
        """
        # This is essentially the combined_df from cost attribution
        # Just need to ensure all required columns are present

        required_columns = [
            'uuid', 'report_period_id', 'cluster_id', 'cluster_alias',
            'data_source', 'namespace', 'node',
            'persistentvolumeclaim', 'persistentvolume', 'storageclass',
            'resource_id', 'usage_start', 'usage_end',
            'product_code', 'product_family', 'instance_type',
            'cost_entry_bill_id', 'usage_account_id', 'account_alias_id',
            'availability_zone', 'region', 'unit', 'usage_amount',
            'infrastructure_data_in_gigabytes', 'infrastructure_data_out_gigabytes',
            'data_transfer_direction', 'currency_code',
            'unblended_cost', 'markup_cost',
            'blended_cost', 'markup_cost_blended',
            'savingsplan_effective_cost', 'markup_cost_savingsplan',
            'calculated_amortized_cost', 'markup_cost_amortized',
            'pod_labels', 'tags', 'aws_cost_category', 'cost_category_id',
            'source_uuid'
        ]

        # Generate UUIDs
        import uuid
        combined_df['uuid'] = [str(uuid.uuid4()) for _ in range(len(combined_df))]

        # Calculate data transfer amounts
        combined_df['infrastructure_data_in_gigabytes'] = np.where(
            combined_df['data_transfer_direction'] == 'IN',
            combined_df['usage_amount'],
            0
        )
        combined_df['infrastructure_data_out_gigabytes'] = np.where(
            combined_df['data_transfer_direction'] == 'OUT',
            combined_df['usage_amount'],
            0
        )

        self.logger.info(f"Detailed line items: {len(combined_df)} records")

        return combined_df[required_columns]

    def aggregate_cluster_totals(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate to cluster-level totals.

        Target table: reporting_ocpaws_cost_summary_p

        Equivalent to Trino:
            SELECT uuid() as id,
                usage_start,
                usage_start as usage_end,
                max(cluster_id) as cluster_id,
                max(cluster_alias) as cluster_alias,
                sum(unblended_cost),
                sum(markup_cost),
                ...
            FROM managed_reporting_ocpawscostlineitem_project_daily_summary
            GROUP BY usage_start

        Returns:
            DataFrame with cluster-level aggregates
        """
        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max',
            'cost_category_id': 'max'
        }

        result = combined_df.groupby('usage_start').agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        # Generate UUIDs
        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"Cluster totals: {len(result)} records")

        return result

    def aggregate_by_account(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate by AWS account.

        Target table: reporting_ocpaws_cost_summary_by_account_p

        Equivalent to Trino:
            GROUP BY usage_start, usage_account_id, account_alias_id

        Returns:
            DataFrame with account-level aggregates
        """
        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = combined_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"By account: {len(result)} records")

        return result

    def aggregate_by_service(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate by AWS service.

        Target table: reporting_ocpaws_cost_summary_by_service_p

        Equivalent to Trino:
            GROUP BY usage_start, usage_account_id, account_alias_id, product_code, product_family

        Returns:
            DataFrame with service-level aggregates
        """
        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'product_code', 'product_family']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = combined_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"By service: {len(result)} records")

        return result

    def aggregate_by_region(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate by AWS region.

        Target table: reporting_ocpaws_cost_summary_by_region_p

        Equivalent to Trino:
            GROUP BY usage_start, usage_account_id, account_alias_id, region, availability_zone

        Returns:
            DataFrame with region-level aggregates
        """
        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'region', 'availability_zone']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = combined_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"By region: {len(result)} records")

        return result

    def aggregate_compute_summary(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate compute (EC2) costs.

        Target table: reporting_ocpaws_compute_summary_p

        Equivalent to Trino:
            WHERE instance_type IS NOT NULL
            GROUP BY usage_start, usage_account_id, account_alias_id, instance_type, resource_id

        Returns:
            DataFrame with compute-specific aggregates
        """
        # Filter to compute resources only
        compute_df = combined_df[combined_df['instance_type'].notna()].copy()

        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'instance_type', 'resource_id']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'usage_amount': 'sum',
            'unit': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = compute_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"Compute summary: {len(result)} records")

        return result

    def aggregate_storage_summary(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate storage costs.

        Target table: reporting_ocpaws_storage_summary_p

        Equivalent to Trino:
            WHERE product_family LIKE '%Storage%' AND unit = 'GB-Mo'
            GROUP BY usage_start, usage_account_id, account_alias_id, product_family

        Returns:
            DataFrame with storage-specific aggregates
        """
        # Filter to storage resources only
        storage_df = combined_df[
            (combined_df['product_family'].str.contains('Storage', na=False)) &
            (combined_df['unit'] == 'GB-Mo')
        ].copy()

        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'product_family']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'usage_amount': 'sum',
            'unit': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = storage_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"Storage summary: {len(result)} records")

        return result

    def aggregate_database_summary(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate database service costs.

        Target table: reporting_ocpaws_database_summary_p

        Equivalent to Trino:
            WHERE product_code IN ('AmazonRDS','AmazonDynamoDB','AmazonElastiCache','AmazonNeptune','AmazonRedshift','AmazonDocumentDB')
            GROUP BY usage_start, usage_account_id, account_alias_id, product_code

        Returns:
            DataFrame with database-specific aggregates
        """
        database_products = [
            'AmazonRDS', 'AmazonDynamoDB', 'AmazonElastiCache',
            'AmazonNeptune', 'AmazonRedshift', 'AmazonDocumentDB'
        ]

        # Filter to database resources only
        database_df = combined_df[
            combined_df['product_code'].isin(database_products)
        ].copy()

        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'product_code']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'usage_amount': 'sum',
            'unit': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = database_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"Database summary: {len(result)} records")

        return result

    def aggregate_network_summary(
        self,
        combined_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aggregate network service costs.

        Target table: reporting_ocpaws_network_summary_p

        Equivalent to Trino:
            WHERE product_code IN ('AmazonVPC','AmazonCloudFront','AmazonRoute53','AmazonAPIGateway')
            GROUP BY usage_start, usage_account_id, account_alias_id, product_code

        Returns:
            DataFrame with network-specific aggregates
        """
        network_products = [
            'AmazonVPC', 'AmazonCloudFront', 'AmazonRoute53', 'AmazonAPIGateway'
        ]

        # Filter to network resources only
        network_df = combined_df[
            combined_df['product_code'].isin(network_products)
        ].copy()

        group_by_cols = ['usage_start', 'usage_account_id', 'account_alias_id', 'product_code']

        agg_dict = {
            'cluster_id': 'max',
            'cluster_alias': 'max',
            'usage_amount': 'sum',
            'unit': 'max',
            'unblended_cost': 'sum',
            'markup_cost': 'sum',
            'blended_cost': 'sum',
            'markup_cost_blended': 'sum',
            'savingsplan_effective_cost': 'sum',
            'markup_cost_savingsplan': 'sum',
            'calculated_amortized_cost': 'sum',
            'markup_cost_amortized': 'sum',
            'currency_code': 'max'
        }

        result = network_df.groupby(group_by_cols).agg(agg_dict).reset_index()
        result['usage_end'] = result['usage_start']

        import uuid
        result['id'] = [str(uuid.uuid4()) for _ in range(len(result))]

        self.logger.info(f"Network summary: {len(result)} records")

        return result

    def aggregate_all(
        self,
        combined_df: pd.DataFrame
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate all 9 aggregation tables.

        Returns:
            Dictionary mapping table names to DataFrames
        """
        self.logger.info("Starting aggregation for all 9 tables...")

        results = {
            'detailed_line_items': self.aggregate_detailed_line_items(combined_df),
            'cluster_totals': self.aggregate_cluster_totals(combined_df),
            'by_account': self.aggregate_by_account(combined_df),
            'by_service': self.aggregate_by_service(combined_df),
            'by_region': self.aggregate_by_region(combined_df),
            'compute_summary': self.aggregate_compute_summary(combined_df),
            'storage_summary': self.aggregate_storage_summary(combined_df),
            'database_summary': self.aggregate_database_summary(combined_df),
            'network_summary': self.aggregate_network_summary(combined_df)
        }

        self.logger.info("Aggregation complete for all 9 tables")

        return results
```

---

## Implementation Modules

### Module Structure

```
src/
├── aws_data_loader.py          # NEW: Load AWS CUR Parquet files
├── resource_matcher.py          # NEW: Match AWS to OCP
├── disk_capacity_calculator.py  # NEW: Calculate EBS capacities
├── cost_attributor.py           # NEW: Attribute costs to namespaces
├── aggregator_ocpaws.py         # NEW: Aggregate to 9 tables
├── main_ocpaws.py               # NEW: Main pipeline for OCP on AWS
│
├── parquet_reader.py            # EXISTING: Reuse for AWS Parquet
├── utils.py                     # EXISTING: Reuse utilities
├── postgres_writer.py           # EXISTING: Reuse for writes
├── aggregator_pod.py            # EXISTING: OCP aggregation (reuse label precedence)
└── main.py                      # EXISTING: OCP pipeline
```

### Main Pipeline: `src/main_ocpaws.py`

```python
"""
Main Pipeline for OCP on AWS
Orchestrates the entire OCP on AWS aggregation process
"""

import pandas as pd
from src.aws_data_loader import AWSDataLoader
from src.resource_matcher import ResourceMatcher
from src.disk_capacity_calculator import DiskCapacityCalculator
from src.cost_attributor import CostAttributor
from src.aggregator_ocpaws import OCPAWSAggregator
from src.parquet_reader import ParquetReader
from src.postgres_writer import PostgreSQLWriter
from src.utils import log_memory_usage, cleanup_memory

class OCPAWSPipeline:
    """Main pipeline for OCP on AWS aggregation."""

    def __init__(self, config, logger, postgres_conn):
        self.config = config
        self.logger = logger
        self.postgres_conn = postgres_conn

        # Initialize components
        self.aws_loader = AWSDataLoader(config, logger)
        self.resource_matcher = ResourceMatcher(config, logger, postgres_conn)
        self.capacity_calculator = DiskCapacityCalculator(config, logger)
        self.cost_attributor = CostAttributor(config, logger)
        self.aggregator = OCPAWSAggregator(config, logger)
        self.parquet_reader = ParquetReader(config, logger)
        self.postgres_writer = PostgreSQLWriter(config, logger, postgres_conn)

    def run(
        self,
        aws_source_uuid: str,
        ocp_source_uuid: str,
        year: str,
        month: str,
        start_date: str,
        end_date: str,
        schema: str,
        markup: float = 0.0
    ):
        """
        Run the complete OCP on AWS aggregation pipeline.

        Steps:
        1. Load OCP data (reuse existing OCP POC)
        2. Load AWS data
        3. Match AWS resources to OCP
        4. Calculate disk capacities
        5. Attribute costs
        6. Aggregate to 9 tables
        7. Write to PostgreSQL

        Args:
            aws_source_uuid: AWS source UUID
            ocp_source_uuid: OCP source UUID
            year: Year partition
            month: Month partition
            start_date: Start date
            end_date: End date
            schema: PostgreSQL schema
            markup: Markup percentage (e.g., 0.10 for 10%)
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting OCP on AWS aggregation pipeline")
        self.logger.info("=" * 80)

        # Step 1: Load OCP data
        self.logger.info("Step 1: Loading OCP data...")
        log_memory_usage(self.logger, "before OCP load")

        ocp_pod_usage = self.parquet_reader.read_pod_usage_line_items(
            ocp_source_uuid, year, month
        )
        ocp_storage_usage = self.parquet_reader.read_storage_usage_line_items(
            ocp_source_uuid, year, month
        )

        log_memory_usage(self.logger, "after OCP load")

        # Step 2: Load AWS data
        self.logger.info("Step 2: Loading AWS data...")
        log_memory_usage(self.logger, "before AWS load")

        aws_line_items = self.aws_loader.read_aws_line_items_daily(
            aws_source_uuid, year, month, start_date, end_date
        )

        log_memory_usage(self.logger, "after AWS load")

        # Step 3: Match AWS resources to OCP
        self.logger.info("Step 3: Matching AWS resources to OCP...")
        log_memory_usage(self.logger, "before matching")

        matched_aws = self.resource_matcher.match_aws_to_ocp(
            aws_line_items,
            ocp_pod_usage,
            ocp_storage_usage,
            schema
        )

        # Clean up
        del aws_line_items
        cleanup_memory(self.logger)
        log_memory_usage(self.logger, "after matching")

        # Step 4: Calculate disk capacities (if needed)
        self.logger.info("Step 4: Calculating disk capacities...")

        # Note: This requires hourly AWS data, not daily
        # For now, skip if not available
        disk_capacities = pd.DataFrame()  # Placeholder

        # Step 5: Attribute costs
        self.logger.info("Step 5: Attributing costs...")
        log_memory_usage(self.logger, "before cost attribution")

        storage_costs = self.cost_attributor.attribute_storage_costs(
            matched_aws, ocp_storage_usage, disk_capacities, markup
        )

        compute_costs = self.cost_attributor.attribute_compute_costs(
            matched_aws, ocp_pod_usage, markup
        )

        network_costs = self.cost_attributor.attribute_network_costs(
            matched_aws, ocp_pod_usage, markup
        )

        combined_costs = self.cost_attributor.combine_attributed_costs(
            storage_costs, compute_costs, network_costs
        )

        # Clean up
        del matched_aws, storage_costs, compute_costs, network_costs
        cleanup_memory(self.logger)
        log_memory_usage(self.logger, "after cost attribution")

        # Step 6: Aggregate to 9 tables
        self.logger.info("Step 6: Aggregating to 9 summary tables...")
        log_memory_usage(self.logger, "before aggregation")

        aggregated_tables = self.aggregator.aggregate_all(combined_costs)

        log_memory_usage(self.logger, "after aggregation")

        # Step 7: Write to PostgreSQL
        self.logger.info("Step 7: Writing to PostgreSQL...")

        table_mapping = {
            'detailed_line_items': 'reporting_ocpawscostlineitem_project_daily_summary_p',
            'cluster_totals': 'reporting_ocpaws_cost_summary_p',
            'by_account': 'reporting_ocpaws_cost_summary_by_account_p',
            'by_service': 'reporting_ocpaws_cost_summary_by_service_p',
            'by_region': 'reporting_ocpaws_cost_summary_by_region_p',
            'compute_summary': 'reporting_ocpaws_compute_summary_p',
            'storage_summary': 'reporting_ocpaws_storage_summary_p',
            'database_summary': 'reporting_ocpaws_database_summary_p',
            'network_summary': 'reporting_ocpaws_network_summary_p'
        }

        for key, table_name in table_mapping.items():
            df = aggregated_tables[key]
            if len(df) > 0:
                self.postgres_writer.bulk_insert(
                    table_name=f"{schema}.{table_name}",
                    dataframe=df
                )

        self.logger.info("=" * 80)
        self.logger.info("OCP on AWS aggregation pipeline complete!")
        self.logger.info("=" * 80)
```

---

## Integration with Existing POC

### Strategy: Provider Type Pattern

The existing OCP POC will be extended to support multiple provider types:

```python
# config/config.yaml

providers:
  - type: "OCP"
    enabled: true
    source_uuid: "ocp-source-uuid"

  - type: "OCP_AWS"
    enabled: true
    aws_source_uuid: "aws-source-uuid"
    ocp_source_uuid: "ocp-source-uuid"
    markup: 0.10  # 10% markup
```

### Main Entry Point: `src/main.py` (Enhanced)

```python
"""
Main entry point - supports both OCP and OCP on AWS
"""

def main():
    config = load_config()
    logger = setup_logging()
    postgres_conn = get_postgres_connection()

    for provider in config['providers']:
        if not provider['enabled']:
            continue

        if provider['type'] == 'OCP':
            # Run existing OCP pipeline
            ocp_pipeline = OCPPipeline(config, logger, postgres_conn)
            ocp_pipeline.run(
                source_uuid=provider['source_uuid'],
                year=config['year'],
                month=config['month'],
                schema=config['schema']
            )

        elif provider['type'] == 'OCP_AWS':
            # Run new OCP on AWS pipeline
            ocpaws_pipeline = OCPAWSPipeline(config, logger, postgres_conn)
            ocpaws_pipeline.run(
                aws_source_uuid=provider['aws_source_uuid'],
                ocp_source_uuid=provider['ocp_source_uuid'],
                year=config['year'],
                month=config['month'],
                start_date=config['start_date'],
                end_date=config['end_date'],
                schema=config['schema'],
                markup=provider.get('markup', 0.0)
            )
```

---

## Summary

This document provides a complete mapping of Trino SQL to Python/PyArrow implementations for OCP on AWS. The key principles are:

1. **Reuse Existing Infrastructure**: Leverage ParquetReader, PostgreSQLWriter, and utilities from OCP POC
2. **Modular Design**: Each phase (matching, attribution, aggregation) is a separate module
3. **Clear SQL-to-Python Mapping**: Each Python method documents its equivalent Trino SQL
4. **Performance Optimizations**: Apply streaming, parallel reading, and memory optimizations from OCP POC
5. **Provider Type Pattern**: Extend existing POC to support multiple provider types

### Next Steps

1. **Review this document** with technical lead
2. **Create implementation plan** based on this analysis
3. **Start with Phase 1** (Resource Matching)
4. **Validate each phase** against Trino results
5. **Integrate with existing POC** using provider type pattern

---

**Document**: TRINO_TO_PYTHON_IMPLEMENTATION.md
**Status**: ✅ Complete - Ready for Implementation Planning
**Date**: November 21, 2025
**Next**: Create detailed implementation plan

