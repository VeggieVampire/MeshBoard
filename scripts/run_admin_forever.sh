#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
LOG_FILE="$APP_DIR/admin.log"
LOCK_FILE="/tmp/meshboard-admin.lock"
CHECK_INTERVAL_SECONDS="${ADMIN_IP_CHECK_INTERVAL_SECONDS:-15}"

cd "$APP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -Is) MeshBoard Admin is already running." >> "$LOG_FILE"
    exit 0
fi

current_ipv4_addresses() {
    if command -v ip >/dev/null 2>&1; then
        ip -o -4 addr show scope global up 2>/dev/null \
            | awk '{ split($4, address, "/"); if (address[1] !~ /^169\.254\./) print address[1] }'
        return
    fi

    hostname -I 2>/dev/null | tr ' ' '\n' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $0 !~ /^169\.254\./ { print }'
}

has_ip() {
    [ -n "$(current_ipv4_addresses | head -n 1)" ]
}

admin_pid=""

stop_admin() {
    if [ -n "$admin_pid" ] && kill -0 "$admin_pid" 2>/dev/null; then
        echo "$(date -Is) No usable IP address; stopping MeshBoard Admin." >> "$LOG_FILE"
        kill "$admin_pid" 2>/dev/null || true
        wait "$admin_pid" 2>/dev/null || true
    fi
    admin_pid=""
}

trap 'stop_admin; exit 0' INT TERM

while true; do
    if ! has_ip; then
        stop_admin
        echo "$(date -Is) No usable IP address; MeshBoard Admin is down." >> "$LOG_FILE"
        sleep "$CHECK_INTERVAL_SECONDS"
        continue
    fi

    if [ -z "$admin_pid" ] || ! kill -0 "$admin_pid" 2>/dev/null; then
        echo "$(date -Is) Starting MeshBoard Admin on IP(s): $(current_ipv4_addresses | paste -sd ' ' -)." >> "$LOG_FILE"
        "$APP_DIR/.venv/bin/python" "$APP_DIR/admin_server.py" >> "$LOG_FILE" 2>&1 &
        admin_pid="$!"
    fi

    sleep "$CHECK_INTERVAL_SECONDS"
done
