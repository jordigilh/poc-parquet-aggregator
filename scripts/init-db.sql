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
    ('node_role_kubernetes_io')
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

