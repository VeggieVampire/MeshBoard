import json
import logging
import serial.tools.list_ports
from meshtastic.serial_interface import SerialInterface

CONFIG_FILE = "meshtastic_config.json"

logging.basicConfig(
    level=logging.INFO,  # Set to INFO for less verbose output
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

def find_meshtastic_device():
    """Search for the Meshtastic device among available serial ports."""
    logger.info("Scanning for Meshtastic device...")
    ports = serial.tools.list_ports.comports()
    if not ports:
        logger.warning("No serial ports found on this system.")
        return None

    logger.info(f"Found {len(ports)} serial ports.")
    for port in ports:
        logger.info(f"Testing port: {port.device} ({port.description})")
        try:
            # Attempt to initialize the Meshtastic interface
            interface = SerialInterface(devPath=port.device)
            logger.info(f"✅ Meshtastic device detected on {port.device}")
            interface.close()
            return port.device
        except Exception as e:
            logger.info(f"❌ Port {port.device} is not a Meshtastic device: {e}")

    logger.error("No Meshtastic device found. Please check the connection and try again.")
    return None

def create_config_file(dev_path):
    """Create the configuration file with the detected device path."""
    logger.info(f"Creating configuration file '{CONFIG_FILE}'...")
    config_data = {"device_path": dev_path}  # Updated key to 'device_path'
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=4)
        logger.info(f"✅ Configuration file created successfully at {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"❌ Failed to create configuration file: {e}")

def main():
    logger.info("Starting Meshtastic setup script...")
    device_path = find_meshtastic_device()

    if device_path:
        logger.info(f"Meshtastic device found: {device_path}")
        create_config_file(device_path)
        logger.info("Setup completed successfully!")
    else:
        logger.error("Setup failed: No Meshtastic device detected.")

if __name__ == "__main__":
    main()
