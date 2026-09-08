#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/MeshBoard}"
SERVICE_NAME="${SERVICE_NAME:-meshboard.service}"

if [[ ! -f "bbs_system.py" ]]; then
    echo "Run this script from the MeshBoard repository root."
    exit 1
fi

sudo apt update
sudo apt install -y python3-venv python3-pip python3-serial git rsync
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install meshtastic

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
        ./ "$APP_DIR/"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install meshtastic

mkdir -p "$HOME/.config/systemd/user"
cp "$APP_DIR/systemd/meshboard.service" "$HOME/.config/systemd/user/$SERVICE_NAME"
if [[ "$APP_DIR" != "$HOME/MeshBoard" ]]; then
    sed -i "s|WorkingDirectory=%h/MeshBoard|WorkingDirectory=$APP_DIR|" "$HOME/.config/systemd/user/$SERVICE_NAME"
    sed -i "s|ExecStart=%h/MeshBoard/.venv/bin/python %h/MeshBoard/bbs_system.py|ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bbs_system.py|" "$HOME/.config/systemd/user/$SERVICE_NAME"
fi

sudo usermod -aG dialout "$(id -un)" || true
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"

echo "Installed MeshBoard to $APP_DIR."
echo "Run 'cd $APP_DIR && .venv/bin/python setup.py' to detect USB, or edit meshtastic_config.json for WiFi/Bluetooth."
echo "Then start with: systemctl --user start $SERVICE_NAME"
