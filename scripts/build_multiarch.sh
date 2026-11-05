#!/usr/bin/env bash
# Build and push the service images for amd64 and arm64 to Docker Hub.
# Needs: docker login, a builder that can build multi-platform images (the
# default builder with the containerd image store, or docker buildx create
# --use) and QEMU emulation for the other architecture.
#
#   DOCKERHUB_USER=me scripts/build_multiarch.sh
#   DOCKERHUB_USER=me SERVICES="frontend" scripts/build_multiarch.sh   # one image
#
# Each image gets two tags: latest and VERSION (default: the version in
# pyproject.toml). On a small disk, build one image per call and run
# "docker buildx prune -f" in between.
set -euo pipefail
: "${DOCKERHUB_USER:?set DOCKERHUB_USER}"
cd "$(dirname "$0")/.."
VERSION="${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)}"
# model_server comes before mlflow, whose image is built on top of it.
SERVICES="${SERVICES:-frontend backend model_server mlflow pipeline}"
for svc in $SERVICES; do
  name="aq-${svc//_/-}"
  docker buildx build --platform linux/amd64,linux/arm64 \
    --build-arg "BASE=${DOCKERHUB_USER}/aq-model-server:latest" \
    -f "docker/${svc}/Dockerfile" \
    -t "${DOCKERHUB_USER}/${name}:latest" -t "${DOCKERHUB_USER}/${name}:${VERSION}" \
    --push .
  docker buildx imagetools inspect "${DOCKERHUB_USER}/${name}:${VERSION}"
done
