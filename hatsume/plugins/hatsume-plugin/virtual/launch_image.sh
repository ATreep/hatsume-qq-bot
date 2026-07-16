#!/usr/bin/env bash
# !! Do NOT execute this script manually.

set -e

CONTAINER_NAME="hatsume-space-kali"

IMAGE_NAME="hatsume-space-kali:1.0"

# Argument parsing
MODE=""
HOST_PATH=""

if ! docker info > /dev/null 2>&1; then
    echo "[HALT] Docker not running."
    exit 1
fi

if ! docker image inspect "${IMAGE_NAME}" > /dev/null 2>&1; then
    zstd -d kali-cmd-image.tar.zst -c | docker load > /dev/null
fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    # Create the container if not exists
    docker create \
        --name "${CONTAINER_NAME}" \
        -it \
        "${IMAGE_NAME}" > /dev/null
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker start "${CONTAINER_NAME}" > /dev/null
fi
docker exec -i "${CONTAINER_NAME}" bash -s < $(pwd)/script.sh
