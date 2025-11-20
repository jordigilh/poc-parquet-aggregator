#!/bin/bash
# Stop local POC validation environment
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Stopping POC Local Environment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Stop and remove containers
echo -e "${BLUE}Stopping containers...${NC}"
podman stop minio-poc postgres-poc 2>/dev/null || true
podman rm minio-poc postgres-poc 2>/dev/null || true
echo -e "${GREEN}✓ Containers stopped${NC}"

# Remove pod
echo -e "${BLUE}Removing pod...${NC}"
podman pod rm poc-pod 2>/dev/null || true
echo -e "${GREEN}✓ Pod removed${NC}"

# Ask about volumes
echo ""
read -p "Remove volumes (data will be lost)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Removing volumes...${NC}"
    podman volume rm minio-data postgres-data 2>/dev/null || true
    echo -e "${GREEN}✓ Volumes removed${NC}"
else
    echo -e "${YELLOW}Volumes preserved (data retained)${NC}"
fi

echo ""
echo -e "${GREEN}Environment stopped${NC}"
echo ""
echo "To start again:"
echo -e "  ${BLUE}./scripts/start-local-env.sh${NC}"
echo ""

