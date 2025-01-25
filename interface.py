import json
import os
import logging
from meshtastic.serial_interface import SerialInterface
from pubsub import pub
import time
import requests

CONFIG_FILE = "meshtastic_config.json"
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
    def __init__(self):
        self.interface = None
        self.handle_message = None  # Callback for message handling

    def load_device_path(self):
        """Load the device path from the configuration file."""
        if not os.path.exists(CONFIG_FILE):
            logger.error(f"Configuration file '{CONFIG_FILE}' not found. Please run setup.py to create it.")
            return None

        try:
            with open(CONFIG_FILE, "r") as config_file:
                config = json.load(config_file)
                device_path = config.get("device_path")
                if not device_path:
                    logger.error(f"'device_path' not found in '{CONFIG_FILE}'.")
                    return None
                logger.info(f"Loaded device path from config: {device_path}")
                return device_path
        except Exception as e:
            logger.error(f"Error reading configuration file '{CONFIG_FILE}': {e}")
            return None

    def connect(self):
        """Attempt to connect to the Meshtastic device."""
        device_path = self.load_device_path()
        if not device_path:
            logger.error("Device path could not be loaded. Exiting...")
            return

        logger.info(f"Attempting to connect to the Meshtastic device at {device_path}...")
        try:
            # Initialize the SerialInterface object with the specified device path
            self.interface = SerialInterface(devPath=device_path)
            logger.info(f"Successfully connected to Meshtastic device on {device_path}")
            pub.subscribe(self.on_receive, "meshtastic.receive")
        except Exception as e:
            logger.error(f"Failed to connect to Meshtastic device: {e}")
            self.interface = None

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
            text = decoded.get("text", None)
            sender = packet.get("fromId", None)

            # Handle standard text messages
            if text and sender:
                logger.info(f"Message received from {sender}: {text}")
                if self.handle_message:
                    response = self.handle_message(sender, text)
                    if response:
                        self.send_message(sender, response)

            # Handle telemetry data
            position = packet.get("position", None)
            if position:
                latitude = position.get("latitude", None)
                longitude = position.get("longitude", None)
                altitude = position.get("altitude", None)
                time = position.get("time", None)

                if latitude and longitude:
                    logger.info(f"Telemetry received from {sender}: Latitude: {latitude}, Longitude: {longitude}")
                    self.log_telemetry(sender, latitude, longitude, altitude, time)

                if altitude:
                    logger.info(f"Altitude: {altitude} meters")
                if time:
                    logger.info(f"Timestamp: {time}")
            else:
                logger.debug("Received invalid or incomplete packet.")
        except Exception as e:
            logger.error(f"Error processing received message: {e}")

    def send_message(self, user_id, message):
        """Send a message back to the user."""
        try:
            destination = int(user_id.lstrip("!"), 16)  # Remove `!` and convert to int
            self.interface.sendText(message, destinationId=destination)
            logger.info(f"Sent message to {user_id}: {message}")
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {e}")

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
            self.connect()
            if not self.interface:
                logger.error("Could not connect to the Meshtastic device. Exiting...")
                return

            logger.info("Listening for messages... Press Ctrl+C to exit.")
            while self.interface:  # Continue listening while connected
                time.sleep(0.01)  # Prevent high CPU usage
        except Exception as e:
            logger.warning(f"Connection lost: {e}")
        except KeyboardInterrupt:
            logger.info("Shutting down on Ctrl+C...")
        finally:
            self.disconnect()
            logger.info("Interface stopped.")

if __name__ == "__main__":
    interface = Interface()
    interface.run()

