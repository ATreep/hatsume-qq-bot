#!/usr/bin/env bash

set +x
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.prod"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
IMAGE_NAME="hatsume-space:1.0"
ARCHIVE_PATH="${SCRIPT_DIR}/hatsume-space-image.tar.zst"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[HALT] Missing ${ENV_FILE}." >&2
    exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "[HALT] Missing ${PYTHON_BIN}; install the project dependencies first." >&2
    exit 1
fi

load_dotenv_value() {
    local key="$1"
    "${PYTHON_BIN}" - "${ENV_FILE}" "${key}" <<'PY'
import sys

from dotenv import dotenv_values

env_file, key = sys.argv[1:]
value = dotenv_values(env_file).get(key)
if not isinstance(value, str) or not value:
    print(f"[HALT] {key} is missing or empty in {env_file}.", file=sys.stderr)
    raise SystemExit(1)
sys.stdout.write(value)
PY
}

CLAWMAIL_API_KEY="$(load_dotenv_value CLAWMAIL_API_KEY)"
DS_API_KEY="$(load_dotenv_value DS_API_KEY)"
GH_TOKEN="$(load_dotenv_value GH_TOKEN)"
export CLAWMAIL_API_KEY DS_API_KEY GH_TOKEN

DOCKER_BUILDKIT=1 docker build \
    --no-cache \
    --build-arg CLAWMAIL_API_KEY="${CLAWMAIL_API_KEY}" \
    --build-arg DS_API_KEY="${DS_API_KEY}" \
    --build-arg GH_TOKEN="${GH_TOKEN}" \
    -t "${IMAGE_NAME}" \
    "${SCRIPT_DIR}/image"

unset CLAWMAIL_API_KEY DS_API_KEY GH_TOKEN
docker save "${IMAGE_NAME}" | zstd -T0 -19 > "${ARCHIVE_PATH}"
