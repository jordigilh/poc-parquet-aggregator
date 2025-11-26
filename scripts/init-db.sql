-- PostgreSQL initialization script for POC
-- This script runs automatically when the postgres container starts

-- Create schema for organization
CREATE SCHEMA IF NOT EXISTS org1234567;

-- Create summary table (matching production schema)
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocpusagelineitem_daily_summary (
    uuid UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
    report_period_id INTEGER,
    cluster_id VARCHAR(50),
    cluster_alias VARCHAR(256),
    data_source VARCHAR(64),
    namespace VARCHAR(253),
    node VARCHAR(253),
    resource_id VARCHAR(253),
    usage_start DATE NOT NULL,
    usage_end DATE NOT NULL,
    pod_labels JSONB,
    pod_usage_cpu_core_hours NUMERIC(24,6),
    pod_request_cpu_core_hours NUMERIC(24,6),
    pod_effective_usage_cpu_core_hours NUMERIC(24,6),
    pod_limit_cpu_core_hours NUMERIC(24,6),
    pod_usage_memory_gigabyte_hours NUMERIC(24,6),
    pod_request_memory_gigabyte_hours NUMERIC(24,6),
    pod_effective_usage_memory_gigabyte_hours NUMERIC(24,6),
    pod_limit_memory_gigabyte_hours NUMERIC(24,6),
    node_capacity_cpu_cores NUMERIC(24,6),
    node_capacity_cpu_core_hours NUMERIC(24,6),
    node_capacity_memory_gigabytes NUMERIC(24,6),
    node_capacity_memory_gigabyte_hours NUMERIC(24,6),
    cluster_capacity_cpu_core_hours NUMERIC(24,6),
    cluster_capacity_memory_gigabyte_hours NUMERIC(24,6),
    persistentvolumeclaim VARCHAR(253),
    persistentvolume VARCHAR(253),
    storageclass VARCHAR(50),
    volume_labels JSONB,
    all_labels JSONB,
    persistentvolumeclaim_capacity_gigabyte NUMERIC(24,6),
    persistentvolumeclaim_capacity_gigabyte_months NUMERIC(24,6),
    volume_request_storage_gigabyte_months NUMERIC(24,6),
    persistentvolumeclaim_usage_gigabyte_months NUMERIC(24,6),
    cost_category_id INTEGER,
    source_uuid UUID,
    infrastructure_usage_cost JSONB,
    csi_volume_handle VARCHAR(253),
    source VARCHAR(50),
    year VARCHAR(4),
    month VARCHAR(2),
    day VARCHAR(2)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS summary_source_uuid_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (source_uuid);
CREATE INDEX IF NOT EXISTS summary_usage_start_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (usage_start);
CREATE INDEX IF NOT EXISTS summary_namespace_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (namespace);
CREATE INDEX IF NOT EXISTS summary_node_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (node);
CREATE INDEX IF NOT EXISTS summary_year_month_idx
    ON org1234567.reporting_ocpusagelineitem_daily_summary (year, month);

-- Create OCP-AWS cost summary table (matching production schema from cost-mgmt cluster)
-- Simplified for POC - no foreign keys, no partitioning
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocpawscostlineitem_project_daily_summary_p (
    uuid UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
    cluster_id VARCHAR(50),
    cluster_alias VARCHAR(256),
    data_source VARCHAR(64),
    namespace VARCHAR(253),
    node VARCHAR(253),
    persistentvolumeclaim VARCHAR(253),
    persistentvolume VARCHAR(253),
    storageclass VARCHAR(50),
    pod_labels JSONB,
    resource_id VARCHAR(253),
    usage_start DATE NOT NULL,
    usage_end DATE NOT NULL,
    product_code TEXT NOT NULL,
    product_family VARCHAR(150),
    instance_type VARCHAR(50),
    usage_account_id VARCHAR(50) NOT NULL,
    availability_zone VARCHAR(50),
    region VARCHAR(50),
    unit VARCHAR(63),
    usage_amount NUMERIC(30,15),
    normalized_usage_amount DOUBLE PRECISION,
    currency_code VARCHAR(10),
    unblended_cost NUMERIC(30,15),
    markup_cost NUMERIC(30,15),
    blended_cost NUMERIC(33,15),
    markup_cost_blended NUMERIC(33,15),
    markup_cost_savingsplan NUMERIC(33,15),
    markup_cost_amortized NUMERIC(33,9),
    savingsplan_effective_cost NUMERIC(33,15),
    calculated_amortized_cost NUMERIC(33,9),
    tags JSONB,
    source_uuid UUID,
    account_alias_id INTEGER,
    cost_entry_bill_id INTEGER,
    report_period_id INTEGER,
    cost_category_id INTEGER,
    aws_cost_category JSONB,
    data_transfer_direction TEXT,
    infrastructure_data_in_gigabytes NUMERIC(33,15),
    infrastructure_data_out_gigabytes NUMERIC(33,15)
);

-- Create indexes for OCP-AWS table
CREATE INDEX IF NOT EXISTS ocp_aws_source_uuid_idx
    ON org1234567.reporting_ocpawscostlineitem_project_daily_summary_p (source_uuid);
CREATE INDEX IF NOT EXISTS ocp_aws_usage_start_idx
    ON org1234567.reporting_ocpawscostlineitem_project_daily_summary_p (usage_start);
CREATE INDEX IF NOT EXISTS ocp_aws_namespace_idx
    ON org1234567.reporting_ocpawscostlineitem_project_daily_summary_p (namespace);
CREATE INDEX IF NOT EXISTS ocp_aws_resource_id_idx
    ON org1234567.reporting_ocpawscostlineitem_project_daily_summary_p (resource_id);

-- Create mock enabled tag keys table
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocpenabledtagkeys (
    id SERIAL PRIMARY KEY,
    key VARCHAR(253) NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT TRUE
);

-- Insert test enabled tag keys (matching nise YAML labels)
INSERT INTO org1234567.reporting_ocpenabledtagkeys (key) VALUES
    ('app'),
    ('environment'),
    ('tier'),
    ('component'),
    ('nodeclass'),
    ('node_role_kubernetes_io'),
    -- OpenShift tags for tag-based matching (critical for scenarios 02, 07, etc.)
    ('openshift_cluster'),
    ('openshift_node'),
    ('openshift_project'),
    -- Additional generic tags (scenario 23, etc.)
    ('team'),
    ('version'),
    ('storageclass'),
    -- Benchmark labels (for unique pod identification in benchmarks)
    ('pod'),
    ('node')
ON CONFLICT (key) DO NOTHING;

-- Create mock cost category table
CREATE TABLE IF NOT EXISTS org1234567.reporting_ocp_cost_category (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    namespace_pattern VARCHAR(255) NOT NULL
);

-- Insert test cost categories
INSERT INTO org1234567.reporting_ocp_cost_category (id, name, namespace_pattern) VALUES
    (1, 'Production', 'prod-%'),
    (2, 'Development', 'dev-%'),
    (3, 'Testing', 'test-%'),
    (4, 'Monitoring', 'monitoring%'),
    (5, 'System', 'kube-%')
ON CONFLICT (id) DO NOTHING;

-- Grant permissions (if needed)
GRANT ALL PRIVILEGES ON SCHEMA org1234567 TO koku;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA org1234567 TO koku;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA org1234567 TO koku;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'POC database initialized successfully';
    RAISE NOTICE 'Schema: org1234567';
    RAISE NOTICE 'Tables: reporting_ocpusagelineitem_daily_summary, reporting_ocpenabledtagkeys, reporting_ocp_cost_category';
END $$;

