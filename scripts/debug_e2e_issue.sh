#!/bin/bash
#
# Debug E2E Test Failures
# Minimal reproduction to understand Cartesian product and $0 cost bugs
#

set -e

POC_ROOT="/Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator"
cd "$POC_ROOT"

echo "========================================"
echo "E2E Debug: Minimal Reproduction"
echo "========================================"
echo ""

# Clean slate
echo "→ Cleaning previous test data..."
rm -rf /tmp/e2e_debug
mkdir -p /tmp/e2e_debug/{ocp,aws}

# Generate TINY dataset with nise
echo "→ Generating MINIMAL test data (1 day, 1 node, 1 pod)..."

# OCP manifest - 1 node, 1 pod, 1 day
cat > /tmp/e2e_debug/ocp_minimal.yml <<'EOF'
generators:
  - OCPGenerator:
      start_date: 2025-10-01
      end_date: 2025-10-01  # 1 day only
      nodes:
        - node:
            node_name: worker-node-1.example.com
            resource_id: i-debug123
            cpu_cores: 2
            memory_gig: 4
            namespaces:
              debug-ns:
                pods:
                  - pod:
                      pod_name: debug-pod-1
                      cpu_request: 1
                      mem_request_gig: 2
                      cpu_limit: 2
                      mem_limit_gig: 4
                      pod_seconds: 3600
EOF

# AWS manifest - 1 EC2 instance, matching resource ID, WITH COST
cat > /tmp/e2e_debug/aws_minimal.yml <<'EOF'
generators:
  - EC2Generator:
      start_date: 2025-10-01
      end_date: 2025-10-01  # 1 day only
      resource_id: i-debug123  # MATCHES OCP!
      amount: 24  # 24 hours
      rate: 0.096  # $0.096/hour = $2.304/day
      tags:
        openshift_cluster: debug-cluster
        openshift_node: worker-node-1
EOF

echo "→ Running nise for OCP..."
source "$POC_ROOT/venv/bin/activate"
cd /tmp/e2e_debug/ocp

nise report ocp \
  --static-report-file /tmp/e2e_debug/ocp_minimal.yml \
  --ocp-cluster-id debug-cluster \
  --start-date 2025-10-01 \
  --end-date 2025-10-01 \
  --write-monthly \
  > /tmp/e2e_debug/nise_ocp.log 2>&1

echo "→ Running nise for AWS..."
cd /tmp/e2e_debug/aws

nise report aws \
  --static-report-file /tmp/e2e_debug/aws_minimal.yml \
  --start-date 2025-10-01 \
  --end-date 2025-10-01 \
  --write-monthly \
  > /tmp/e2e_debug/nise_aws.log 2>&1

cd /tmp/e2e_debug

# Count rows
OCP_ROWS=$(find ocp -name "*.csv" -exec wc -l {} + | tail -1 | awk '{print $1}')
AWS_ROWS=$(find aws -name "*.csv" -exec wc -l {} + | tail -1 | awk '{print $1}')

echo "✅ Data generated:"
echo "   OCP rows: $OCP_ROWS"
echo "   AWS rows: $AWS_ROWS"
echo ""

# Check if alignment is needed
echo "→ Checking OCP resource IDs..."
OCP_RESOURCE_IDS=$(grep -h "resource_id" ocp/*.csv | head -5 | cut -d',' -f1 | sort -u)
echo "   Sample OCP resource_ids:"
echo "$OCP_RESOURCE_IDS" | head -3

echo ""
echo "→ Checking AWS resource IDs..."
AWS_RESOURCE_IDS=$(grep -h "lineItem/ResourceId" aws/*.csv | head -5 | cut -d',' -f1 | sort -u)
echo "   Sample AWS resource_ids:"
echo "$AWS_RESOURCE_IDS" | head -3

echo ""
echo "→ Checking AWS costs..."
AWS_COST_SAMPLE=$(grep -h "lineItem/UnblendedCost" aws/*.csv | head -5 | cut -d',' -f1)
echo "   Sample AWS costs:"
echo "$AWS_COST_SAMPLE" | head -3

echo ""
echo "→ Converting to Parquet and uploading to MinIO..."
export S3_BUCKET="test-bucket"
export ORG_ID="org1234567"
export OCP_PROVIDER_UUID="debug-ocp-uuid"
export AWS_PROVIDER_UUID="debug-aws-uuid"
export OCP_CLUSTER_ID="debug-cluster"

python3 "$POC_ROOT/scripts/csv_to_parquet_minio.py" /tmp/e2e_debug \
  > /tmp/e2e_debug/parquet.log 2>&1

echo "✅ Parquet files uploaded"
echo ""

# Clear database
echo "→ Clearing database..."
podman exec postgres-poc psql -U koku -d koku -c "
  TRUNCATE TABLE org${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;
" > /dev/null 2>&1

echo "✅ Database cleared"
echo ""

# Run POC with DEBUG logging
echo "→ Running POC aggregation WITH DEBUG LOGGING..."
export POC_YEAR="2025"
export POC_MONTH="10"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="15432"
export POSTGRES_DB="koku"
export POSTGRES_USER="koku"
export POSTGRES_PASSWORD="koku_password"
export MINIO_ENDPOINT="http://localhost:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"

cd "$POC_ROOT"
python3 -m src.main --truncate > /tmp/e2e_debug/poc.log 2>&1

POC_EXIT=$?

if [ $POC_EXIT -ne 0 ]; then
    echo "❌ POC aggregation failed!"
    echo ""
    echo "Last 50 lines of POC log:"
    tail -50 /tmp/e2e_debug/poc.log
    exit 1
fi

echo "✅ POC aggregation complete"
echo ""

# Query results
echo "→ Querying results..."
OUTPUT_ROWS=$(podman exec postgres-poc psql -U koku -d koku -t -c "
  SELECT COUNT(*)
  FROM org${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;
" | tr -d ' ')

TOTAL_COST=$(podman exec postgres-poc psql -U koku -d koku -t -c "
  SELECT ROUND(SUM(unblended_cost)::numeric, 2)
  FROM org${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p;
" | tr -d ' ')

MATCHED_RESOURCE=$(podman exec postgres-poc psql -U koku -d koku -t -c "
  SELECT COUNT(*)
  FROM org${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p
  WHERE resource_id_matched = true;
" | tr -d ' ')

MATCHED_TAG=$(podman exec postgres-poc psql -U koku -d koku -t -c "
  SELECT COUNT(*)
  FROM org${ORG_ID}.reporting_ocpawscostlineitem_project_daily_summary_p
  WHERE tag_matched = true;
" | tr -d ' ')

echo "========================================"
echo "RESULTS"
echo "========================================"
echo "Input:"
echo "  OCP rows: $OCP_ROWS"
echo "  AWS rows: $AWS_ROWS"
echo "  Expected output: ~24-48 rows (1 pod × 24 hours × 1-2 cost types)"
echo ""
echo "Output:"
echo "  Total rows: $OUTPUT_ROWS"
echo "  Resource ID matched: $MATCHED_RESOURCE rows"
echo "  Tag matched: $MATCHED_TAG rows"
echo "  Total cost: \$$TOTAL_COST"
echo ""

# Diagnosis
if [ "$OUTPUT_ROWS" -gt 1000 ]; then
    echo "❌ CARTESIAN PRODUCT DETECTED!"
    echo "   Output rows ($OUTPUT_ROWS) >> Expected (24-48)"
    echo "   Likely cause: Matching returned 0 matches"
fi

if [ "$TOTAL_COST" == "0.00" ] || [ "$TOTAL_COST" == ".00" ]; then
    echo "❌ ZERO COST BUG DETECTED!"
    echo "   Total cost is \$0.00"
    echo "   Likely cause: Cost columns missing or misnamed"
fi

if [ "$MATCHED_RESOURCE" -eq 0 ] && [ "$MATCHED_TAG" -eq 0 ]; then
    echo "❌ ZERO MATCHES DETECTED!"
    echo "   Neither resource_id nor tag matching worked"
    echo "   Likely cause: align_test_data.py not working"
fi

echo ""
echo "Full logs available at:"
echo "  /tmp/e2e_debug/nise_ocp.log"
echo "  /tmp/e2e_debug/nise_aws.log"
echo "  /tmp/e2e_debug/parquet.log"
echo "  /tmp/e2e_debug/poc.log"

