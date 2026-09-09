import logging
import copy
import os
import serial.tools.list_ports
from meshtastic.serial_interface import SerialInterface
from config import DEFAULT_CONFIG, CONFIG_FILE, save_config

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
            logger.info(f"Meshtastic device detected on {port.device}")
            interface.close()
            return port.device
        except Exception as e:
            logger.info(f"Port {port.device} is not a Meshtastic device: {e}")

    logger.error("No Meshtastic device found. Please check the connection and try again.")
    return None

def auto_config(app_dir=None, dev_path=None):
    app_dir = app_dir or os.getcwd()
    config_data = copy.deepcopy(DEFAULT_CONFIG)
    config_data["device_path"] = dev_path or "/dev/ttyUSB0"
    config_data["connection_type"] = "auto"
    config_data["database"] = {"path": os.path.join(app_dir, "meshboard.db")}
    config_data["wifi"] = {"hostname": "", "port": 4403}
    config_data["bluetooth"] = {"address": ""}
    return config_data


def create_config_file(dev_path, app_dir=None, config_file=CONFIG_FILE):
    """Create the configuration file with the detected device path."""
    logger.info(f"Creating configuration file '{config_file}'...")
    config_data = auto_config(app_dir=app_dir, dev_path=dev_path)
    try:
        save_config(config_data, config_file)
        logger.info(f"Configuration file created successfully at {config_file}")
    except Exception as e:
        logger.error(f"Failed to create configuration file: {e}")

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
