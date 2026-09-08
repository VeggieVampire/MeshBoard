#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
LOG_FILE="$APP_DIR/listener.log"
LOCK_FILE="/tmp/meshboard.lock"

cd "$APP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -Is) MeshBoard is already running." >> "$LOG_FILE"
    exit 0
fi

while true; do
    echo "$(date -Is) Starting MeshBoard." >> "$LOG_FILE"
    "$APP_DIR/.venv/bin/python" "$APP_DIR/bbs_system.py" >> "$LOG_FILE" 2>&1 || true
    echo "$(date -Is) MeshBoard exited; restarting in 10 seconds." >> "$LOG_FILE"
    sleep 10
done
