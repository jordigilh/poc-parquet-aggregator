#!/bin/bash
# End-to-end IQE validation workflow

set -e

# Configuration
IQE_YAML="${IQE_YAML:-ocp_report_advanced.yml}"
OUTPUT_DIR="${OUTPUT_DIR:-/tmp/nise-iqe-data}"
CLUSTER_ID="iqe-test-cluster"
# Use a unique provider UUID based on the YAML file to avoid conflicts between tests
PROVIDER_UUID="${PROVIDER_UUID:-$(echo -n "${IQE_YAML}" | md5 | cut -c1-32 | sed 's/\(........\)\(....\)\(....\)\(....\)\(............\)/\1-\2-\3-\4-\5/')}"
ORG_ID="1234567"

echo "================================================================================"
echo "POC Validation with IQE Test Data"
echo "================================================================================"
echo "IQE YAML: ${IQE_YAML}"
echo "Cluster ID: ${CLUSTER_ID}"
echo "================================================================================"

# Export environment variables
export S3_ENDPOINT=http://localhost:9000
export S3_ACCESS_KEY=minioadmin
export S3_SECRET_KEY=minioadmin
export S3_BUCKET=cost-management
export POSTGRES_HOST=localhost
export POSTGRES_DB=koku
export POSTGRES_USER=koku
export POSTGRES_PASSWORD=koku123
export POSTGRES_SCHEMA=org${ORG_ID}
export OCP_PROVIDER_UUID=${PROVIDER_UUID}
export OCP_CLUSTER_ID=${CLUSTER_ID}
export ORG_ID=${ORG_ID}
export PROVIDER_TYPE=OCP
export IQE_YAML_FILE="config/${IQE_YAML}"

# Activate venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ Virtual environment not found. Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Phase 1: Ensure local environment is running
echo ""
echo "Phase 1: Checking local environment..."
if ! podman ps | grep -q postgres-poc; then
    echo "Starting local environment..."
    ./scripts/start-local-env.sh
    sleep 5
else
    echo "✓ Local environment already running"
fi

# Phase 2: Generate IQE test data
echo ""
echo "Phase 2: Generating IQE test data..."
./scripts/generate_iqe_test_data.sh

# Phase 3: Convert CSV to Parquet and upload to MinIO
echo ""
echo "Phase 3: Converting CSV to Parquet and uploading to MinIO..."
python3 scripts/csv_to_parquet_minio.py "${OUTPUT_DIR}"

# Phase 3.5: Detect which months have data
echo ""
echo "Phase 3.5: Detecting data months from MinIO..."
MONTHS_TO_PROCESS=$(python3 -c "
import s3fs
import os
provider_uuid = os.getenv('OCP_PROVIDER_UUID', '')
try:
    fs = s3fs.S3FileSystem(key='minioadmin', secret='minioadmin', client_kwargs={'endpoint_url': 'http://localhost:9000'})
    # Check all months
    months_with_data = []
    for month in range(1, 13):
        month_str = f'{month:02d}'
        files = fs.glob(f'cost-management/data/*/OCP/source={provider_uuid}/year=2025/month={month_str}/**/*.parquet')
        if len(files) > 0:
            months_with_data.append(month_str)

    if months_with_data:
        print(' '.join(months_with_data))
    else:
        print('11')  # Default to current month
except Exception as e:
    import sys
    print(f'Error detecting months: {e}', file=sys.stderr)
    print('11')  # Default to current month
" 2>&1)

export POC_YEAR=2025
echo "✓ Detected data in months: ${MONTHS_TO_PROCESS} for provider ${OCP_PROVIDER_UUID}"

# Phase 4: Run POC aggregator for each month
echo ""
echo "Phase 4: Running POC aggregator..."
FIRST_MONTH=true
for MONTH in ${MONTHS_TO_PROCESS}; do
    export POC_MONTH=${MONTH}
    echo "  Processing month: ${MONTH}"

    if [ "$FIRST_MONTH" = true ]; then
        # First month: truncate table
        python3 -m src.main --truncate
        FIRST_MONTH=false
    else
        # Subsequent months: append to table
        python3 -m src.main
    fi
done
echo "✓ Processed ${MONTHS_TO_PROCESS}"

# Phase 5: Validate against IQE expected values
echo ""
echo "Phase 5: Validating against IQE expected values..."
python3 scripts/validate_against_iqe.py

# Success
echo ""
echo "================================================================================"
echo "✅ IQE VALIDATION COMPLETE"
echo "================================================================================"
echo "All phases completed successfully!"
echo ""
echo "Results:"
echo "  - Nise data: ${OUTPUT_DIR}"
echo "  - MinIO: http://localhost:9001 (minioadmin/minioadmin)"
echo "  - PostgreSQL: localhost:5432 (koku/koku123)"
echo "  - Summary table: ${POSTGRES_SCHEMA}.reporting_ocpusagelineitem_daily_summary"
echo "================================================================================"

