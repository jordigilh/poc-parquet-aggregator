#!/bin/bash
#
# E2E Validation Script
# Strict validation for OCP aggregation results
# Used by both local E2E tests and CI/CD
#
# Usage:
#   ./scripts/validate_e2e_results.sh [cluster_id]
#
# Environment variables:
#   POSTGRES_HOST (default: localhost)
#   POSTGRES_PORT (default: 15432)
#   POSTGRES_USER (default: koku)
#   POSTGRES_PASSWORD (default: koku123)
#   POSTGRES_DB (default: koku)
#   ORG_ID (default: org1234567)

set -e

# Configuration
CLUSTER_ID="${1:-e2e-test-cluster}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-15432}"
POSTGRES_USER="${POSTGRES_USER:-koku}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-koku123}"
POSTGRES_DB="${POSTGRES_DB:-koku}"
ORG_ID="${ORG_ID:-org1234567}"

# Colors (disabled in CI)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    GREEN=''
    RED=''
    YELLOW=''
    NC=''
fi

# Helper function to run psql
run_psql() {
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "$1" | xargs
}

run_psql_display() {
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"
}

echo "=========================================="
echo "=== E2E Validation Results ==="
echo "=========================================="
echo "Cluster ID: $CLUSTER_ID"
echo "Database: $POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"
echo ""

# Track validation failures
VALIDATION_FAILURES=0

# =============================================================================
# 1. Total Row Count
# =============================================================================
echo "1. Total Row Count"
echo "-------------------"
TOTAL_ROWS=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID';")
echo "Total rows: $TOTAL_ROWS"

if [ "$TOTAL_ROWS" -eq 0 ]; then
    echo -e "${RED}❌ FAIL: No data found in database${NC}"
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: Data found in database ($TOTAL_ROWS rows)${NC}"
fi

# =============================================================================
# 2. Data Source Distribution (Pod vs Storage)
# =============================================================================
echo ""
echo "2. Data Source Distribution"
echo "---------------------------"
run_psql_display "SELECT data_source, COUNT(*) as count FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' GROUP BY data_source ORDER BY data_source;"

POD_ROWS=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod';")
STORAGE_ROWS=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage';")

if [ "$POD_ROWS" -eq 0 ]; then
    echo -e "${RED}❌ FAIL: No Pod data found${NC}"
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: Pod rows = $POD_ROWS${NC}"
fi

if [ "$STORAGE_ROWS" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  WARNING: No Storage data found (may be expected for pod-only scenarios)${NC}"
else
    echo -e "${GREEN}✅ PASS: Storage rows = $STORAGE_ROWS${NC}"
fi

# =============================================================================
# 3. Namespace Coverage
# =============================================================================
echo ""
echo "3. Namespace Coverage"
echo "---------------------"
NAMESPACE_COUNT=$(run_psql "SELECT COUNT(DISTINCT namespace) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND namespace IS NOT NULL;")
echo "Distinct namespaces: $NAMESPACE_COUNT"

run_psql_display "SELECT namespace, COUNT(*) as rows FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' GROUP BY namespace ORDER BY namespace LIMIT 10;"

if [ "$NAMESPACE_COUNT" -eq 0 ]; then
    echo -e "${RED}❌ FAIL: No namespaces found${NC}"
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: $NAMESPACE_COUNT namespace(s) found${NC}"
fi

# =============================================================================
# 4. Pod Metrics Validation (for Pod rows)
# =============================================================================
echo ""
echo "4. Pod Metrics Validation"
echo "-------------------------"
POD_WITH_CPU=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' AND pod_usage_cpu_core_hours IS NOT NULL AND pod_usage_cpu_core_hours > 0;")
POD_WITH_MEMORY=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' AND pod_usage_memory_gigabyte_hours IS NOT NULL AND pod_usage_memory_gigabyte_hours > 0;")

echo "Pod rows with CPU usage: $POD_WITH_CPU / $POD_ROWS"
echo "Pod rows with memory usage: $POD_WITH_MEMORY / $POD_ROWS"

if [ "$POD_ROWS" -gt 0 ]; then
    if [ "$POD_WITH_CPU" -eq 0 ] || [ "$POD_WITH_MEMORY" -eq 0 ]; then
        echo -e "${RED}❌ FAIL: Pod rows missing CPU/memory metrics${NC}"
        VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
    else
        echo -e "${GREEN}✅ PASS: Pod rows have CPU/memory metrics${NC}"
    fi
fi

# =============================================================================
# 5. Storage Metrics Validation (for Storage rows)
# =============================================================================
echo ""
echo "5. Storage Metrics Validation"
echo "-----------------------------"
if [ "$STORAGE_ROWS" -gt 0 ]; then
    STORAGE_WITH_CAPACITY=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage' AND persistentvolumeclaim_capacity_gigabyte_months IS NOT NULL AND persistentvolumeclaim_capacity_gigabyte_months > 0;")
    STORAGE_WITH_USAGE=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage' AND persistentvolumeclaim_usage_gigabyte_months IS NOT NULL AND persistentvolumeclaim_usage_gigabyte_months > 0;")
    
    echo "Storage rows with capacity: $STORAGE_WITH_CAPACITY / $STORAGE_ROWS"
    echo "Storage rows with usage: $STORAGE_WITH_USAGE / $STORAGE_ROWS"
    
    if [ "$STORAGE_WITH_CAPACITY" -eq 0 ] || [ "$STORAGE_WITH_USAGE" -eq 0 ]; then
        echo -e "${RED}❌ FAIL: Storage rows missing storage metrics${NC}"
        VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
    else
        echo -e "${GREEN}✅ PASS: Storage rows have storage metrics${NC}"
    fi
    
    # Storage class distribution
    echo ""
    echo "Storage Class Distribution:"
    run_psql_display "SELECT storageclass, COUNT(*) as count FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage' GROUP BY storageclass ORDER BY storageclass;"
else
    echo "Skipped (no storage rows)"
fi

# =============================================================================
# 6. Data Integrity - No Duplicate Aggregations
# =============================================================================
echo ""
echo "6. Duplicate Aggregation Check"
echo "------------------------------"
echo "Note: Pod rows grouped by (usage_start, namespace, node)"
echo "      Storage rows grouped by (usage_start, namespace, node, pvc, pv, storageclass)"

# Check for Pod duplicates (grouped by usage_start, namespace, node)
POD_DUPLICATES=$(run_psql "SELECT COUNT(*) FROM (SELECT usage_start, namespace, node, COUNT(*) as cnt FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' GROUP BY usage_start, namespace, node HAVING COUNT(*) > 1) as dupes;")
echo "Pod duplicate aggregations: $POD_DUPLICATES"

# Check for Storage duplicates (grouped by usage_start, namespace, node, pvc, pv, storageclass)
STORAGE_DUPLICATES=$(run_psql "SELECT COUNT(*) FROM (SELECT usage_start, namespace, node, persistentvolumeclaim, persistentvolume, storageclass, COUNT(*) as cnt FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage' GROUP BY usage_start, namespace, node, persistentvolumeclaim, persistentvolume, storageclass HAVING COUNT(*) > 1) as dupes;")
echo "Storage duplicate aggregations: $STORAGE_DUPLICATES"

TOTAL_DUPLICATES=$((POD_DUPLICATES + STORAGE_DUPLICATES))

if [ "$TOTAL_DUPLICATES" -gt 0 ]; then
    echo -e "${RED}❌ FAIL: Found duplicate aggregations${NC}"
    if [ "$POD_DUPLICATES" -gt 0 ]; then
        echo "Pod duplicates:"
        run_psql_display "SELECT usage_start, namespace, node, COUNT(*) as cnt FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' GROUP BY usage_start, namespace, node HAVING COUNT(*) > 1 LIMIT 5;"
    fi
    if [ "$STORAGE_DUPLICATES" -gt 0 ]; then
        echo "Storage duplicates:"
        run_psql_display "SELECT usage_start, namespace, node, persistentvolumeclaim, persistentvolume, storageclass, COUNT(*) as cnt FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Storage' GROUP BY usage_start, namespace, node, persistentvolumeclaim, persistentvolume, storageclass HAVING COUNT(*) > 1 LIMIT 5;"
    fi
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: No duplicate aggregations${NC}"
fi

# =============================================================================
# 7. Cluster Metadata
# =============================================================================
echo ""
echo "7. Cluster Metadata"
echo "-------------------"
ROWS_WITH_CLUSTER=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND cluster_id IS NOT NULL;")
echo "Rows with cluster_id: $ROWS_WITH_CLUSTER / $TOTAL_ROWS"

if [ "$ROWS_WITH_CLUSTER" -ne "$TOTAL_ROWS" ]; then
    echo -e "${RED}❌ FAIL: Some rows missing cluster_id${NC}"
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: All rows have cluster_id${NC}"
fi

# =============================================================================
# 8. JSON Labels Validation
# =============================================================================
echo ""
echo "8. JSON Labels Validation"
echo "-------------------------"
INVALID_POD_LABELS=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND pod_labels IS NOT NULL AND pod_labels::text NOT LIKE '{%}';")
echo "Invalid pod_labels: $INVALID_POD_LABELS"

if [ "$INVALID_POD_LABELS" -gt 0 ]; then
    echo -e "${RED}❌ FAIL: Found invalid JSON in pod_labels${NC}"
    VALIDATION_FAILURES=$((VALIDATION_FAILURES + 1))
else
    echo -e "${GREEN}✅ PASS: All pod_labels are valid JSON${NC}"
fi

# Sample labels
echo ""
echo "Sample Pod labels:"
run_psql_display "SELECT namespace, node, pod_labels FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' AND pod_labels IS NOT NULL LIMIT 3;"

# =============================================================================
# 9. Date Range
# =============================================================================
echo ""
echo "9. Date Range"
echo "-------------"
run_psql_display "SELECT MIN(usage_start) as min_date, MAX(usage_start) as max_date, COUNT(DISTINCT usage_start) as unique_dates FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID';"

# =============================================================================
# 10. Node Capacity (for Pod rows)
# =============================================================================
echo ""
echo "10. Node Capacity"
echo "-----------------"
if [ "$POD_ROWS" -gt 0 ]; then
    ROWS_WITH_CAPACITY=$(run_psql "SELECT COUNT(*) FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary WHERE cluster_id='$CLUSTER_ID' AND data_source='Pod' AND node_capacity_cpu_core_hours IS NOT NULL AND node_capacity_cpu_core_hours > 0;")
    echo "Pod rows with node capacity: $ROWS_WITH_CAPACITY / $POD_ROWS"
    
    if [ "$ROWS_WITH_CAPACITY" -eq 0 ]; then
        echo -e "${YELLOW}⚠️  WARNING: No node capacity data found${NC}"
    else
        echo -e "${GREEN}✅ PASS: Node capacity data present${NC}"
    fi
fi

# =============================================================================
# 11. Aggregated Metrics Summary
# =============================================================================
echo ""
echo "11. Aggregated Metrics Summary"
echo "------------------------------"
run_psql_display "SELECT 
    ROUND(SUM(pod_usage_cpu_core_hours)::numeric, 2) as total_cpu_hours,
    ROUND(SUM(pod_usage_memory_gigabyte_hours)::numeric, 2) as total_mem_gb_hours,
    ROUND(SUM(persistentvolumeclaim_usage_gigabyte_months)::numeric, 4) as total_storage_gb_months
FROM ${ORG_ID}.reporting_ocpusagelineitem_daily_summary 
WHERE cluster_id='$CLUSTER_ID';"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=========================================="
echo "=== Validation Summary ==="
echo "=========================================="
echo "Total rows processed: $TOTAL_ROWS"
echo "Pod rows: $POD_ROWS"
echo "Storage rows: $STORAGE_ROWS"
echo "Validation failures: $VALIDATION_FAILURES"
echo ""

if [ "$VALIDATION_FAILURES" -gt 0 ]; then
    echo -e "${RED}❌ VALIDATION FAILED: $VALIDATION_FAILURES check(s) failed${NC}"
    exit 1
else
    echo -e "${GREEN}✅ ALL VALIDATIONS PASSED${NC}"
    exit 0
fi

