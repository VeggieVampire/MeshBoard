#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
CONFIG_FILE="${WIFI_CONFIG_FILE:-$APP_DIR/wifi_remote.conf}"
LOG_FILE="${WIFI_LOG_FILE:-$APP_DIR/wifi-connect.log}"
LOCK_FILE="/tmp/meshboard-wifi-connect.lock"

DEFAULT_INTERVAL=60

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "$(date -Is) $*" >> "$LOG_FILE"
}

read_config_value() {
    local key="$1"
    local default_value="${2:-}"
    local line value

    if [[ ! -f "$CONFIG_FILE" ]]; then
        printf '%s' "$default_value"
        return
    fi

    line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$CONFIG_FILE" | tail -n 1 || true)"
    if [[ -z "$line" ]]; then
        printf '%s' "$default_value"
        return
    fi

    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
}

truthy() {
    case "${1,,}" in
        1|true|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

wifi_connected() {
    local interface="$1"
    nmcli -t -f DEVICE,STATE device status 2>/dev/null | grep -q "^${interface}:connected$"
}

active_ssid() {
    local interface="$1"
    nmcli -t -f ACTIVE,SSID device wifi list ifname "$interface" 2>/dev/null | awk -F: '$1 == "yes" {print $2; exit}'
}

wifi_interface() {
    local configured="$1"
    if [[ -n "$configured" && "$configured" != "auto" ]]; then
        printf '%s' "$configured"
        return
    fi
    nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2 == "wifi" {print $1; exit}'
}

connect_once() {
    local enabled ssid psk configured_interface interface connection_name only_when_offline current_ssid

    enabled="$(read_config_value ENABLED false)"
    if ! truthy "$enabled"; then
        return
    fi

    ssid="$(read_config_value SSID)"
    psk="$(read_config_value PSK)"
    configured_interface="$(read_config_value INTERFACE auto)"
    interface="$(wifi_interface "$configured_interface")"
    connection_name="$(read_config_value CONNECTION_NAME MeshBoardRemoteHotspot)"
    only_when_offline="$(read_config_value CONNECT_ONLY_WHEN_OFFLINE true)"

    if [[ -z "$ssid" || -z "$psk" ]]; then
        log "ENABLED is true, but SSID or PSK is empty."
        return
    fi

    if [[ -z "$interface" ]]; then
        log "ENABLED is true, but no WiFi interface is visible to NetworkManager."
        return
    fi

    if truthy "$only_when_offline" && wifi_connected "$interface"; then
        current_ssid="$(active_ssid "$interface")"
        log "WiFi already connected on $interface${current_ssid:+ to $current_ssid}; skipping hotspot."
        return
    fi

    log "Trying WiFi hotspot '$ssid' on $interface."
    nmcli radio wifi on >> "$LOG_FILE" 2>&1 || true
    nmcli device wifi rescan ifname "$interface" >> "$LOG_FILE" 2>&1 || true

    if nmcli connection show "$connection_name" >/dev/null 2>&1; then
        nmcli connection modify "$connection_name" \
            connection.autoconnect yes \
            802-11-wireless.ssid "$ssid" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk "$psk" >> "$LOG_FILE" 2>&1
        nmcli connection up "$connection_name" ifname "$interface" >> "$LOG_FILE" 2>&1 || log "Connection attempt failed."
    else
        nmcli device wifi connect "$ssid" password "$psk" ifname "$interface" name "$connection_name" >> "$LOG_FILE" 2>&1 || log "Connection attempt failed."
    fi
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "WiFi retry helper is already running."
    exit 0
fi

log "Starting WiFi retry helper with config $CONFIG_FILE."

while true; do
    interval="$(read_config_value CHECK_INTERVAL_SECONDS "$DEFAULT_INTERVAL")"
    connect_once || log "Unexpected WiFi helper error."
    sleep "${interval:-$DEFAULT_INTERVAL}"
done
