#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
SERVICE_NAME="${SERVICE_NAME:-meshboard.service}"
ADMIN_USERNAME="${MESHBOARD_ADMIN_USERNAME:-sysop}"
ADMIN_PASSWORD="${MESHBOARD_ADMIN_PASSWORD:-}"
ADMIN_CREDENTIALS_FILE="${MESHBOARD_ADMIN_CREDENTIALS_FILE:-$APP_DIR/admin_credentials.txt}"

if [[ ! -f "bbs_system.py" ]]; then
    echo "Run this script from the MeshBoard repository root."
    exit 1
fi

sudo apt update
sudo apt install -y python3-venv python3-pip python3-serial git rsync cron
sudo systemctl enable --now cron || true

mkdir -p "$APP_DIR"
SOURCE_DIR="$(pwd -P)"
TARGET_DIR="$(cd "$APP_DIR" && pwd -P)"
if [[ "$SOURCE_DIR" != "$TARGET_DIR" ]]; then
    rsync -a --delete \
        --exclude ".git" \
        --exclude "__pycache__" \
        --exclude "*.pyc" \
        --exclude ".venv" \
        --exclude "meshboard.db" \
        --exclude "meshtastic_config.json" \
        --exclude "admin_config.json" \
        --exclude "wifi_remote.conf" \
        --exclude "wifi-connect.log" \
        ./ "$APP_DIR/"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install meshtastic

if [[ ! -f "$APP_DIR/meshtastic_config.json" ]]; then
    (
        cd "$APP_DIR"
        "$APP_DIR/.venv/bin/python" setup.py || true
    )
fi
if [[ ! -f "$APP_DIR/meshtastic_config.json" ]]; then
    (
        cd "$APP_DIR"
        "$APP_DIR/.venv/bin/python" - <<'PY'
from config import DEFAULT_CONFIG, save_config

save_config(DEFAULT_CONFIG)
print("Created default meshtastic_config.json.")
PY
    )
fi

if [[ ! -f "$APP_DIR/wifi_remote.conf" && -f "$APP_DIR/wifi_remote.conf.example" ]]; then
    cp "$APP_DIR/wifi_remote.conf.example" "$APP_DIR/wifi_remote.conf"
    chmod 600 "$APP_DIR/wifi_remote.conf"
    echo "Created local $APP_DIR/wifi_remote.conf from wifi_remote.conf.example."
fi

"$APP_DIR/.venv/bin/python" - "$APP_DIR" "$ADMIN_USERNAME" "$ADMIN_PASSWORD" "$ADMIN_CREDENTIALS_FILE" <<'PY'
import json
import os
import secrets
import sys

app_dir, username, password, credentials_file = sys.argv[1:5]
sys.path.insert(0, app_dir)

from admin_server import make_password_hash

config_path = os.path.join(app_dir, "admin_config.json")
example_path = os.path.join(app_dir, "admin_config.json.example")

if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
else:
    with open(example_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

needs_password_hash = not config.get("password_hash")
generated_password = False
if needs_password_hash and not password:
    password = secrets.token_urlsafe(12)
    generated_password = True

changed = False
if not config.get("enabled"):
    config["enabled"] = True
    changed = True
if config.get("username") != username:
    config["username"] = username
    changed = True
if needs_password_hash:
    config["password_hash"] = make_password_hash(password)
    changed = True
if not config.get("session_secret") or config.get("session_secret") == "change-this-random-secret":
    config["session_secret"] = secrets.token_urlsafe(32)
    changed = True

if changed or not os.path.exists(config_path):
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4)
        handle.write("\n")
    os.chmod(config_path, 0o600)

if generated_password:
    with open(credentials_file, "w", encoding="utf-8") as handle:
        handle.write(f"MeshBoard Admin\nURL: http://<pi-ip>:8080\nUsername: {username}\nPassword: {password}\n")
    os.chmod(credentials_file, 0o600)
    print(f"Generated admin login saved to {credentials_file}")
elif needs_password_hash:
    print("Admin password was supplied with MESHBOARD_ADMIN_PASSWORD.")
else:
    print("Existing admin password hash preserved.")
PY

mkdir -p "$HOME/.config/systemd/user"
cp "$APP_DIR/systemd/meshboard.service" "$HOME/.config/systemd/user/$SERVICE_NAME"
if [[ "$APP_DIR" != "$HOME/MeshBoard" ]]; then
    sed -i "s|WorkingDirectory=%h/MeshBoard|WorkingDirectory=$APP_DIR|" "$HOME/.config/systemd/user/$SERVICE_NAME"
    sed -i "s|ExecStart=%h/MeshBoard/scripts/run_meshboard_forever.sh|ExecStart=$APP_DIR/scripts/run_meshboard_forever.sh|" "$HOME/.config/systemd/user/$SERVICE_NAME"
fi

sudo usermod -aG dialout "$(id -un)" || true
systemctl --user daemon-reload || true
systemctl --user enable "$SERVICE_NAME" || true
systemctl --user start "$SERVICE_NAME" || true

chmod +x "$APP_DIR/scripts/run_meshboard_forever.sh" "$APP_DIR/scripts/run_admin_forever.sh" "$APP_DIR/scripts/run_wifi_connect_forever.sh"

install_cron_entry() {
    local marker="$1"
    local command="$2"
    local current

    current="$(crontab -l 2>/dev/null || true)"
    if ! printf '%s\n' "$current" | grep -Fq "$marker"; then
        {
            printf '%s\n' "$current"
            printf '@reboot %s # %s\n' "$command" "$marker"
        } | crontab -
    fi
}

quote_shell() {
    local value="$1"
    printf "'%s'" "${value//\'/\'\\\'\'}"
}

quoted_app_dir="$(quote_shell "$APP_DIR")"
install_cron_entry "meshboard-bbs" "APP_DIR=$quoted_app_dir $quoted_app_dir/scripts/run_meshboard_forever.sh"
install_cron_entry "meshboard-admin" "APP_DIR=$quoted_app_dir $quoted_app_dir/scripts/run_admin_forever.sh"
install_cron_entry "meshboard-wifi" "APP_DIR=$quoted_app_dir $quoted_app_dir/scripts/run_wifi_connect_forever.sh"

nohup env APP_DIR="$APP_DIR" "$APP_DIR/scripts/run_meshboard_forever.sh" >/dev/null 2>&1 &
nohup env APP_DIR="$APP_DIR" "$APP_DIR/scripts/run_admin_forever.sh" >/dev/null 2>&1 &
nohup env APP_DIR="$APP_DIR" "$APP_DIR/scripts/run_wifi_connect_forever.sh" >/dev/null 2>&1 &

echo "Installed MeshBoard to $APP_DIR."
echo "MeshBoard, the admin website, and the WiFi helper were installed at boot and started now."
echo "Edit $APP_DIR/wifi_remote.conf later if you want the Pi to join a phone hotspot."
