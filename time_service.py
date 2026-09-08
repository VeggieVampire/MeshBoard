import logging
import time


logger = logging.getLogger(__name__)


class TimeSyncService:
    """Keeps the attached Meshtastic radio clock away from epoch zero."""

    def __init__(self, config=None, clock=None):
        self.config = config or {}
        self.clock = clock or time.time
        self.last_sync_at = None

    def enabled(self, key):
        return bool(self.config.get(key, True))

    def sync_interval(self):
        return int(self.config.get("sync_interval_seconds", 3600))

    def minimum_valid_epoch(self):
        return int(self.config.get("minimum_valid_epoch", 1704067200))

    def maximum_future_seconds(self):
        return int(self.config.get("maximum_future_seconds", 172800))

    def allow_receive_time(self):
        return bool(self.config.get("allow_receive_time", False))

    def is_reasonable_timestamp(self, timestamp):
        try:
            timestamp = int(timestamp)
        except (TypeError, ValueError):
            return False

        if timestamp < self.minimum_valid_epoch():
            return False

        now = int(self.clock())
        if now >= self.minimum_valid_epoch():
            return timestamp <= now + self.maximum_future_seconds()

        return timestamp < 4102444800

    def should_sync(self):
        if self.last_sync_at is None:
            return True
        return int(self.clock()) - self.last_sync_at >= self.sync_interval()

    def sync_from_host(self, mesh_interface):
        if not self.enabled("sync_on_startup") or not self.enabled("sync_from_host"):
            return False

        now = int(self.clock())
        if not self.is_reasonable_timestamp(now):
            logger.warning("Host time is not plausible; waiting for a mesh packet time.")
            return False

        return self.set_radio_time(mesh_interface, now, "host clock")

    def sync_from_packet(self, mesh_interface, packet):
        if not self.enabled("sync_from_mesh") or not self.should_sync():
            return False

        for timestamp in self.extract_packet_times(packet):
            if self.is_reasonable_timestamp(timestamp):
                return self.set_radio_time(mesh_interface, int(timestamp), "mesh packet")
        return False

    def sync_from_known_nodes(self, mesh_interface):
        if not self.enabled("sync_from_mesh") or not self.should_sync():
            return False

        nodes = getattr(mesh_interface, "nodes", {}) or {}
        local_num = getattr(getattr(mesh_interface, "localNode", None), "num", None)
        candidates = []

        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            if local_num is not None and node.get("num") == local_num:
                continue
            candidates.extend(self.extract_node_times(node))

        for timestamp in sorted(set(candidates), reverse=True):
            if self.is_reasonable_timestamp(timestamp):
                return self.set_radio_time(mesh_interface, int(timestamp), "known mesh node")
        return False

    def set_radio_time(self, mesh_interface, timestamp, source):
        local_node = getattr(mesh_interface, "localNode", None)
        if local_node is None:
            logger.warning("Cannot set Meshtastic time from %s: local node is unavailable.", source)
            return False

        try:
            local_node.setTime(int(timestamp))
            self.last_sync_at = int(self.clock())
            logger.info("Set Meshtastic radio time from %s to %s.", source, int(timestamp))
            return True
        except Exception as exc:
            logger.warning("Failed to set Meshtastic radio time from %s: %s", source, exc)
            return False

    def extract_packet_times(self, packet):
        if not isinstance(packet, dict):
            return []

        candidates = []
        if self.allow_receive_time():
            self._append_time(candidates, packet.get("rxTime"))
            self._append_time(candidates, packet.get("time"))
        self._append_position_time(candidates, packet.get("position"))

        decoded = packet.get("decoded", {})
        if isinstance(decoded, dict):
            self._append_time(candidates, decoded.get("time"))
            self._append_position_time(candidates, decoded.get("position"))
            telemetry = decoded.get("telemetry")
            if isinstance(telemetry, dict):
                self._append_time(candidates, telemetry.get("time"))
                self._append_time(candidates, telemetry.get("timestamp"))

        return candidates

    def extract_node_times(self, node):
        if not isinstance(node, dict):
            return []

        candidates = []
        self._append_position_time(candidates, node.get("position"))
        return candidates

    def _append_position_time(self, candidates, position):
        if isinstance(position, dict):
            self._append_time(candidates, position.get("time"))
            self._append_time(candidates, position.get("timestamp"))

    def _append_time(self, candidates, value):
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return
        if timestamp not in candidates:
            candidates.append(timestamp)
