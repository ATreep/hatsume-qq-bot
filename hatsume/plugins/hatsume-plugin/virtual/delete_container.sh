#!/usr/bin/env bash

set -e

CONTAINER_NAME="hatsume-space-kali"

if ! docker info > /dev/null 2>&1; then
    echo "[HALT] Docker not running."
    exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker rm -f "${CONTAINER_NAME}"
fi