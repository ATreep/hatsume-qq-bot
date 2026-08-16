#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly CONTAINER_NAME="hatsume-containerization"
readonly LEGACY_CONTAINER_NAME="hatsume-space"
readonly NETWORK_NAME="${HATSUME_NETWORK_NAME:-shared-net}"
readonly IMAGE_NAME="${HATSUME_IMAGE_NAME:-hatsume-space:1.0}"
readonly IMAGE_ARCHIVE="${HATSUME_IMAGE_ARCHIVE:-/Users/treep/Dev/qqbot/hatsume/hatsume/plugins/hatsume-plugin/virtual/hatsume-space-image.tar.zst}"
readonly CONTAINER_WORKDIR="/work/hatsume"
readonly CONTAINER_DEFAULT_WORKDIR="/work"
readonly CONTAINER_HOME="/root"
readonly CONTAINER_ENTRYPOINT="${CONTAINER_WORKDIR}/.container/supervise.sh"
readonly CONTAINER_PATH="${CONTAINER_WORKDIR}/.container:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
readonly CONTAINER_TIMEZONE="Asia/Shanghai"
readonly BOT_PID_FILE="/run/hatsume/bot.pid"
readonly BOT_PORT="${HATSUME_BOT_PORT:-6999}"
readonly START_TIMEOUT_SECONDS="${HATSUME_START_TIMEOUT_SECONDS:-60}"

log() {
    printf '[hatsume-containerization] %s\n' "$*"
}

fail() {
    printf '[hatsume-containerization] ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup_on_error() {
    local status=$?
    if ((status != 0)); then
        printf '[hatsume-containerization] startup failed (exit %s)\n' "$status" >&2
        if command -v docker >/dev/null 2>&1 \
            && docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
            docker logs --tail 80 "${CONTAINER_NAME}" >&2 || true
        fi
    fi
}

bot_is_ready() {
    docker exec "${CONTAINER_NAME}" sh -c '
        pid_file=$1
        port=$2
        test -r "${pid_file}" || exit 1
        bot_pid=$(cat "${pid_file}")
        kill -0 "${bot_pid}" 2>/dev/null || exit 1
        ss -H -ltn "sport = :${port}" | grep -q .
    ' sh "${BOT_PID_FILE}" "${BOT_PORT}" >/dev/null 2>&1
}

trap cleanup_on_error EXIT

command -v docker >/dev/null 2>&1 || fail 'docker command is required.'
command -v zstd >/dev/null 2>&1 || fail 'zstd command is required.'
docker info >/dev/null 2>&1 || fail 'Docker is not running or is not accessible.'

[[ "${BOT_PORT}" =~ ^[1-9][0-9]*$ ]] && ((BOT_PORT <= 65535)) \
    || fail 'HATSUME_BOT_PORT must be an integer between 1 and 65535.'
[[ "${START_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] \
    || fail 'HATSUME_START_TIMEOUT_SECONDS must be a positive integer.'

[[ -d "${SCRIPT_DIR}" ]] || fail "Project directory does not exist: ${SCRIPT_DIR}"
[[ -f "${IMAGE_ARCHIVE}" ]] || fail "Image archive does not exist: ${IMAGE_ARCHIVE}"
[[ -x "${SCRIPT_DIR}/.container/supervise.sh" ]] || fail "Missing executable supervisor: ${SCRIPT_DIR}/.container/supervise.sh"

log "Loading image archive: ${IMAGE_ARCHIVE}"
zstd -d -c "${IMAGE_ARCHIVE}" | docker load
docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1 \
    || fail "Loaded archive does not provide expected image ${IMAGE_NAME}."

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    log "Creating Docker network: ${NETWORK_NAME}"
    docker network create "${NETWORK_NAME}" >/dev/null
else
    log "Using Docker network: ${NETWORK_NAME}"
fi

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log "Removing existing container: ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

if docker container inspect "${LEGACY_CONTAINER_NAME}" >/dev/null 2>&1; then
    log "Removing legacy container: ${LEGACY_CONTAINER_NAME}"
    docker rm -f "${LEGACY_CONTAINER_NAME}" >/dev/null
fi

log "Creating container: ${CONTAINER_NAME}"
docker create \
    --name "${CONTAINER_NAME}" \
    --network "${NETWORK_NAME}" \
    --workdir "${CONTAINER_DEFAULT_WORKDIR}" \
    --env "HOME=${CONTAINER_HOME}" \
    --env "PATH=${CONTAINER_PATH}" \
    --env "TZ=${CONTAINER_TIMEZONE}" \
    --mount "type=bind,src=${SCRIPT_DIR},dst=${CONTAINER_WORKDIR}" \
    --entrypoint "${CONTAINER_ENTRYPOINT}" \
    -it \
    "${IMAGE_NAME}" >/dev/null

log "Starting container and bot supervisor"
docker start "${CONTAINER_NAME}" >/dev/null

deadline=$((SECONDS + START_TIMEOUT_SECONDS))
while ((SECONDS < deadline)); do
    if bot_is_ready; then
        break
    fi
    sleep 1
done

bot_is_ready \
    || fail "Container started but bot did not listen on port ${BOT_PORT} within ${START_TIMEOUT_SECONDS}s."

docker exec "${CONTAINER_NAME}" sh -lc \
    "command -v hatsume-restart >/dev/null 2>&1 && test -x '${CONTAINER_ENTRYPOINT}'" \
    || fail 'Container started but hatsume-restart or the supervisor is unavailable.'

log "Container is running: ${CONTAINER_NAME}"
log "Network: ${NETWORK_NAME}"
log "Mount: ${SCRIPT_DIR} -> ${CONTAINER_WORKDIR}"
log "PID 1: ${CONTAINER_ENTRYPOINT}"
log "Bot PID: $(docker exec "${CONTAINER_NAME}" sh -lc "cat '${BOT_PID_FILE}'")"
log "Bot port: ${BOT_PORT}"
