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
- Location check-ins with optional comments that also appear in nearby location results.
- Local SysOp admin website for viewing database content, editing records, and enabling/disabling game plugins from the LAN or hotspot.
- Admin file manager and editor with per-file rotating backups.
- Admin Test Commands console for emulating direct mesh messages without a second Meshtastic device.
- Admin backup/restore page with daily rotating backups and manual restore points.
- Editable Python game plugins with access to MeshBoard location, database, mail, and optional local AI helpers.
- Local AI menu backed by on-demand Ollama startup and 20-minute idle shutdown.
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
- `backup_manager.py` creates, prunes, lists, and restores whole-app backup archives.
- `location_service.py` contains GPS freshness and Haversine helpers.
- `modules/Mail/` provides private inbox, send, AddressBook opt-in, reply, archive, and send-to-all flows.
- `modules/MessageBoard/` provides public board categories and Events check-ins.
- `modules/CheckIns/` lists recent location check-ins from the main menu.
- `modules/LocalAI/` provides an on-demand local AI question menu.
- `modules/WhosBeenHere/` lists automatic recent users by last interaction time and command count.
- `modules/Location/` provides What's Here, Drop Note, Nearby Notes, and location check-ins.
- `modules/Games/` remains dynamically loaded as the Games submenu.

## Install On A Pi Or OSMC Host

These steps install as whichever Linux user runs them. The default app directory is `~/MeshBoard`, and the service/startup entries do not depend on a specific username.

```bash
git clone https://github.com/VeggieVampire/MeshBoard.git
cd MeshBoard
scripts/install_pi.sh
```

The installer does the full default setup:

- Installs Linux packages and Python dependencies.
- Installs MeshBoard to `~/MeshBoard` unless `APP_DIR` is set.
- Creates `meshtastic_config.json`, detecting USB when available and falling back to safe auto-connection defaults.
- Creates `admin_config.json`, enables the admin website, generates a private admin password, saves it to `admin_credentials.txt`, and prints the login details at the end.
- Creates disabled `wifi_remote.conf` so hotspot access can be enabled later by editing one file.
- Installs startup entries for MeshBoard, the admin website, and the WiFi helper.
- Enables daily backups in `~/MeshBoard/backups` and creates the first daily backup.
- Installs Ollama when supported, pulls the small `tinyllama` model, and disables the always-on Ollama service so Local AI starts only on demand. On 32-bit ARM Pi OS, Ollama is skipped and Local AI can be pointed at another LAN Ollama server from Config.
- Starts MeshBoard and the admin website immediately.

After install, the script prints the admin URL, username, password, and config file locations. You can also find the generated admin login on the Pi:

```bash
cat ~/MeshBoard/admin_credentials.txt
```

Override the destination with:

```bash
APP_DIR="$HOME/apps/MeshBoard" scripts/install_pi.sh
```

Use a specific admin password instead of a generated one:

```bash
MESHBOARD_ADMIN_PASSWORD='change-this-password' scripts/install_pi.sh
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
    },
    "local_ai": {
        "enabled": true,
        "url": "http://127.0.0.1:11434/api/generate",
        "model": "tinyllama",
        "timeout_seconds": 120,
        "idle_shutdown_seconds": 1200,
        "startup_timeout_seconds": 120
    }
}
```

View logs:

```bash
tail -f ~/MeshBoard/listener.log
```

The installer tries to enable the user service and also installs cron `@reboot` fallback entries. If you want the user service to start before that user logs in, enable linger:

```bash
sudo loginctl enable-linger "$USER"
```

The installer adds the current user to `dialout` for USB serial access. On some systems, that group change does not affect existing sessions until logout/login or reboot.

## Offline Headless Startup

A Pi without internet usually also has no reliable clock, and a user systemd service can stop when the SSH/login session ends unless linger is enabled. The installer sets up the no-sudo cron launcher automatically:

```bash
crontab -l
```

The launcher uses `/tmp/meshboard.lock` so a second copy exits instead of fighting for the USB radio. Logs still go to `listener.log`.

## Remote Hotspot WiFi Fallback

For remote trips, you can keep a disabled hotspot config on the Pi and enable it when you need emergency SSH access. MeshBoard includes a NetworkManager helper for Raspberry Pi OS/OSMC systems that have `nmcli`.

You can edit these settings from the admin website under Config > Remote Hotspot WiFi. Password fields stay blank in the browser when a password is already saved; leaving them blank keeps the existing password.

The installer also creates the editable config for offline changes:

```bash
vi ~/MeshBoard/wifi_remote.conf
```

Example:

```text
ENABLED=true
INTERFACE=auto
CONNECTION_NAME=MeshBoardRemoteHotspot
CONNECT_ONLY_WHEN_OFFLINE=true
PREFER_VISIBLE_HOTSPOT=true
CHECK_INTERVAL_SECONDS=60

HOTSPOT_1_ENABLED=true
HOTSPOT_1_SSID=MyPhoneHotspot
HOTSPOT_1_PSK=hotspot-password-here

HOTSPOT_2_ENABLED=true
HOTSPOT_2_SSID=BackupHotspot
HOTSPOT_2_PSK=backup-password-here
```

The installer adds the retry helper at boot and starts it immediately. It stays idle while `ENABLED=false`.

```bash
tail -f ~/MeshBoard/wifi-connect.log
```

The helper rereads `wifi_remote.conf` every retry cycle. If `ENABLED=true`, it scans for the configured hotspots and tries enabled entries in slot order until one connects. Use `INTERFACE=auto` to pick the first WiFi device, or set a specific device such as `wlan0`. If `CONNECT_ONLY_WHEN_OFFLINE=true`, it normally leaves an already-connected WiFi network alone; `PREFER_VISIBLE_HOTSPOT=true` makes any configured hotspot win when it is visible, which is useful when a weak saved WiFi network is still associated but you want phone-hotspot access. Logs go to `wifi-connect.log`.

The installer grants the MeshBoard user passwordless permission to run `nmcli` through `/etc/sudoers.d/meshboard-nmcli`, because background hotspot scans and connection changes may be rejected by NetworkManager without it.

Useful checks:

```bash
tail -f /home/osmc/MeshBoard/wifi-connect.log
nmcli device status
nmcli connection show
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

The installer creates and enables the admin config. It saves the generated login here:

```bash
cat ~/MeshBoard/admin_credentials.txt
```

To change the admin password later:

```bash
cd ~/MeshBoard
.venv/bin/python admin_server.py --hash-password
vi admin_config.json
```

Admin pages include Users activity, editable AddressBook contacts, active and archived Mail messages, Message Board posts, location notes, Events check-ins, game controls, backups, file editing, test commands, configuration, and recent logs. Edit/archive/delete/remove/close/restore buttons change local MeshBoard files immediately, so use them like a real SysOp console.

The `Files` admin page browses the MeshBoard app directory and edits text files in place. Before each save, MeshBoard creates a backup under `.file_backups` and keeps only the newest 7 backups for that specific file.

The `Test Commands` admin page emulates direct messages from a fake node ID. It keeps menu state for that fake node, so you can send `top`, `3`, `1`, and other commands through the web UI without needing a second Meshtastic device.

The admin launcher watches for a usable IPv4 address before starting the website. If the Pi has no LAN or hotspot IP, the web server stays down and only the small launcher loop remains. If the IP disappears later, the launcher stops the website until an IP comes back. To change the check interval, set `ADMIN_IP_CHECK_INTERVAL_SECONDS` before running `scripts/run_admin_forever.sh`.

The `Games` admin page discovers Python game plugins in `modules/Games`. Enable/disable changes apply to the live Games menu. Imported game plugins are saved into `modules/Games` and load after MeshBoard restarts.

Each game row has:

- `Edit`: opens the plugin Python source in the admin website and validates it before saving.
- `Enable` / `Disable`: controls whether the game appears in the Meshtastic Games menu.
- `Import Game Plugin`: adds a new `.py` plugin file.

Existing MeshBoard sessions load game code at startup, so restart MeshBoard after editing or importing a plugin:

```bash
pkill -f bbs_system.py
```

The cron/service launcher starts it again automatically.

Game plugins receive the live `bbs_system` object:

```python
menu_name = "Trail Helper"

def process_command(user_id, command, bbs_system):
    location, message = bbs_system.get_recent_location_or_message(user_id)
    if message:
        return message
    return bbs_system.ask_local_ai(
        f"Make a short trail hint for {location['latitude']}, {location['longitude']}"
    )
```

Useful plugin hooks:

- `bbs_system.db`: access `meshboard.db` helpers for mail, users, locations, boards, and game settings.
- `bbs_system.get_recent_location_or_message(user_id)`: get the user's fresh GPS position or a ready-to-send error message.
- `bbs_system.get_latest_location(user_id)`: get the last cached GPS position without freshness checking.
- `bbs_system.interface`: access the Meshtastic interface if a game needs lower-level radio behavior.
- `bbs_system.ask_local_ai(prompt, system=None, model=None)`: call a local AI server when enabled.

Local AI uses an Ollama-compatible local server. The installer tries to install Ollama and pull `tinyllama` when the OS supports it. The Ollama service is disabled after install so MeshBoard starts it only when someone opens the Local AI menu. On 32-bit ARM Pi OS, use Config to point `url` at another LAN Ollama server.

```json
"local_ai": {
    "enabled": true,
    "url": "http://127.0.0.1:11434/api/generate",
    "model": "tinyllama",
    "timeout_seconds": 120,
    "idle_shutdown_seconds": 1200,
    "startup_timeout_seconds": 120
}
```

### Config

The `Config` admin page is the central place for routine customization. It edits `meshtastic_config.json` and backup retention without needing SSH.

Config sections include:

- `Backups`: daily retention days.
- `Connection`: USB path, WiFi/TCP host and port, Bluetooth address, and preferred connection type.
- `Meshtastic Replies`: max text length, chunk delay, ACK timeout, ACK retries, and reconnect delay.
- `GPS / Location`: GPS freshness and What's Here/Nearby radius settings.
- `Time Sync`: mesh/host time sync options and timestamp safety limits.
- `Local AI`: optional local AI URL, model, timeout, idle shutdown, startup timeout, and enable switch.

Runtime changes take effect after MeshBoard restarts:

```bash
pkill -f bbs_system.py
```

The cron/service launcher starts it again automatically.

### Backups

The `Backups` admin page has:

- `Backup All Now`: creates a manual zip restore point.
- `Daily Retention Days`: controls how many daily backups are kept. The default is 7 days.
- `Restore`: restores the selected backup over the current app files.

The installer adds this cron entry:

```bash
@daily cd ~/MeshBoard && ~/MeshBoard/.venv/bin/python ~/MeshBoard/backup_manager.py --daily
```

Daily backups use one file per day, so a second daily run on the same date overwrites that day's file. Older daily backups are pruned after the retention limit. Manual backups are kept until you remove them from `~/MeshBoard/backups`.

Backups include MeshBoard code, database, local configs, and plugin files. They exclude `.git`, `.venv`, logs, Python cache files, and the backup folder itself.

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
6. Check-Ins
7. Local AI
Reply number. top - Main, cd .. - Back
```

Common commands:

- `top`: return to the main menu.
- `cd ..`, `cd..`, `Cd ..`, or `Cd..`: go back one menu.
- `1`, `2`, `3`, etc.: choose menu items.

Mail:

- Open `Mail` from the main menu.
- Use Inbox to read stored messages addressed to your node only. New/unread messages have `*` beside them. MeshBoard records when each user last checked mail. Message detail uses `1. Reply`, `2. Archive`, and `3. Back`.
- Use Send to choose an AddressBook contact and send a stored message. Choose `0. All` to save the message for every AddressBook contact except yourself.
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
- Drop Note saves a note at your current node position.
- Nearby lists saved notes and location check-ins sorted by distance.
- Check In saves your current node position with an optional comment. It appears in What's Here, Nearby, and the main-menu Check-Ins view.
- Hot Cold uses your latest live GPS position.

Check-Ins:

- Shows recent location check-ins from the main menu.
- This is separate from Events check-ins. Events check-ins are the HAM-style 24-hour roster under Message Board > Events and do not require GPS.

Local AI:

- Open `Local AI` from the main menu.
- MeshBoard replies with `Local AI booting up...` and help text immediately.
- When Ollama and the configured model are ready, MeshBoard sends `Local AI is ready. Ask any short question.`
- Ask short questions in plain text.
- Send `top` or `end of line` to shut down Local AI and return to the main menu.
- If nobody uses Local AI for 20 minutes, MeshBoard unloads/stops it to free Pi resources.
- Long AI replies are split into radio-sized chunks with a footer such as `1 of 3`.

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

- `users(node_id, display_name, mail_listed, first_seen, last_seen, command_count, last_mail_check_at)`
- `address_book(owner_id, node_id, display_name, created_at, updated_at)`
- `messages(id, sender_id, recipient_id, body, created_at, read_at, deleted_by_sender, deleted_by_recipient)`
- `locations(id, creator_id, creator_name, latitude, longitude, altitude, body, created_at, updated_at, deleted, visibility, kind)`
- `board_posts(id, category, author_id, body, created_at, deleted)`
- `checkin_events(id, title, created_by, starts_at, ends_at, closed)`
- `checkin_entries(event_id, node_id, checked_in_at)`
- `game_settings(module_name, enabled, updated_at)`

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
