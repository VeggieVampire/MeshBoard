import os
import logging
import time
from config import load_config, CONFIG_FILE
from time_service import TimeSyncService

try:
    from pubsub import pub
except ImportError:
    pub = None

try:
    from meshtastic.serial_interface import SerialInterface
except ImportError:
    SerialInterface = None

try:
    from meshtastic.tcp_interface import TCPInterface
except ImportError:
    TCPInterface = None

try:
    from meshtastic.ble_interface import BLEInterface
except ImportError:
    BLEInterface = None

LOG_FILE = "listener.log"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class Interface:
    def __init__(self, config=None, config_file=CONFIG_FILE):
        self.config = config or load_config()
        self.config_file = config_file if config is None else None
        self.interface = None
        self.handle_message = None  # Callback for message handling
        self.handle_position = None
        self._seen_packet_ids = []
        self.time_sync = TimeSyncService(self.config.get("time_sync", {}))

    def _is_direct_text_packet(self, packet):
        to_id = packet.get("toId")
        to_num = packet.get("to")
        if to_id in (None, "^all"):
            return False
        if to_num in (None, 0xFFFFFFFF):
            return False
        return True

    def load_device_path(self):
        """Load the device path from the configuration file."""
        config_file = self.config_file or CONFIG_FILE
        if not os.path.exists(config_file):
            logger.warning(f"Configuration file '{CONFIG_FILE}' not found. Using default device path.")
            return self.config["device_path"]

        try:
            self.config = load_config(config_file)
            device_path = self.config.get("device_path")
            if not device_path:
                logger.error(f"'device_path' not found in '{CONFIG_FILE}'.")
                return None
            logger.info(f"Loaded device path from config: {device_path}")
            return device_path
        except Exception as e:
            logger.error(f"Error reading configuration file '{CONFIG_FILE}': {e}")
            return None

    def reload_config(self):
        if self.config_file and os.path.exists(self.config_file):
            self.config = load_config(self.config_file)
            self.time_sync.config = self.config.get("time_sync", {})
        return self.config

    def configured_transports(self):
        config = self.reload_config()
        preferred = str(config.get("connection_type", "auto")).lower()
        all_transports = ["serial", "wifi", "bluetooth"]
        if preferred == "auto":
            return all_transports
        if preferred in all_transports:
            return [preferred] + [transport for transport in all_transports if transport != preferred]
        logger.warning("Unknown connection_type '%s'. Falling back to auto.", preferred)
        return all_transports

    def _connect_serial(self):
        device_path = self.config.get("device_path")
        if not device_path:
            logger.info("Skipping USB serial: no device_path configured.")
            return None
        if SerialInterface is None:
            logger.error("Meshtastic serial support is unavailable. Run: pip3 install meshtastic")
            return None
        logger.info(f"Attempting USB serial Meshtastic connection at {device_path}...")
        return SerialInterface(devPath=device_path)

    def _connect_wifi(self):
        wifi_config = self.config.get("wifi", {})
        hostname = wifi_config.get("hostname")
        port = int(wifi_config.get("port", 4403))
        if not hostname:
            logger.info("Skipping WiFi/TCP: no wifi.hostname configured.")
            return None
        if TCPInterface is None:
            logger.error("Meshtastic TCP support is unavailable. Run: pip3 install meshtastic")
            return None
        logger.info(f"Attempting WiFi/TCP Meshtastic connection to {hostname}:{port}...")
        return TCPInterface(hostname=hostname, portNumber=port)

    def _connect_bluetooth(self):
        bluetooth_config = self.config.get("bluetooth", {})
        address = bluetooth_config.get("address") or None
        if not address:
            logger.info("Skipping Bluetooth/BLE: no bluetooth.address configured.")
            return None
        if BLEInterface is None:
            logger.error("Meshtastic BLE support is unavailable. Run: pip3 install meshtastic")
            return None
        logger.info(f"Attempting Bluetooth/BLE Meshtastic connection to {address}...")
        return BLEInterface(address=address)

    def connect(self):
        """Attempt to connect to the Meshtastic device."""
        self.reload_config()
        if pub is None:
            logger.error("Meshtastic dependencies are not installed. Run: pip3 install meshtastic")
            self.interface = None
            return

        connectors = {
            "serial": self._connect_serial,
            "wifi": self._connect_wifi,
            "bluetooth": self._connect_bluetooth,
        }
        for transport in self.configured_transports():
            try:
                connection = connectors[transport]()
                if not connection:
                    continue
                self.interface = connection
                pub.subscribe(self.on_receive, "meshtastic.receive")
                pub.subscribe(self.on_receive, "meshtastic.receive.text")
                pub.subscribe(self.on_receive, "meshtastic.receive.position")
                logger.info(f"Successfully connected to Meshtastic device using {transport}.")
                if not self.time_sync.sync_from_host(self.interface):
                    self.time_sync.sync_from_known_nodes(self.interface)
                return
            except Exception as e:
                logger.warning(f"Failed to connect using {transport}: {e}")
                self.interface = None
        logger.error("Could not connect to Meshtastic by USB serial, WiFi/TCP, or Bluetooth/BLE.")

    def disconnect(self):
        """Safely disconnect the Meshtastic device."""
        if self.interface:
            try:
                logger.info("Disconnecting Meshtastic device...")
                self.interface.close()
                logger.info("Disconnected successfully.")
            except Exception as e:
                logger.error(f"Error during disconnection: {e}")
            finally:
                self.interface = None

    def on_receive(self, packet, interface):
        """Handle incoming messages and telemetry data."""
        try:
            decoded = packet.get("decoded", {})
            self.time_sync.sync_from_packet(interface or self.interface, packet)
            text = decoded.get("text", None)
            sender = packet.get("fromId", None)
            packet_id = packet.get("id")
            if packet_id is not None:
                dedupe_key = (packet_id, sender, decoded.get("portnum"))
                if dedupe_key in self._seen_packet_ids:
                    return
                self._seen_packet_ids.append(dedupe_key)
                self._seen_packet_ids = self._seen_packet_ids[-1000:]

            # Handle standard text messages
            if text and sender:
                if not self._is_direct_text_packet(packet):
                    logger.info("Ignoring non-direct text message from %s", sender)
                    return
                logger.info(f"Message received from {sender}")
                if self.handle_message:
                    response = self.handle_message(sender, text)
                    if response:
                        self.send_message(sender, response, reply_id=packet_id)

            # Handle telemetry data
            position = packet.get("position") or decoded.get("position")
            if position:
                latitude = position.get("latitude", None)
                longitude = position.get("longitude", None)
                altitude = position.get("altitude", None)
                timestamp = position.get("time", None)

                if latitude is not None and longitude is not None and sender:
                    logger.info(f"Position received from {sender}")
                    if self.handle_position:
                        self.handle_position(sender, {
                            "latitude": latitude,
                            "longitude": longitude,
                            "altitude": altitude,
                            "timestamp": timestamp,
                        })
                    if self.config["gps"].get("log_raw_history", False):
                        self.log_telemetry(sender, latitude, longitude, altitude, timestamp)

                if altitude:
                    logger.info(f"Altitude: {altitude} meters")
                if timestamp:
                    logger.info(f"Timestamp: {timestamp}")
            else:
                logger.debug("Received invalid or incomplete packet.")
        except Exception as e:
            logger.error(f"Error processing received message: {e}")

    def send_message(self, user_id, message, reply_id=None):
        """Send a message back to the user."""
        if not self.interface:
            logger.error("Cannot send message to %s because the interface is disconnected.", user_id)
            return
        try:
            destination = int(user_id.lstrip("!"), 16)  # Remove `!` and convert to int
            for chunk in self.chunk_message(message):
                def onAckNak(packet):
                    routing = packet.get("decoded", {}).get("routing", {})
                    error = routing.get("errorReason", "NONE")
                    request_id = routing.get("requestId")
                    if error == "NONE":
                        logger.info("Reply ACK received from %s for packet %s", user_id, request_id)
                    else:
                        logger.warning("Reply NAK from %s for packet %s: %s", user_id, request_id, error)

                sent_packet = self.interface.sendText(
                    chunk,
                    destinationId=destination,
                    wantAck=True,
                    onResponse=onAckNak,
                    replyId=reply_id,
                )
                logger.info("Queued reply to %s as packet %s", user_id, getattr(sent_packet, "id", "unknown"))
                reply_id = None
                delay = self.config["meshtastic"].get("chunk_delay_seconds", 0)
                if delay:
                    time.sleep(delay)
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {e}")

    def chunk_message(self, message):
        max_length = int(self.config["meshtastic"].get("max_text_length", 180))
        if max_length <= 0 or len(message) <= max_length:
            return [message]

        chunks = []
        remaining = message
        while len(remaining) > max_length:
            split_at = remaining.rfind(" ", 0, max_length + 1)
            newline_at = remaining.rfind("\n", 0, max_length + 1)
            split_at = max(split_at, newline_at)
            if split_at < max_length // 2:
                split_at = max_length
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks

    def log_telemetry(self, sender, latitude, longitude, altitude, timestamp):
        """Log telemetry data to a CSV file."""
        try:
            with open("telemetry_log.csv", "a") as log_file:
                log_file.write(f"{sender},{latitude},{longitude},{altitude},{timestamp}\n")
            logger.info("Telemetry data logged successfully.")
        except Exception as e:
            logger.error(f"Error logging telemetry data: {e}")

    def run(self):
        """Run the interface."""
        try:
            while True:
                self.connect()
                if not self.interface:
                    delay = self.config["meshtastic"].get("reconnect_delay_seconds", 10)
                    logger.warning("Meshtastic connection unavailable. Retrying in %s seconds...", delay)
                    time.sleep(delay)
                    continue

                logger.info("Listening for messages... Press Ctrl+C to exit.")
                try:
                    while self.interface:
                        time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Connection lost: {e}")
                    self.disconnect()
                    delay = self.config["meshtastic"].get("reconnect_delay_seconds", 10)
                    logger.warning("Retrying in %s seconds...", delay)
                    time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("Shutting down on Ctrl+C...")
        finally:
            self.disconnect()
            logger.info("Interface stopped.")

if __name__ == "__main__":
    interface = Interface()
    interface.run()
