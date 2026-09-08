import os
import tempfile
import time
import unittest

import interface as interface_module
from bbs_system import BBSSystem
from config import DEFAULT_CONFIG
from database import Database
from interface import Interface
from location_service import distance_between_locations
from modules.Location import process_command as location_command


class DummyInterface:
    def __init__(self):
        self.handle_message = None
        self.handle_position = None

    def run(self):
        pass


def test_config(db_path):
    config = DEFAULT_CONFIG.copy()
    config["database"] = {"path": db_path}
    config["gps"] = {
        "freshness_seconds": 300,
        "whats_here_radius_meters": 100,
        "nearby_radius_meters": 1000,
        "log_raw_history": False,
    }
    config["meshtastic"] = {
        "max_text_length": 40,
        "chunk_delay_seconds": 0,
        "reconnect_delay_seconds": 1,
    }
    return config


class MeshBoardTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "meshboard.db")
        self.bbs = BBSSystem(
            config=test_config(self.db_path),
            database=Database(self.db_path),
            interface=DummyInterface(),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_haversine_distance(self):
        distance = distance_between_locations(35.0, -97.0, 35.001, -97.0)
        self.assertGreater(distance, 100)
        self.assertLess(distance, 120)

    def test_recent_and_stale_gps(self):
        self.bbs.update_node_location("!abc12345", {"latitude": 35, "longitude": -97})
        location, message = self.bbs.get_recent_location_or_message("!abc12345")
        self.assertIsNotNone(location)
        self.assertIsNone(message)

        self.bbs.node_locations["!abc12345"]["received_at"] = int(time.time()) - 600
        location, message = self.bbs.get_recent_location_or_message("!abc12345")
        self.assertIsNone(location)
        self.assertIn("last GPS position", message)

    def test_save_location_note_and_whats_here(self):
        user = "!abc12345"
        self.bbs.update_node_location(user, {"latitude": 35.0, "longitude": -97.0})
        self.bbs.users[user] = {"menu": ["main"]}
        self.assertIn("Enter the message", location_command(user, "2", self.bbs))
        self.assertEqual("Saved at your current location.", location_command(user, "Old foundation.", self.bbs))

        response = location_command(user, "1", self.bbs)
        self.assertIn("Old foundation.", response)
        reopened = Database(self.db_path)
        self.assertEqual(1, len(reopened.active_locations()))

    def test_whats_here_radius_and_nearby_sorting(self):
        user = "!abc12345"
        self.bbs.update_node_location(user, {"latitude": 35.0, "longitude": -97.0})
        self.bbs.db.save_location("!n1", None, 35.0001, -97.0, None, "Close note")
        self.bbs.db.save_location("!n2", None, 35.005, -97.0, None, "Far note")
        self.bbs.users[user] = {"menu": ["main"]}

        here = location_command(user, "1", self.bbs)
        self.assertIn("Close note", here)
        self.assertNotIn("Far note", here)

        nearby = location_command(user, "3", self.bbs)
        self.assertLess(nearby.index("Close note"), nearby.index("Far note"))

    def test_send_mail_inbox_read_and_reopen(self):
        self.bbs.db.upsert_user("!sender", "Sender")
        self.bbs.db.upsert_user("!recipient", "Recipient")
        message_id = self.bbs.db.send_message("!sender", "!recipient", "Gate is fixed.")

        self.assertEqual(1, self.bbs.db.unread_count("!recipient"))
        inbox = self.bbs.db.inbox("!recipient")
        self.assertEqual(message_id, inbox[0]["id"])
        self.bbs.db.mark_read(message_id, "!recipient")
        self.assertEqual(0, self.bbs.db.unread_count("!recipient"))

        reopened = Database(self.db_path)
        self.assertEqual("Gate is fixed.", reopened.inbox("!recipient")[0]["body"])

    def test_new_user_first_message_is_processed(self):
        response = self.bbs.handle_message("!newuser", "hello")
        self.assertIn("Main Menu", response)
        self.assertIn("Invalid", response)

    def test_chunk_long_outgoing_messages(self):
        interface = Interface(test_config(self.db_path))
        chunks = interface.chunk_message("alpha beta gamma delta epsilon zeta eta theta")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))
        self.assertEqual("alpha beta gamma delta epsilon zeta eta theta", " ".join(chunks))

    def test_broadcast_text_is_ignored(self):
        mesh_interface = Interface(test_config(self.db_path))
        calls = []
        mesh_interface.handle_message = lambda sender, text: calls.append((sender, text))

        mesh_interface.on_receive({
            "fromId": "!sender",
            "toId": "^all",
            "to": 0xFFFFFFFF,
            "id": 1,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "top"},
        }, None)

        self.assertEqual([], calls)

    def test_direct_text_is_processed(self):
        mesh_interface = Interface(test_config(self.db_path))
        sent = []
        mesh_interface.handle_message = lambda sender, text: "ok"
        mesh_interface.send_message = lambda sender, text, reply_id=None: sent.append((sender, text, reply_id))

        mesh_interface.on_receive({
            "fromId": "!sender",
            "toId": "!meshboard",
            "to": 0x9EA0CC08,
            "id": 2,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "top"},
        }, None)

        self.assertEqual([("!sender", "ok", 2)], sent)

    def test_wifi_transport_connects_with_hostname_and_port(self):
        calls = []

        class FakeTCP:
            def __init__(self, hostname, portNumber):
                calls.append((hostname, portNumber))

        original_pub = interface_module.pub
        original_tcp = interface_module.TCPInterface
        original_serial = interface_module.SerialInterface
        original_ble = interface_module.BLEInterface
        try:
            interface_module.pub = type("FakePub", (), {"subscribe": staticmethod(lambda *args: None)})
            interface_module.TCPInterface = FakeTCP
            interface_module.SerialInterface = None
            interface_module.BLEInterface = None
            config = test_config(self.db_path)
            config["connection_type"] = "wifi"
            config["wifi"] = {"hostname": "192.168.1.50", "port": 4404}
            mesh_interface = Interface(config)
            mesh_interface.connect()
            self.assertIsInstance(mesh_interface.interface, FakeTCP)
            self.assertEqual([("192.168.1.50", 4404)], calls)
        finally:
            interface_module.pub = original_pub
            interface_module.TCPInterface = original_tcp
            interface_module.SerialInterface = original_serial
            interface_module.BLEInterface = original_ble

    def test_bluetooth_transport_uses_configured_address(self):
        calls = []

        class FakeBLE:
            def __init__(self, address):
                calls.append(address)

        original_pub = interface_module.pub
        original_tcp = interface_module.TCPInterface
        original_serial = interface_module.SerialInterface
        original_ble = interface_module.BLEInterface
        try:
            interface_module.pub = type("FakePub", (), {"subscribe": staticmethod(lambda *args: None)})
            interface_module.TCPInterface = None
            interface_module.SerialInterface = None
            interface_module.BLEInterface = FakeBLE
            config = test_config(self.db_path)
            config["connection_type"] = "bluetooth"
            config["bluetooth"] = {"address": "AA:BB:CC:DD:EE:FF"}
            mesh_interface = Interface(config)
            mesh_interface.connect()
            self.assertIsInstance(mesh_interface.interface, FakeBLE)
            self.assertEqual(["AA:BB:CC:DD:EE:FF"], calls)
        finally:
            interface_module.pub = original_pub
            interface_module.TCPInterface = original_tcp
            interface_module.SerialInterface = original_serial
            interface_module.BLEInterface = original_ble


if __name__ == "__main__":
    unittest.main()
