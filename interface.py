import json
import os
import logging
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

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
    def __init__(self):
        self.interface = None
        self.handle_message = None  # Callback for message handling

    def connect(self):
        """Connect to the Meshtastic device."""
        logger.info("Connecting to Meshtastic device...")
        try:
            self.interface = SerialInterface()
            logger.info(f"Connected to Meshtastic device on {self.interface.devPath}")
            pub.subscribe(self.on_receive, "meshtastic.receive")
            pub.subscribe(self.on_connection, "meshtastic.connection.established")
        except Exception as e:
            logger.error(f"Failed to connect to Meshtastic device: {e}")

    def on_connection(self, interface):
        """Handle connection establishment."""
        logger.info("Meshtastic device connected and ready.")

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
        """Run the interface."""
        self.connect()
        logger.info("Listening for messages... Press Ctrl+C to exit.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            logger.info("Shutting down interface...")
        finally:
            if self.interface:
                self.interface.close()

