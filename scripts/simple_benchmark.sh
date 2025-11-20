#!/bin/bash
# Simple benchmark using existing test data

set -e

# Use existing test data from previous runs
export S3_ENDPOINT="http://localhost:9000"
export S3_ACCESS_KEY="minioadmin"
export S3_SECRET_KEY="minioadmin"
export S3_BUCKET="cost-management"
export POSTGRES_HOST="localhost"
export POSTGRES_PASSWORD="koku123"
export POSTGRES_SCHEMA="org1234567"
export ORG_ID="org1234567"

# Find an existing provider UUID from MinIO
echo "Finding existing test data in MinIO..."
PROVIDER_UUID=$(python3 << 'PYEOF'
import s3fs
import os

fs = s3fs.S3FileSystem(
    key='minioadmin',
    secret='minioadmin',
    client_kwargs={'endpoint_url': 'http://localhost:9000'}
)

try:
    # List all providers
    files = fs.glob('cost-management/data/*/OCP/source=*/**/*.parquet')
    if files:
        # Extract provider UUID from first file
        for f in files:
            if 'source=' in f:
                provider = f.split('source=')[1].split('/')[0]
                print(provider)
                break
except Exception as e:
    print("", file=sys.stderr)
PYEOF
)

if [ -z "$PROVIDER_UUID" ]; then
    echo "❌ No existing test data found in MinIO"
    echo "Run an IQE test first: ./scripts/run_iqe_validation.sh"
    exit 1
fi

export OCP_PROVIDER_UUID="$PROVIDER_UUID"
export OCP_CLUSTER_ID="iqe-test-cluster"

echo "✓ Found provider: $PROVIDER_UUID"

# Find which months have data
YEAR_MONTH=$(python3 << 'PYEOF'
import s3fs
import os

provider = os.getenv('OCP_PROVIDER_UUID')
fs = s3fs.S3FileSystem(
    key='minioadmin',
    secret='minioadmin',
    client_kwargs={'endpoint_url': 'http://localhost:9000'}
)

try:
    for year in ['2025', '2024']:
        for month in range(1, 13):
            month_str = f'{month:02d}'
            files = fs.glob(f'cost-management/data/*/OCP/source={provider}/year={year}/month={month_str}/**/*.parquet')
            if files:
                print(f"{year} {month_str}")
                break
        else:
            continue
        break
except Exception as e:
    print("2025 11", file=sys.stderr)
PYEOF
)

export POC_YEAR=$(echo $YEAR_MONTH | awk '{print $1}')
export POC_MONTH=$(echo $YEAR_MONTH | awk '{print $2}')

echo "✓ Found data: $POC_YEAR-$POC_MONTH"

# Activate venv
source venv/bin/activate

# Run benchmark
echo ""
echo "Running benchmark..."
python3 scripts/benchmark_performance.py \
    --provider-uuid "$OCP_PROVIDER_UUID" \
    --year "$POC_YEAR" \
    --month "$POC_MONTH" \
    --output "benchmark_results/benchmark_empirical_$(date +%Y%m%d_%H%M%S).json"

echo ""
echo "✓ Benchmark complete!"
