#!/usr/bin/env bash
set -uo pipefail

readonly RUNTIME_DIR=/run/hatsume
readonly PID_FILE="${RUNTIME_DIR}/bot.pid"
readonly RESTART_FILE="${RUNTIME_DIR}/restart.request"

# The source tree is bind-mounted at runtime, so the restart helper lives
# outside the immutable image layer. Keep it discoverable by the bot and by
# every shell/process it launches.
export PATH="/work/hatsume/.container:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"
export TZ="Asia/Shanghai"

# The supplied image archive defaults to UTC. Configure the process and the
# container's libc timezone database at boot so shell, Python, and schedulers
# agree even when the image predates this setting.
if [[ -e "/usr/share/zoneinfo/${TZ}" ]]; then
    ln -sf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    printf '%s\n' "${TZ}" > /etc/timezone
fi

# Keep the historical public command path available for tools and diagnostics.
# This is recreated on every boot because the image archive may predate the
# bind-mounted helper.
ln -sf /work/hatsume/.container/hatsume-restart /usr/local/bin/hatsume-restart

bot_pid=""
terminating=0

forward_signal() {
    terminating=1
    if [[ -n "${bot_pid}" ]] && kill -0 "${bot_pid}" 2>/dev/null; then
        kill -TERM "${bot_pid}" 2>/dev/null || true
    fi
}

trap forward_signal TERM INT
install -d -m 755 "${RUNTIME_DIR}"

while true; do
    rm -f "${RESTART_FILE}"
    cd /work/hatsume || exit 1
    if ! command -v uv &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    ENVIRONMENT=prod /work/hatsume/.venv/bin/python /work/hatsume/.container/run_bot.py &
    bot_pid=$!
    printf '%s\n' "${bot_pid}" > "${PID_FILE}"

    wait "${bot_pid}"
    status=$?
    bot_pid=""
    rm -f "${PID_FILE}"

    if (( terminating )); then
        exit "${status}"
    fi
    if [[ -f "${RESTART_FILE}" ]]; then
        printf 'Restarting Hatsume after an explicit request.\n'
        continue
    fi

    printf 'Hatsume exited with status %s; stopping supervisor.\n' "${status}" >&2
    exit "${status}"
done
