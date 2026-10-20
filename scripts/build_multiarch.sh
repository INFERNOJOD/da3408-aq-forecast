#!/usr/bin/env bash
# Build and push the four service images for amd64 and arm64 to Docker Hub.
# Needs: docker login, a buildx builder (docker buildx create --use) and QEMU
# emulation for the other architecture. Usage: DOCKERHUB_USER=me scripts/build_multiarch.sh
set -euo pipefail
: "${DOCKERHUB_USER:?set DOCKERHUB_USER}"
cd "$(dirname "$0")/.."
for svc in frontend backend model_server pipeline; do
  name="aq-${svc//_/-}"
  docker buildx build --platform linux/amd64,linux/arm64 \
    -f "docker/${svc}/Dockerfile" -t "${DOCKERHUB_USER}/${name}:latest" --push .
  docker buildx imagetools inspect "${DOCKERHUB_USER}/${name}:latest"
done
