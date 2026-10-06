#!/usr/bin/env bash
set +x
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env.prod"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
IMAGE_NAME="hatsume-space-gui:1.0"
ARCHIVE_PATH="${SCRIPT_DIR}/hatsume-space-gui-image.tar.zst"
[[ -f "$ENV_FILE" ]] || { echo "[HALT] Missing $ENV_FILE." >&2; exit 1; }
[[ -x "$PYTHON_BIN" ]] || { echo "[HALT] Missing Python interpreter: $PYTHON_BIN." >&2; exit 1; }
load_dotenv_value() { "$PYTHON_BIN" - "$ENV_FILE" "$1" <<'PY'
import sys
from dotenv import dotenv_values
value = dotenv_values(sys.argv[1]).get(sys.argv[2])
if not isinstance(value, str) or not value: raise SystemExit(f"[HALT] {sys.argv[2]} is missing or empty")
sys.stdout.write(value)
PY
}
AGENTMAIL_API_KEY="$(load_dotenv_value AGENTMAIL_API_KEY)"
GH_TOKEN="$(load_dotenv_value GH_TOKEN)"
export AGENTMAIL_API_KEY GH_TOKEN
DOCKER_BUILDKIT=1 docker build --secret "id=agentmail_api_key,env=AGENTMAIL_API_KEY" --secret "id=gh_token,env=GH_TOKEN" -t "$IMAGE_NAME" "$SCRIPT_DIR/image"
unset AGENTMAIL_API_KEY GH_TOKEN
docker save "$IMAGE_NAME" | zstd -T0 -19 > "$ARCHIVE_PATH"
printf "%s\n" "$ARCHIVE_PATH"
