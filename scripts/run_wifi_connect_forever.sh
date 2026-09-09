#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
CONFIG_FILE="${WIFI_CONFIG_FILE:-$APP_DIR/wifi_remote.conf}"
LOG_FILE="${WIFI_LOG_FILE:-$APP_DIR/wifi-connect.log}"
LOCK_FILE="/tmp/meshboard-wifi-connect.lock"

DEFAULT_INTERVAL=60
NMCLI=(nmcli)

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

configure_nmcli_command() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        NMCLI=(nmcli)
    elif command -v sudo >/dev/null 2>&1 && sudo -n nmcli general status >/dev/null 2>&1; then
        NMCLI=(sudo -n nmcli)
    else
        NMCLI=(nmcli)
    fi
}

wifi_connected() {
    local interface="$1"
    "${NMCLI[@]}" -t -f DEVICE,STATE device status 2>/dev/null | grep -q "^${interface}:connected$"
}

active_ssid() {
    local interface="$1"
    "${NMCLI[@]}" -t -f ACTIVE,SSID device wifi list ifname "$interface" 2>/dev/null | awk -F: '$1 == "yes" {print $2; exit}'
}

ssid_visible() {
    local interface="$1"
    local ssid="$2"
    "${NMCLI[@]}" -t -f SSID device wifi list ifname "$interface" 2>/dev/null | awk -F: -v target="$ssid" '$1 == target {found = 1} END {exit !found}'
}

wifi_interface() {
    local configured="$1"
    if [[ -n "$configured" && "$configured" != "auto" ]]; then
        printf '%s' "$configured"
        return
    fi
    "${NMCLI[@]}" -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2 == "wifi" {print $1; exit}'
}

connect_hotspot() {
    local index="$1"
    local ssid="$2"
    local psk="$3"
    local interface="$4"
    local connection_name="$5"
    local only_when_offline="$6"
    local prefer_visible_hotspot="$7"
    local current_ssid connection_label

    connection_label="${connection_name}-${index}"
    current_ssid="$(active_ssid "$interface")"
    if [[ "$current_ssid" == "$ssid" ]]; then
        log "WiFi already connected on $interface to configured hotspot '$ssid'."
        return 0
    fi

    if truthy "$only_when_offline" && wifi_connected "$interface"; then
        if truthy "$prefer_visible_hotspot" && ssid_visible "$interface" "$ssid"; then
            log "Configured hotspot '$ssid' is visible; switching from ${current_ssid:-current WiFi}."
        else
            log "WiFi already connected on $interface${current_ssid:+ to $current_ssid}; configured hotspot '$ssid' not visible, skipping."
            return 1
        fi
    fi

    log "Trying WiFi hotspot '$ssid' on $interface."
    if "${NMCLI[@]}" connection show "$connection_label" >/dev/null 2>&1; then
        "${NMCLI[@]}" connection modify "$connection_label" \
            connection.autoconnect yes \
            802-11-wireless.ssid "$ssid" \
            wifi-sec.key-mgmt wpa-psk \
            wifi-sec.psk "$psk" >> "$LOG_FILE" 2>&1
        "${NMCLI[@]}" connection up "$connection_label" ifname "$interface" >> "$LOG_FILE" 2>&1 || {
            log "Connection attempt failed for hotspot '$ssid'."
            return 1
        }
    else
        "${NMCLI[@]}" device wifi connect "$ssid" password "$psk" ifname "$interface" name "$connection_label" >> "$LOG_FILE" 2>&1 || {
            log "Connection attempt failed for hotspot '$ssid'."
            return 1
        }
    fi
    return 0
}

connect_once() {
    local enabled configured_interface interface connection_name only_when_offline prefer_visible_hotspot index slot_enabled ssid psk tried_any

    enabled="$(read_config_value ENABLED false)"
    if ! truthy "$enabled"; then
        return
    fi

    configured_interface="$(read_config_value INTERFACE auto)"
    interface="$(wifi_interface "$configured_interface")"
    connection_name="$(read_config_value CONNECTION_NAME MeshBoardRemoteHotspot)"
    only_when_offline="$(read_config_value CONNECT_ONLY_WHEN_OFFLINE true)"
    prefer_visible_hotspot="$(read_config_value PREFER_VISIBLE_HOTSPOT true)"

    if [[ -z "$interface" ]]; then
        log "ENABLED is true, but no WiFi interface is visible to NetworkManager."
        return
    fi

    "${NMCLI[@]}" radio wifi on >> "$LOG_FILE" 2>&1 || true
    "${NMCLI[@]}" device wifi rescan ifname "$interface" >> "$LOG_FILE" 2>&1 || true

    tried_any=false
    for index in 1 2 3 4 5; do
        slot_enabled="$(read_config_value "HOTSPOT_${index}_ENABLED")"
        ssid="$(read_config_value "HOTSPOT_${index}_SSID")"
        psk="$(read_config_value "HOTSPOT_${index}_PSK")"
        if [[ -z "$ssid" && "$index" == "1" ]]; then
            ssid="$(read_config_value SSID)"
            psk="$(read_config_value PSK)"
            slot_enabled="$(read_config_value HOTSPOT_1_ENABLED true)"
        fi
        if ! truthy "${slot_enabled:-false}"; then
            continue
        fi
        if [[ -z "$ssid" || -z "$psk" ]]; then
            log "Hotspot $index is enabled, but SSID or PSK is empty."
            continue
        fi
        tried_any=true
        if connect_hotspot "$index" "$ssid" "$psk" "$interface" "$connection_name" "$only_when_offline" "$prefer_visible_hotspot"; then
            return
        fi
    done

    if [[ "$tried_any" == "false" ]]; then
        log "ENABLED is true, but no enabled hotspots are configured."
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
    configure_nmcli_command
    connect_once || log "Unexpected WiFi helper error."
    sleep "${interval:-$DEFAULT_INTERVAL}"
done
