#!/bin/bash
# Generate benchmark data using nise with configurable scale

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

# Parse arguments
SCALE="${1:-small}"
OUTPUT_DIR="${2:-/tmp/nise-benchmark-data}"

# Scale configurations
case "$SCALE" in
    small)
        PODS=10
        NAMESPACES=2
        NODES=2
        DAYS=1
        DESCRIPTION="Small (1K rows)"
        ;;
    medium)
        PODS=100
        NAMESPACES=5
        NODES=5
        DAYS=1
        DESCRIPTION="Medium (10K rows)"
        ;;
    large)
        PODS=500
        NAMESPACES=10
        NODES=10
        DAYS=1
        DESCRIPTION="Large (50K rows)"
        ;;
    xlarge)
        PODS=1000
        NAMESPACES=10
        NODES=20
        DAYS=1
        DESCRIPTION="Very Large (100K rows)"
        ;;
    xxlarge)
        PODS=2500
        NAMESPACES=20
        NODES=30
        DAYS=1
        DESCRIPTION="Extra Large (250K rows)"
        ;;
    production-small)
        PODS=5000
        NAMESPACES=25
        NODES=40
        DAYS=1
        DESCRIPTION="Production Small (500K rows)"
        ;;
    production-medium)
        PODS=10000
        NAMESPACES=30
        NODES=50
        DAYS=1
        DESCRIPTION="Production Medium (1M rows)"
        ;;
    production-large)
        PODS=20000
        NAMESPACES=40
        NODES=100
        DAYS=1
        DESCRIPTION="Production Large (2M rows)"
        ;;
    *)
        echo "Usage: $0 {small|medium|large|xlarge|xxlarge|production-small|production-medium|production-large} [output_dir]"
        echo ""
        echo "Scales:"
        echo "  small             - 10 pods, 2 namespaces, 2 nodes, 1 day (~1K rows)"
        echo "  medium            - 100 pods, 5 namespaces, 5 nodes, 1 day (~10K rows)"
        echo "  large             - 500 pods, 10 namespaces, 10 nodes, 1 day (~50K rows)"
        echo "  xlarge            - 1000 pods, 10 namespaces, 20 nodes, 1 day (~100K rows)"
        echo "  xxlarge           - 2500 pods, 20 namespaces, 30 nodes, 1 day (~250K rows)"
        echo "  production-small  - 5000 pods, 25 namespaces, 40 nodes, 1 day (~500K rows)"
        echo "  production-medium - 10000 pods, 30 namespaces, 50 nodes, 1 day (~1M rows)"
        echo "  production-large  - 20000 pods, 40 namespaces, 100 nodes, 1 day (~2M rows)"
        exit 1
        ;;
esac

echo "========================================================================"
echo "Generating Nise Benchmark Data: ${DESCRIPTION}"
echo "========================================================================"
echo "Pods: ${PODS}"
echo "Namespaces: ${NAMESPACES}"
echo "Nodes: ${NODES}"
echo "Days: ${DAYS}"
echo "Output: ${OUTPUT_DIR}"
echo ""

# Create output directory
mkdir -p "${OUTPUT_DIR}"

# Generate unique UUID for this test
PROVIDER_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
CLUSTER_ID="benchmark-${SCALE}-${PROVIDER_UUID:0:8}"

# Create temporary YAML config
YAML_FILE="${OUTPUT_DIR}/benchmark_${SCALE}.yml"

cat > "${YAML_FILE}" << EOF
---
generators:
EOF

# Generate namespace/pod configurations
for ns_idx in $(seq 1 ${NAMESPACES}); do
    NAMESPACE="namespace-${ns_idx}"
    PODS_PER_NS=$((PODS / NAMESPACES))

    for pod_idx in $(seq 1 ${PODS_PER_NS}); do
        NODE_IDX=$(( (pod_idx % NODES) + 1 ))
        NODE="node-${NODE_IDX}"
        POD="pod-${ns_idx}-${pod_idx}"

        # Random resource values
        CPU_REQUEST=$(awk -v min=0.1 -v max=2.0 'BEGIN{srand(); print min+rand()*(max-min)}')
        CPU_LIMIT=$(awk -v req=${CPU_REQUEST} 'BEGIN{print req * (1.2 + rand() * 0.8)}')
        MEM_REQUEST=$(awk -v min=128 -v max=2048 'BEGIN{srand(); print int(min+rand()*(max-min))}')
        MEM_LIMIT=$(awk -v req=${MEM_REQUEST} 'BEGIN{print int(req * (1.2 + rand() * 0.3))}')

        cat >> "${YAML_FILE}" << EOFGEN
  - OCPGenerator:
      start_date: last_month
      nodes:
        - node:
          node_name: ${NODE}
          cpu_cores: 8
          memory_gig: 32
          resource_id: ${NODE}-resource-id
          namespaces:
            ${NAMESPACE}:
              pods:
                - pod:
                  pod_name: ${POD}
                  cpu_request: ${CPU_REQUEST}
                  mem_request_gig: $(awk -v m=${MEM_REQUEST} 'BEGIN{print m/1024}')
                  cpu_limit: ${CPU_LIMIT}
                  mem_limit_gig: $(awk -v m=${MEM_LIMIT} 'BEGIN{print m/1024}')
                  pod_seconds: 3600
                  cpu_usage:
                    full_period: $(awk -v c=${CPU_REQUEST} 'BEGIN{print c * 0.7}')
                  mem_usage_gig:
                    full_period: $(awk -v m=${MEM_REQUEST} 'BEGIN{print m/1024 * 0.7}')
                  labels: app:benchmark|tier:backend|namespace:${NAMESPACE}
EOFGEN
    done
done

echo "✓ Generated YAML config: ${YAML_FILE}"
echo "  Provider UUID: ${PROVIDER_UUID}"
echo "  Cluster ID: ${CLUSTER_ID}"
echo ""

# Generate nise data
echo "Generating nise data..."
cd "${OUTPUT_DIR}"
nise report ocp \
    --static-report-file "${YAML_FILE}" \
    --ocp-cluster-id "${CLUSTER_ID}" \
    --write-monthly \
    --file-row-limit 100000 \
    2>&1 | tee "nise_${SCALE}.log"

# Check for generated CSV files (nise writes to current directory with --write-monthly)
NISE_CSV_FILES=$(ls -1 October-*-${CLUSTER_ID}-*.csv 2>/dev/null | head -1)

if [ -z "${NISE_CSV_FILES}" ]; then
    echo "❌ Failed to find nise CSV files"
    echo "Expected pattern: October-*-${CLUSTER_ID}-*.csv"
    ls -la October-*.csv 2>/dev/null || echo "No CSV files found"
    exit 1
fi

echo ""
echo "✓ Nise data generated: ${OUTPUT_DIR}"

# Count rows
TOTAL_ROWS=0
for csv in October-*-${CLUSTER_ID}-*.csv; do
    if [ -f "$csv" ]; then
        ROWS=$(wc -l < "$csv")
        ROWS=$((ROWS - 1))  # Subtract header
        TOTAL_ROWS=$((TOTAL_ROWS + ROWS))
        echo "  $(basename "$csv"): ${ROWS} rows"
    fi
done

echo ""
echo "========================================================================"
echo "Summary"
echo "========================================================================"
echo "Scale: ${DESCRIPTION}"
echo "Total rows: ${TOTAL_ROWS}"
echo "Provider UUID: ${PROVIDER_UUID}"
echo "Cluster ID: ${CLUSTER_ID}"
echo "Nise output: ${OUTPUT_DIR}"
echo "YAML config: ${YAML_FILE}"
echo ""
echo "Next steps:"
echo "  1. Convert to Parquet and upload to MinIO:"
echo "     python3 scripts/csv_to_parquet_minio.py ${OUTPUT_DIR}"
echo ""
echo "  2. Run benchmark:"
echo "     export OCP_PROVIDER_UUID='${PROVIDER_UUID}'"
echo "     export POC_YEAR='2025'"
echo "     export POC_MONTH='10'"
echo "     python3 scripts/benchmark_performance.py \\"
echo "         --provider-uuid '${PROVIDER_UUID}' \\"
echo "         --year '2025' \\"
echo "         --month '10' \\"
echo "         --output 'benchmark_results/benchmark_${SCALE}_\$(date +%Y%m%d_%H%M%S).json'"
echo "========================================================================"

# Save metadata
cat > "${OUTPUT_DIR}/metadata_${SCALE}.json" << EOFMETA
{
  "scale": "${SCALE}",
  "description": "${DESCRIPTION}",
  "provider_uuid": "${PROVIDER_UUID}",
  "cluster_id": "${CLUSTER_ID}",
  "pods": ${PODS},
  "namespaces": ${NAMESPACES},
  "nodes": ${NODES},
  "days": ${DAYS},
  "total_rows": ${TOTAL_ROWS},
  "nise_output": "${NISE_OUTPUT}",
  "yaml_config": "${YAML_FILE}",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOFMETA

echo "✓ Metadata saved: ${OUTPUT_DIR}/metadata_${SCALE}.json"

