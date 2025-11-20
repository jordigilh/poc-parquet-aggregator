#!/bin/bash
# Quick start script for local POC validation environment using Podman
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}POC Local Environment Setup (Podman)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if podman is installed
if ! command -v podman &> /dev/null; then
    echo -e "${RED}ERROR: podman is not installed${NC}"
    echo "Install with: brew install podman"
    exit 1
fi

# Check if podman machine is running (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! podman machine list | grep -q "Currently running"; then
        echo -e "${YELLOW}Podman machine not running. Starting...${NC}"
        podman machine start || {
            echo -e "${YELLOW}No podman machine found. Creating one...${NC}"
            podman machine init
            podman machine start
        }
    fi
fi

# Create pod with port mappings
echo -e "${BLUE}Step 1: Creating Podman pod...${NC}"
if podman pod exists poc-pod; then
    echo -e "${YELLOW}Pod 'poc-pod' already exists. Removing...${NC}"
    podman pod rm -f poc-pod
fi

podman pod create --name poc-pod \
    -p 9000:9000 \
    -p 9001:9001 \
    -p 5432:5432

echo -e "${GREEN}✓ Pod created${NC}"

# Start MinIO
echo -e "${BLUE}Step 2: Starting MinIO...${NC}"
podman run -d \
    --pod poc-pod \
    --name minio-poc \
    -e MINIO_ROOT_USER=minioadmin \
    -e MINIO_ROOT_PASSWORD=minioadmin \
    -v minio-data:/data:Z \
    quay.io/minio/minio server /data --console-address ":9001"

echo -e "${GREEN}✓ MinIO started${NC}"
echo -e "  Console: ${BLUE}http://localhost:9001${NC} (minioadmin/minioadmin)"

# Start PostgreSQL
echo -e "${BLUE}Step 3: Starting PostgreSQL...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_DIR="$(dirname "$SCRIPT_DIR")"

podman run -d \
    --pod poc-pod \
    --name postgres-poc \
    -e POSTGRES_USER=koku \
    -e POSTGRES_PASSWORD=koku123 \
    -e POSTGRES_DB=koku \
    -v postgres-data:/var/lib/postgresql/data:Z \
    -v "$POC_DIR/scripts/init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:Z" \
    postgres:15

echo -e "${GREEN}✓ PostgreSQL started${NC}"

# Wait for services to be ready
echo -e "${BLUE}Step 4: Waiting for services to be ready...${NC}"
sleep 5

# Check MinIO
echo -n "  Checking MinIO... "
for i in {1..30}; do
    if curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ (timeout)${NC}"
        echo -e "${YELLOW}Check logs: podman logs minio-poc${NC}"
    fi
done

# Check PostgreSQL
echo -n "  Checking PostgreSQL... "
for i in {1..30}; do
    if pg_isready -h localhost -U koku > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ (timeout)${NC}"
        echo -e "${YELLOW}Check logs: podman logs postgres-poc${NC}"
    fi
done

# Create MinIO bucket
echo -e "${BLUE}Step 5: Creating MinIO bucket...${NC}"
if command -v mc &> /dev/null; then
    mc alias set local http://localhost:9000 minioadmin minioadmin 2>/dev/null || true
    mc mb local/cost-management 2>/dev/null || echo "  Bucket already exists"
    echo -e "${GREEN}✓ Bucket 'cost-management' ready${NC}"
else
    echo -e "${YELLOW}⚠ MinIO client (mc) not installed. Create bucket manually via console.${NC}"
    echo -e "  Install with: brew install minio/stable/mc"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Environment Ready!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Services:"
echo -e "  MinIO Console:  ${BLUE}http://localhost:9001${NC} (minioadmin/minioadmin)"
echo -e "  MinIO S3 API:   ${BLUE}http://localhost:9000${NC}"
echo -e "  PostgreSQL:     ${BLUE}localhost:5432${NC} (koku/koku123)"
echo ""
echo "Useful commands:"
echo -e "  ${BLUE}podman ps${NC}                    # List running containers"
echo -e "  ${BLUE}podman logs minio-poc${NC}        # View MinIO logs"
echo -e "  ${BLUE}podman logs postgres-poc${NC}     # View PostgreSQL logs"
echo -e "  ${BLUE}podman exec -it postgres-poc psql -U koku -d koku${NC}  # Connect to DB"
echo ""
echo "Next steps:"
echo -e "  1. Generate test data:  ${BLUE}./scripts/generate-test-data.sh${NC}"
echo -e "  2. Run POC validation:  ${BLUE}./scripts/run-poc-validation.sh${NC}"
echo -e "  3. Stop environment:    ${BLUE}./scripts/stop-local-env.sh${NC}"
echo ""

