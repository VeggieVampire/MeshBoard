# MeshBoard

Text-based Bulletin Board System (BBS) designed to run over a Meshtastic network.

MeshBoard runs on a Raspberry Pi or Linux host connected to a Meshtastic radio by USB serial, WiFi/TCP, or Bluetooth/BLE. Users send direct-message text commands to the MeshBoard node; MeshBoard replies with menus, games, store-and-forward mail, and GPS/location features without requiring internet access.

## What It Does

- Direct-message-only BBS commands. Broadcast text packets are ignored.
- Menu navigation with `top`, `cd ..`, and numbered choices.
- Persistent SQLite store-and-forward mail keyed by Meshtastic node ID.
- Live GPS-aware Location tools using the sender node's latest Meshtastic position.
- Saved location notes, nearby note lookup, and Hot Cold GPS gameplay.
- USB serial first, with WiFi/TCP and Bluetooth/BLE fallback.
- Chunked replies for long Meshtastic text responses.
- ACK-requesting replies tagged with the incoming packet ID so clients can correlate responses.

## Architecture

- `interface.py` owns the Meshtastic connection, direct-message filtering, incoming text/position packets, and outgoing replies.
- `bbs_system.py` owns per-node sessions, dynamic module loading, unread mail notices, and latest in-memory GPS state.
- `database.py` initializes and accesses `meshboard.db`.
- `location_service.py` contains GPS freshness and Haversine helpers.
- `modules/Mail/` provides inbox, send, sent mail, address list, and archive flows.
- `modules/Location/` provides What's Here, Leave Something Here, Nearby, My Saved Locations, and Hot Cold access.
- `modules/Games/` remains dynamically loaded as the Games submenu.

## Install On A Pi Or OSMC Host

These steps install as whichever Linux user runs them. The default app directory is `~/MeshBoard`, and the service is a user-level systemd service using `%h`, so it does not depend on a specific username.

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip python3-serial
git clone https://github.com/VeggieVampire/MeshBoard.git
cd MeshBoard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install meshtastic
```

Create config:

```bash
.venv/bin/python setup.py
```

For a USB radio, prefer a stable path from `/dev/serial/by-id/` instead of `/dev/ttyUSB0`.

Example `meshtastic_config.json`:

```json
{
    "connection_type": "auto",
    "device_path": "/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0",
    "wifi": {
        "hostname": "",
        "port": 4403
    },
    "bluetooth": {
        "address": ""
    },
    "gps": {
        "freshness_seconds": 300,
        "whats_here_radius_meters": 100,
        "nearby_radius_meters": 1000,
        "log_raw_history": false
    },
    "meshtastic": {
        "max_text_length": 180,
        "chunk_delay_seconds": 0.5,
        "reconnect_delay_seconds": 10
    },
    "database": {
        "path": "meshboard.db"
    }
}
```

Install the user service:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/meshboard.service ~/.config/systemd/user/meshboard.service
systemctl --user daemon-reload
systemctl --user enable meshboard.service
systemctl --user start meshboard.service
systemctl --user status meshboard.service
```

View logs:

```bash
tail -f listener.log
```

If you want MeshBoard to start before that user logs in, enable linger:

```bash
sudo loginctl enable-linger "$USER"
```

USB serial usually requires access to the serial device:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing groups.

## Optional Installer Script

From the repo root:

```bash
scripts/install_pi.sh
```

By default it installs to `~/MeshBoard`. Override the destination with:

```bash
APP_DIR="$HOME/apps/MeshBoard" scripts/install_pi.sh
```

## Connection Options

Set `connection_type` to:

- `auto`: try USB serial, then WiFi/TCP, then Bluetooth/BLE.
- `serial`: prefer USB serial, then fall back to the others.
- `wifi`: prefer WiFi/TCP, then fall back to the others.
- `bluetooth`: prefer Bluetooth/BLE, then fall back to the others.

WiFi/TCP example:

```json
"connection_type": "wifi",
"wifi": {
    "hostname": "192.168.1.50",
    "port": 4403
}
```

Bluetooth/BLE example:

```json
"connection_type": "bluetooth",
"bluetooth": {
    "address": "AA:BB:CC:DD:EE:FF"
}
```

On Linux, Bluetooth/BLE may require BlueZ support and local pairing. WiFi/TCP is usually the most reliable non-USB option for an unattended Pi when the radio and Pi stay on the same network.

## Meshtastic Radio Setup

MeshBoard assumes the Pi radio and user radios share the same Meshtastic channel and LoRa settings.

After flashing a user radio, set the LoRa region. A radio with `region: UNSET` may connect over USB but fail to behave correctly on RF:

```bash
python -m meshtastic --port COM5 --set lora.region US --wait-to-disconnect 15
python -m meshtastic --port COM5 --get lora.region
```

Use contact URLs to seed direct-message contacts after a flash:

```bash
python -m meshtastic --port COM5 --contact-qr '!433bed54' --contact-verified
python -m meshtastic --port COM5 --add-contact "https://meshtastic.org/v/#..."
```

If direct messages return `NO_CHANNEL`, add fresh contact URLs on both radios and confirm both radios use the same channel, region, and modem preset.

## How To Use MeshBoard

MeshBoard commands must be sent as direct messages to the MeshBoard node. Do not use broadcast for MeshBoard commands.

From the Meshtastic web client:

1. Connect to your local radio.
2. Open the contact or node for the MeshBoard radio.
3. Send `top` as a direct message.
4. MeshBoard replies with the main menu.

From the CLI:

```bash
python -m meshtastic --port COM5 --sendtext "top" --dest '!9ea0cc08' --ch-index 0
```

Main menu:

```text
Main Menu:
1. Location
2. Games
3. Mail
Choose an option (e.g., '1').
'top' to go to Main Menu, 'cd ..' to go back one menu.
```

Common commands:

- `top`: return to the main menu.
- `cd ..`: go back one menu.
- `1`, `2`, `3`: choose menu items.
- `NAME Alice`: set your display name for Mail/address lists.

Mail:

- Open `Mail` from the main menu.
- Use Inbox to read stored messages.
- Use Send Message to send a stored message to another node ID.
- Messages persist in `meshboard.db`.

Location:

- Requires the sender's node to provide GPS/position packets.
- What's Here shows saved notes near your current node position.
- Leave Something Here saves a note at your current node position.
- Nearby lists saved notes sorted by distance.
- Hot Cold uses your latest live GPS position.

## What Was Tested

The working OSMC deployment was installed to `/home/osmc/MeshBoard` as a user systemd service. The MeshBoard radio was connected over USB at a stable `/dev/serial/by-id/...` path.

Tested MeshBoard node:

- Long name: `MacnCheeseNoodles`
- Short name: `mcno`
- Node ID: `!9ea0cc08`
- Region: `US`
- Modem preset: `LONG_FAST`
- Hop limit: `7`

Tested Windows node:

- Long name: `Meshtastic ed54`
- Short name: `ed54`
- Node ID: `!433bed54`
- Firmware: `2.7.26.54e0d8d`

The Windows node was reflashed, had `lora.region` corrected to `US`, and fresh contact URLs were added on both radios. Direct DM then returned ACKs and MeshBoard replies with the original packet ID.

## Troubleshooting

- If the GUI says "still waiting for a reply," reconnect the USB serial session and try a direct message again.
- If "Last Heard" is unknown, wait for NodeInfo or add a contact URL. Direct DM can work before Last Heard is populated.
- If direct DM returns `NO_CHANNEL`, refresh contacts on both radios and confirm matching channel, region, and modem preset.
- If USB is busy, close the Meshtastic web client before running CLI commands against the same COM port.
- If MeshBoard is not responding, check `systemctl --user status meshboard.service` and `tail -f listener.log`.

## Manual Run

```bash
cd MeshBoard
python3 -m venv .venv
.venv/bin/python -m pip install meshtastic
.venv/bin/python setup.py
.venv/bin/python bbs_system.py
```

For development without hardware:

```bash
python -m unittest discover -s tests
```

## Database Schema

`meshboard.db` is created automatically. Tables:

- `users(node_id, display_name, first_seen, last_seen)`
- `address_book(owner_id, node_id, display_name, created_at, updated_at)`
- `messages(id, sender_id, recipient_id, body, created_at, read_at, deleted_by_sender, deleted_by_recipient)`
- `locations(id, creator_id, creator_name, latitude, longitude, altitude, body, created_at, updated_at, deleted, visibility)`

## Manual Mail Test With Two Nodes

1. Start MeshBoard on the Pi.
2. From node A, send a direct message to the MeshBoard node. Confirm the main menu appears.
3. From node B, send a direct message to the MeshBoard node. Confirm the main menu appears.
4. From node A, open Mail, set a display name with `NAME Alice`, then choose Send Message.
5. Enter node B's ID, such as `!a1b2c3d4`, then enter a message body.
6. From node B, open Mail, choose Inbox, and select the unread message number.
7. Restart MeshBoard and confirm node B's read mail and node A's sent mail still exist.
8. Archive a message by ID and confirm the other user cannot archive mail they do not own.

## Hot Cold GPS Test

1. Configure both Meshtastic nodes to send position packets.
2. Start MeshBoard and wait for `Position received from !nodeid` in the logs.
3. From a node, open Location, choose Hot Cold, and start a game.
4. Move the node and send another message to Hot Cold.
5. Confirm the reply uses the current node GPS and says warmer/colder with meters away.
6. Disable GPS or wait beyond `gps.freshness_seconds`; confirm Hot Cold refuses stale data.

## Location Note GPS Test

1. Wait for MeshBoard to receive your node's position.
2. Open Location and choose Leave Something Here.
3. Send a short note.
4. Choose What's Here from the same area and confirm the note appears with distance.
5. Move farther away and choose Nearby to confirm distance sorting.
6. Restart MeshBoard and confirm the saved note still appears.

## Known Limitations

- Latest node GPS is in memory only and is intentionally lost on restart unless a user saved a location note.
- Address-book ownership is scaffolded in the schema, but the current menu uses the persistent user registry as the practical address list.
- Hot Cold still uses one fixed target coordinate; the code is structured so target selection can be added later.
- MeshBoard requests ACKs for direct replies, but Mail stores messages on the Pi and does not prove a recipient's radio received a notification.
