#!/bin/bash
# Build the swecli/resolver Docker image

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="swecli/resolver:latest"

echo "Building $IMAGE_NAME..."
docker build -t "$IMAGE_NAME" -f "$SCRIPT_DIR/Dockerfile.resolver" "$SCRIPT_DIR"

echo ""
echo "Image built successfully: $IMAGE_NAME"
echo "Size: $(docker images --format '{{.Size}}' $IMAGE_NAME)"
