import json
import os
import logging
from meshtastic.serial_interface import SerialInterface
from pubsub import pub
import time

CONFIG_FILE = "meshtastic_config.json"
LOG_FILE = "listener.log"

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
    def __init__(self, retry_delay=20):
        self.interface = None
        self.handle_message = None  # Callback for message handling
        self.retry_delay = retry_delay
        self.running = False

    def connect(self):
        """Attempt to connect to the Meshtastic device."""
        logger.info("Attempting to connect to the Meshtastic device...")
        try:
            self.interface = SerialInterface()
            logger.info(f"Successfully connected to Meshtastic device on {self.interface.devPath}")
            pub.subscribe(self.on_receive, "meshtastic.receive")
            pub.subscribe(self.on_connection, "meshtastic.connection.established")
        except Exception as e:
            logger.error(f"Failed to connect to Meshtastic device: {e}")
            self.interface = None
            raise

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

    def on_connection(self, interface):
        """Handle connection establishment."""
        logger.info("Meshtastic device connection established and ready.")

    def on_receive(self, packet, interface):
        """Handle incoming messages."""
        try:
            decoded = packet.get("decoded", {})
            text = decoded.get("text", None)
            sender = packet.get("fromId", None)

            if text and sender:
                logger.info(f"Message received from {sender}: {text}")
                if self.handle_message:
                    response = self.handle_message(sender, text)
                    if response:
                        self.send_message(sender, response)
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

    def run(self):
        """Run the interface with infinite reconnection attempts."""
        self.running = True
        while self.running:
            try:
                if not self.interface:
                    self.connect()
                logger.info("Listening for messages... Press Ctrl+C to exit.")
                while self.interface:  # Continue listening while connected
                    pass  # Busy listening; no delay added here for responsiveness
            except Exception as e:
                logger.warning(f"Connection lost: {e}")
                self.disconnect()
                logger.info(f"Retrying connection in {self.retry_delay} seconds...")
                for seconds_left in range(self.retry_delay, 0, -1):
                    if not self.running:
                        logger.info("Shutdown detected during retry delay.")
                        break  # Exit retry delay if stopping
                    time.sleep(1)
                continue  # Keep retrying to connect
            except KeyboardInterrupt:
                logger.info("Shutting down interface on Ctrl+C...")
                self.running = False
        self.disconnect()
        logger.info("Interface stopped.")

