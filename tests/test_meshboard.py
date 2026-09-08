import os
import tempfile
import time
import unittest

import interface as interface_module
from bbs_system import BBSSystem, normalize_command
from config import DEFAULT_CONFIG
from database import Database
from interface import Interface
from location_service import distance_between_locations
from modules.Location import process_command as location_command
from modules import Mail
from modules.Games import escape_room, hot_cold, tic_tac_toe, zork


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
        "ack_timeout_seconds": 0.01,
        "ack_retries": 0,
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

    def test_location_menu_only_has_location_tools(self):
        menu = location_command("!abc12345", "menu", self.bbs)

        self.assertIn("1. What's Here?", menu)
        self.assertIn("2. Drop Note", menu)
        self.assertIn("3. Nearby Notes", menu)
        self.assertNotIn("My Saved", menu)
        self.assertNotIn("Hot Cold", menu)

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

        detail = location_command(user, "1", self.bbs)
        self.assertIn("Lat 35.000100", detail)
        self.assertIn("Lon -97.000000", detail)
        self.assertIn("Reply BACK", detail)

    def test_await_note_does_not_save_menu_numbers(self):
        user = "!abc12345"
        self.bbs.update_node_location(user, {"latitude": 35.0, "longitude": -97.0})
        self.bbs.users[user] = {"menu": ["main"]}
        self.assertIn("Enter the message", location_command(user, "2", self.bbs))

        response = location_command(user, "1", self.bbs)

        self.assertIn("Still waiting", response)
        self.assertEqual([], self.bbs.db.active_locations())

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

    def test_top_returns_to_main_menu_from_module_control(self):
        user = "!abc12345"
        self.bbs.handle_message(user, "top")
        self.bbs.handle_message(user, "1")

        response = self.bbs.handle_message(user, "Top")

        self.assertIn("Main Menu", response)
        self.assertNotIn("Invalid", response)
        self.assertNotIn("module_control", self.bbs.users[user])
        self.assertEqual(["main"], self.bbs.users[user]["menu"])

    def test_global_command_aliases_are_normalized(self):
        self.assertEqual("top", normalize_command("top"))
        self.assertEqual("top", normalize_command("Top"))
        self.assertEqual("cd ..", normalize_command("cd .."))
        self.assertEqual("cd ..", normalize_command("Cd .. "))
        self.assertEqual("cd ..", normalize_command("cd.."))
        self.assertEqual("cd ..", normalize_command("Cd.."))

    def test_cd_dot_dot_returns_to_current_module_menu_once(self):
        user = "!abc12345"
        for command in ("cd ..", "Cd .. ", "cd..", "Cd.."):
            with self.subTest(command=command):
                self.bbs.users[user] = {"menu": ["main", "Mail"], "module_control": Mail}

                response = self.bbs.handle_message(user, command)

                self.assertIn("Mail", response)
                self.assertNotIn("Main Menu", response)
                self.assertNotIn("module_control", self.bbs.users[user])
                self.assertEqual(["main", "Mail"], self.bbs.users[user]["menu"])

    def test_mail_addressbook_opt_in_and_paged_send(self):
        user = "!sender"
        self.bbs.users[user] = {"menu": ["main"]}
        menu = Mail.display_menu()
        self.assertIn("1. Inbox", menu)
        self.assertIn("2. Send", menu)
        self.assertIn("3. Add AddressBook", menu)
        self.assertIn("4. Archive", menu)

        self.assertIn("Add you", Mail.process_command(user, "add addressBook", self.bbs))
        self.assertIn("simple ID", Mail.process_command(user, "yes", self.bbs))
        self.assertEqual("Added to AddressBook as Sender.", Mail.process_command(user, "Sender", self.bbs))

        for index in range(9):
            self.bbs.db.set_mail_listed(f"!node{index}", f"User{index}", True)

        response = Mail.process_command(user, "send", self.bbs)
        self.assertIn("1. Sender", response)
        self.assertIn("9. Next", response)
        response = Mail.process_command(user, "9", self.bbs)
        self.assertIn("AddressBook 9-10", response)

    def test_mail_inbox_archive_and_reply(self):
        sender = "!sender"
        recipient = "!recipient"
        self.bbs.db.set_mail_listed(sender, "Sender", True)
        self.bbs.db.set_mail_listed(recipient, "Recipient", True)
        self.bbs.db.send_message(sender, recipient, "Gate is fixed.")

        self.bbs.users[recipient] = {"menu": ["main"]}
        inbox = Mail.process_command(recipient, "inbox", self.bbs)
        self.assertIn("Sender", inbox)

        detail = Mail.process_command(recipient, "1", self.bbs)
        self.assertIn("Reply REPLY", detail)
        self.assertEqual(0, self.bbs.db.unread_count(recipient))

        reply_prompt = Mail.process_command(recipient, "reply", self.bbs)
        self.assertIn("Reply to Sender", reply_prompt)
        sent = Mail.process_command(recipient, "Thanks", self.bbs)
        self.assertIn("Message saved for Sender", sent)
        self.assertEqual("Thanks", self.bbs.db.inbox(sender)[0]["body"])

        Mail.process_command(recipient, "inbox", self.bbs)
        Mail.process_command(recipient, "1", self.bbs)
        archived = Mail.process_command(recipient, "archive", self.bbs)
        self.assertIn("Message archived", archived)
        self.assertEqual([], self.bbs.db.inbox(recipient))

        archive = Mail.process_command(recipient, "archive", self.bbs)
        self.assertIn("Gate is fixed.", archive)
        deleted = Mail.process_command(recipient, "delete 1", self.bbs)
        self.assertIn("Archived message deleted", deleted)
        self.assertEqual([], self.bbs.db.archived_inbox(recipient))

    def test_chunk_long_outgoing_messages(self):
        interface = Interface(test_config(self.db_path))
        chunks = interface.chunk_message("alpha beta gamma delta epsilon zeta eta theta")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))
        self.assertEqual("alpha beta gamma delta epsilon zeta eta theta", " ".join(chunks))

    def test_first_screen_menus_fit_single_radio_packet(self):
        self.bbs.users["!abc12345"] = {"menu": ["main"]}
        menus = [
            self.bbs.display_menu("!abc12345"),
            self.bbs.display_submenu("Games"),
            Mail.display_menu(),
            escape_room.display_menu(),
            hot_cold.display_menu(),
            tic_tac_toe.display_menu(),
            zork.display_menu(),
        ]

        self.assertTrue(all(len(menu) <= 140 for menu in menus))

    def test_non_location_menu_navigation(self):
        game_entries = {
            "1": "Hot Cold",
            "2": "Zork",
            "3": "Tic Tac Toe",
            "4": "Escape Room",
        }
        for choice, title in game_entries.items():
            with self.subTest(game=title):
                user = f"!game{choice}"
                self.assertIn("Main Menu", self.bbs.handle_message(user, "top"))
                self.assertIn("Games Menu", self.bbs.handle_message(user, "2"))
                self.assertIn(title, self.bbs.handle_message(user, choice))
                self.assertIn("Games Menu", self.bbs.handle_message(user, "cd .."))

        user = "!mailtest"
        self.assertIn("Main Menu", self.bbs.handle_message(user, "top"))
        self.assertIn("Mail", self.bbs.handle_message(user, "3"))
        self.assertIn("Inbox", self.bbs.handle_message(user, "1"))
        self.assertIn("Mail", self.bbs.handle_message(user, "back"))
        self.assertIn("AddressBook", self.bbs.handle_message(user, "2"))
        self.assertIn("Mail", self.bbs.handle_message(user, "back"))
        self.assertIn("Add you", self.bbs.handle_message(user, "3"))
        self.assertIn("Not added", self.bbs.handle_message(user, "no"))
        self.assertIn("Archive", self.bbs.handle_message(user, "4"))

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

    def test_outgoing_dm_replies_do_not_use_thread_reply_id(self):
        class FakePacket:
            id = 123

        class FakeRadio:
            def __init__(self):
                self.calls = []

            def sendText(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                kwargs["onResponse"]({"decoded": {"routing": {"errorReason": "NONE", "requestId": 123}}})
                return FakePacket()

        mesh_interface = Interface(test_config(self.db_path))
        mesh_interface.interface = FakeRadio()

        mesh_interface.send_message("!433bed54", "Mail", reply_id=99)

        self.assertEqual("Mail", mesh_interface.interface.calls[0][0][0])
        self.assertEqual("!433bed54", mesh_interface.interface.calls[0][1]["destinationId"])
        self.assertTrue(mesh_interface.interface.calls[0][1]["wantAck"])
        self.assertNotIn("replyId", mesh_interface.interface.calls[0][1])

    def test_outgoing_dm_retries_three_times_without_ack(self):
        class FakePacket:
            id = 123

        class FakeRadio:
            def __init__(self):
                self.calls = []

            def sendText(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return FakePacket()

        config = test_config(self.db_path)
        config["meshtastic"]["ack_timeout_seconds"] = 0.01
        config["meshtastic"]["ack_retries"] = 3
        mesh_interface = Interface(config)
        mesh_interface.interface = FakeRadio()

        mesh_interface.send_message("!433bed54", "Mail")

        self.assertEqual(4, len(mesh_interface.interface.calls))
        self.assertTrue(all(call[1]["destinationId"] == "!433bed54" for call in mesh_interface.interface.calls))

    def test_outgoing_dm_stops_retrying_after_ack(self):
        class FakePacket:
            id = 123

        class FakeRadio:
            def __init__(self):
                self.calls = []

            def sendText(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                kwargs["onResponse"]({"decoded": {"routing": {"errorReason": "NONE", "requestId": 123}}})
                return FakePacket()

        config = test_config(self.db_path)
        config["meshtastic"]["ack_timeout_seconds"] = 0.01
        config["meshtastic"]["ack_retries"] = 3
        mesh_interface = Interface(config)
        mesh_interface.interface = FakeRadio()

        mesh_interface.send_message("!433bed54", "Mail")

        self.assertEqual(1, len(mesh_interface.interface.calls))

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
