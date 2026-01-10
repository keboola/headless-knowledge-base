#!/bin/bash
# =============================================================================
# Build and Push Docker Images
# =============================================================================
# This script builds Docker images and pushes them to Artifact Registry.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
REGION="${REGION:-us-central1}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/knowledge-base"
TAG="${TAG:-latest}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=========================================="
echo "Building and pushing Docker images"
echo "Registry: $REGISTRY"
echo "Tag: $TAG"
echo "=========================================="

# Configure Docker for GCP
echo ""
echo "Configuring Docker for GCP..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

cd "$PROJECT_ROOT"

# Build and push Slack bot image
echo ""
echo "Building Slack bot image..."
docker build \
  -f deploy/docker/Dockerfile.slack \
  -t ${REGISTRY}/slack-bot:${TAG} \
  .

echo "Pushing Slack bot image..."
docker push ${REGISTRY}/slack-bot:${TAG}

# Build and push Jobs image
echo ""
echo "Building Jobs image..."
docker build \
  -f deploy/docker/Dockerfile.jobs \
  -t ${REGISTRY}/jobs:${TAG} \
  .

echo "Pushing Jobs image..."
docker push ${REGISTRY}/jobs:${TAG}

echo ""
echo "=========================================="
echo "Images pushed successfully!"
echo "=========================================="
echo ""
echo "Images:"
echo "  - ${REGISTRY}/slack-bot:${TAG}"
echo "  - ${REGISTRY}/jobs:${TAG}"
