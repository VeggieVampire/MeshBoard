import copy
import json
import logging
import os


CONFIG_FILE = "meshtastic_config.json"

DEFAULT_CONFIG = {
    "connection_type": "auto",
    "device_path": "/dev/ttyUSB0",
    "wifi": {
        "hostname": "",
        "port": 4403,
    },
    "bluetooth": {
        "address": "",
    },
    "gps": {
        "freshness_seconds": 300,
        "whats_here_radius_meters": 100,
        "nearby_radius_meters": 1000,
        "log_raw_history": False,
    },
    "meshtastic": {
        "max_text_length": 140,
        "chunk_delay_seconds": 0.5,
        "ack_timeout_seconds": 7,
        "ack_retries": 3,
        "reconnect_delay_seconds": 10,
    },
    "time_sync": {
        "sync_on_startup": True,
        "sync_from_host": False,
        "sync_from_mesh": True,
        "sync_interval_seconds": 3600,
        "minimum_valid_epoch": 1704067200,
        "maximum_future_seconds": 172800,
        "allow_receive_time": False,
    },
    "database": {
        "path": "meshboard.db",
    },
}

logger = logging.getLogger(__name__)


def _merge_defaults(config, defaults):
    merged = copy.deepcopy(defaults)
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_config(config_file=CONFIG_FILE):
    if not os.path.exists(config_file):
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(config_file, "r", encoding="utf-8") as config_handle:
            loaded = json.load(config_handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Error reading configuration file '%s': %s", config_file, exc)
        return copy.deepcopy(DEFAULT_CONFIG)

    return _merge_defaults(loaded, DEFAULT_CONFIG)


def save_config(config, config_file=CONFIG_FILE):
    with open(config_file, "w", encoding="utf-8") as config_handle:
        json.dump(config, config_handle, indent=4)
