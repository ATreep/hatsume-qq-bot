#!/usr/bin/env bash
# !! Do NOT execute this script manually.

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="${1:-}"

if [[ "${CONTAINER_NAME}" != "hatsume-containerization" ]]; then
    echo "[HALT] Invalid container name."
    exit 2
fi

IMAGE_NAME="hatsume-space:1.0"

if ! docker info > /dev/null 2>&1; then
    echo "[HALT] Docker not running."
    exit 1
fi

if ! docker image inspect "${IMAGE_NAME}" > /dev/null 2>&1; then
    zstd -d hatsume-space-image.tar.zst -c | docker load > /dev/null
fi

if ! docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker create \
        --name "${CONTAINER_NAME}" \
        --network shared-net \
        --workdir /work \
        --env "HOME=/root" \
        --env "PATH=/work/hatsume/.container:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        --env "TZ=Asia/Shanghai" \
        --mount "type=bind,src=$(cd -- "${SCRIPT_DIR}/../../../.." && pwd),dst=/work/hatsume" \
        --entrypoint /work/hatsume/.container/supervise.sh \
        -it \
        "${IMAGE_NAME}" > /dev/null
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    docker start "${CONTAINER_NAME}" > /dev/null
fi
docker exec -i "${CONTAINER_NAME}" bash -s
