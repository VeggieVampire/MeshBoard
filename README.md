# MeshBoard

Text-based Bulletin Board System (BBS) designed to run over a Meshtastic network.

MeshBoard runs on a Raspberry Pi or Linux host connected to a Meshtastic radio by USB serial, WiFi/TCP, or Bluetooth/BLE. Users send direct-message text commands to the MeshBoard node; MeshBoard replies with menus, games, store-and-forward mail, and GPS/location features without requiring internet access.

MeshBoard also keeps the attached radio clock sane. On startup it sets the Meshtastic radio time from the host clock, and while running it can refresh the radio clock from plausible timestamps seen in nearby mesh packets. This prevents messages from showing as December 31, 1969 when the radio has fallen back to epoch zero.

## What It Does

- Direct-message-only BBS commands. Broadcast text packets are ignored.
- Menu navigation with `top`, `cd ..`, and numbered choices.
- Persistent SQLite store-and-forward mail keyed by Meshtastic node ID.
- AddressBook opt-in with user-chosen 4-character IDs.
- Who's Been Here list showing automatic recent MeshBoard users, newest first, with command counts.
- Message Board categories for general discussion, local news, trading, events, and rumors.
- Events check-in board with a 24-hour HAM-style roster from AddressBook.
- Local SysOp admin website for viewing and deleting database content from the LAN or hotspot.
- Live GPS-aware Location tools using the sender node's latest Meshtastic position.
- Saved location notes, nearby note lookup, and Hot Cold GPS gameplay.
- USB serial first, with WiFi/TCP and Bluetooth/BLE fallback.
- Chunked replies for long Meshtastic text responses.
- ACK-requesting replies with 3 automatic retries when no ACK arrives within 7 seconds.
- Automatic Meshtastic radio time sync from the host clock and nearby mesh packet timestamps.

## Architecture

- `interface.py` owns the Meshtastic connection, direct-message filtering, incoming text/position packets, and outgoing replies.
- `bbs_system.py` owns per-node sessions, dynamic module loading, unread mail notices, and latest in-memory GPS state.
- `database.py` initializes and accesses `meshboard.db`.
- `admin_server.py` provides the local SysOp admin website.
- `location_service.py` contains GPS freshness and Haversine helpers.
- `modules/Mail/` provides inbox, send, AddressBook opt-in, reply, and archive flows.
- `modules/MessageBoard/` provides public board categories and Events check-ins.
- `modules/WhosBeenHere/` lists automatic recent users by last interaction time and command count.
- `modules/Location/` provides What's Here, Drop Note, and Nearby Notes.
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
        "max_text_length": 140,
        "chunk_delay_seconds": 0.5,
        "ack_timeout_seconds": 7,
        "ack_retries": 3,
        "reconnect_delay_seconds": 10
    },
    "time_sync": {
        "sync_on_startup": true,
        "sync_from_host": false,
        "sync_from_mesh": true,
        "sync_interval_seconds": 3600,
        "minimum_valid_epoch": 1704067200,
        "maximum_future_seconds": 172800,
        "allow_receive_time": false
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

## Offline Headless Startup

A Pi without internet usually also has no reliable clock, and a user systemd service can stop when the SSH/login session ends unless linger is enabled. If you cannot enable linger with `sudo loginctl enable-linger "$USER"`, use the no-sudo cron launcher:

```bash
chmod +x scripts/run_meshboard_forever.sh
(crontab -l 2>/dev/null; echo '@reboot APP_DIR=$HOME/MeshBoard $HOME/MeshBoard/scripts/run_meshboard_forever.sh') | crontab -
nohup "$HOME/MeshBoard/scripts/run_meshboard_forever.sh" >/dev/null 2>&1 &
```

The launcher uses `/tmp/meshboard.lock` so a second copy exits instead of fighting for the USB radio. Logs still go to `listener.log`.

## Remote Hotspot WiFi Fallback

For remote trips, you can keep a disabled hotspot config on the Pi and enable it when you need emergency SSH access. MeshBoard includes a NetworkManager helper for Raspberry Pi OS/OSMC systems that have `nmcli`.

Create the editable config:

```bash
cd /home/osmc/MeshBoard
cp wifi_remote.conf.example wifi_remote.conf
vi wifi_remote.conf
```

Example:

```text
ENABLED=true
SSID=MyPhoneHotspot
PSK=hotspot-password-here
INTERFACE=auto
CONNECTION_NAME=MeshBoardRemoteHotspot
CONNECT_ONLY_WHEN_OFFLINE=true
CHECK_INTERVAL_SECONDS=60
```

Install the retry helper at boot:

```bash
chmod +x /home/osmc/MeshBoard/scripts/run_wifi_connect_forever.sh
(crontab -l 2>/dev/null; echo '@reboot APP_DIR=/home/osmc/MeshBoard /home/osmc/MeshBoard/scripts/run_wifi_connect_forever.sh') | crontab -
nohup /home/osmc/MeshBoard/scripts/run_wifi_connect_forever.sh >/dev/null 2>&1 &
```

The helper rereads `wifi_remote.conf` every retry cycle. If `ENABLED=true` and the WiFi interface is offline, it tries to connect to the configured hotspot. Use `INTERFACE=auto` to pick the first WiFi device, or set a specific device such as `wlan0`. If `CONNECT_ONLY_WHEN_OFFLINE=true`, it leaves an already-connected WiFi network alone. Logs go to `wifi-connect.log`.

Useful checks:

```bash
tail -f /home/osmc/MeshBoard/wifi-connect.log
nmcli device status
nmcli connection show MeshBoardRemoteHotspot
```

## Local SysOp Admin Website

MeshBoard can run a local-only admin website for SysOp maintenance when you are on the same LAN or phone hotspot as the Pi. It does not need the public internet. Open it from a phone or laptop at:

```text
http://<pi-ip>:8080
```

On the current OSMC install, that is usually:

```text
http://192.168.4.100:8080
```

Create and enable the admin config:

```bash
cd /home/osmc/MeshBoard
cp admin_config.json.example admin_config.json
.venv/bin/python admin_server.py --hash-password
vi admin_config.json
```

Set `enabled` to `true`, keep `username` as `sysop` or change it, paste the generated hash into `password_hash`, and change `session_secret` to any long random text.

Install the admin website at boot:

```bash
chmod +x /home/osmc/MeshBoard/scripts/run_admin_forever.sh
(crontab -l 2>/dev/null; echo '@reboot APP_DIR=/home/osmc/MeshBoard /home/osmc/MeshBoard/scripts/run_admin_forever.sh') | crontab -
nohup /home/osmc/MeshBoard/scripts/run_admin_forever.sh >/dev/null 2>&1 &
```

Admin pages include Users activity, editable AddressBook contacts, Mail messages, Message Board posts, location notes, Events check-ins, and recent logs. Edit/delete/remove/close buttons change `meshboard.db` immediately, so use them like a real SysOp console.

The admin launcher watches for a usable IPv4 address before starting the website. If the Pi has no LAN or hotspot IP, the web server stays down and only the small launcher loop remains. If the IP disappears later, the launcher stops the website until an IP comes back. To change the check interval, set `ADMIN_IP_CHECK_INTERVAL_SECONDS` before running `scripts/run_admin_forever.sh`.

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

## Radio Time Sync

MeshBoard sets the attached Meshtastic radio clock from the mesh by default. On startup it checks cached nearby node position times, and while running it refreshes from nearby mesh packet timestamps no more than once per hour.

The time sync ignores timestamp zero and old packet times before January 1, 2024, so stale GPS packets do not drag the clock backward. By default, mesh-based sync uses explicit position or telemetry timestamps instead of local receive times. Leave `sync_from_host` disabled for offline Pi installs because a Pi without RTC or internet can boot with the wrong clock. Enable `sync_from_host` only when the host has a reliable RTC or NTP.

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
4. Who's Been Here
5. Message Board
Reply number. top - Main, cd .. - Back
```

Common commands:

- `top`: return to the main menu.
- `cd ..`, `cd..`, `Cd ..`, or `Cd..`: go back one menu.
- `1`, `2`, `3`, etc.: choose menu items.

Mail:

- Open `Mail` from the main menu.
- Use Inbox to read stored messages. Message detail uses `1. Reply`, `2. Archive`, and `3. Back`.
- Use Send to choose an AddressBook contact and send a stored message.
- Use Add AddressBook to make yourself selectable by others. Reply `YES` for the default 4-character ID, `NO` to cancel, or send any custom 4-character ID.
- Messages persist in `meshboard.db`.

Who's Been Here:

- Shows users who have interacted with MeshBoard, newest first.
- Uses the AddressBook/display name when available, otherwise the Meshtastic node ID.
- Shows how many commands each user has sent to MeshBoard.
- This is automatic activity tracking. It is not the same as Events check-in.
- In the admin website, this appears under `Users` and includes node ID, AddressBook ID/status, command count, first interaction, and last interaction.

Message Board:

- Open `Message Board` from the main menu.
- Categories are General Discussion, Local News, Buy / Sell / Trade, Events, and Rumors & Gossip.
- In most categories, use `POST` to add a post, a number to read a post, `Next` for another page, and `BACK` to return.
- In Events, `1` starts or joins the active 24-hour check-in, `2` refreshes the check-in roster, and `3` opens normal Event posts.
- The Events check-in roster is based on AddressBook users and shows who is `In` and who is still `Out`.
- Check-in is intentional HAM-style status for one active event. It is separate from automatic Recently Seen activity.

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
- If MeshBoard is not responding, check `tail -f listener.log` and either `systemctl --user status meshboard.service` or the no-sudo cron launcher process.

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

- `users(node_id, display_name, mail_listed, first_seen, last_seen, command_count)`
- `address_book(owner_id, node_id, display_name, created_at, updated_at)`
- `messages(id, sender_id, recipient_id, body, created_at, read_at, deleted_by_sender, deleted_by_recipient)`
- `locations(id, creator_id, creator_name, latitude, longitude, altitude, body, created_at, updated_at, deleted, visibility)`
- `board_posts(id, category, author_id, body, created_at, deleted)`
- `checkin_events(id, title, created_by, starts_at, ends_at, closed)`
- `checkin_entries(event_id, node_id, checked_in_at)`

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
