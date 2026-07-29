#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_NAME="nb-hatsume"
SESSION_TARGET="=${SESSION_NAME}"

cd "$SCRIPT_DIR" || exit 1

if tmux has-session -t "$SESSION_TARGET" 2>/dev/null; then
    tmux kill-session -t "$SESSION_TARGET" || exit 1
fi

tmux new-session -d -s "$SESSION_NAME" -c "$SCRIPT_DIR" \
    "ENVIRONMENT=prod nb run" || exit 1

printf 'Enter the tmux session with:\n  tmux attach-session -t %s\n' "$SESSION_NAME"
