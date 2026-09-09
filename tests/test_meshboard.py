import os
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import interface as interface_module
import local_ai_service
from bbs_system import BBSSystem, normalize_command
from config import DEFAULT_CONFIG
from database import Database
from interface import Interface
from location_service import distance_between_locations
from modules.Location import process_command as location_command
from modules import Mail
from modules.Games import escape_room, hot_cold, tic_tac_toe, zork
from modules import MessageBoard
from modules import WhosBeenHere
from modules import CheckIns


class DummyInterface:
    def __init__(self):
        self.handle_message = None
        self.handle_position = None
        self.sent = []

    def run(self):
        pass

    def send_message(self, user_id, message, reply_id=None):
        self.sent.append((user_id, message, reply_id))


class FakeAIHandler(BaseHTTPRequestHandler):
    last_payload = None

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        FakeAIHandler.last_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps({"response": "AI says trail clear"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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

    def test_local_ai_helper_is_optional(self):
        self.bbs.config["local_ai"] = {"enabled": False}
        self.assertEqual("Local AI is disabled in Config.", self.bbs.ask_local_ai("hello"))

    def test_local_ai_helper_calls_configured_service(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAIHandler)
        thread = None
        original_which = local_ai_service.shutil.which
        try:
            local_ai_service.shutil.which = lambda name: "ollama"
            self.bbs.local_ai_manager.popen = lambda *args, **kwargs: type(
                "FakeProcess",
                (),
                {
                    "poll": lambda self: None,
                    "terminate": lambda self: None,
                    "wait": lambda self, timeout=None: None,
                    "kill": lambda self: None,
                },
            )()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.bbs.config["local_ai"] = {
                "enabled": True,
                "url": f"http://127.0.0.1:{server.server_address[1]}/api/generate",
                "model": "tiny-local",
                "timeout_seconds": 5,
            }

            response = self.bbs.ask_local_ai("hello", system="short replies")

            self.assertEqual("AI says trail clear", response)
            self.assertEqual("tiny-local", FakeAIHandler.last_payload["model"])
            self.assertEqual("hello", FakeAIHandler.last_payload["prompt"])
            self.assertEqual("short replies", FakeAIHandler.last_payload["system"])
            self.assertFalse(FakeAIHandler.last_payload["stream"])
        finally:
            local_ai_service.shutil.which = original_which
            self.bbs.local_ai_manager.shutdown()
            server.shutdown()
            server.server_close()
            if thread:
                thread.join(timeout=5)

    def test_local_ai_menu_boots_answers_and_shutdowns(self):
        class FakeManager:
            def __init__(self):
                self.shutdowns = 0

            def ensure_started(self):
                return True, "starting"

            def wait_until_ready(self, stop_event=None):
                return True, "ready"

            def ask(self, prompt, system=None, model=None, timeout=None):
                return True, f"answer to {prompt}"

            def shutdown(self):
                self.shutdowns += 1

            def update_config(self, config):
                pass

        user = "!aiuser"
        fake = FakeManager()
        self.bbs.local_ai_manager = fake

        booting = self.bbs.handle_message(user, "7")
        self.assertIn("Local AI booting up", booting)
        for _ in range(20):
            if self.bbs.interface.sent:
                break
            time.sleep(0.05)
        self.assertIn("Local AI is ready", self.bbs.interface.sent[-1][1])

        answer = self.bbs.handle_message(user, "what is nearby?")
        self.assertIn("answer to what is nearby?", answer)

        ended = self.bbs.handle_message(user, "end of line")
        self.assertIn("Local AI shut down", ended)
        self.assertIn("Main Menu", ended)
        self.assertEqual(1, fake.shutdowns)

    def test_top_shuts_down_local_ai(self):
        class FakeManager:
            def __init__(self):
                self.shutdowns = 0

            def ensure_started(self):
                return True, "starting"

            def wait_until_ready(self, stop_event=None):
                return True, "ready"

            def shutdown(self):
                self.shutdowns += 1

            def update_config(self, config):
                pass

        user = "!aitop"
        fake = FakeManager()
        self.bbs.local_ai_manager = fake
        self.bbs.handle_message(user, "7")

        menu = self.bbs.handle_message(user, "top")

        self.assertIn("Main Menu", menu)
        self.assertEqual(1, fake.shutdowns)

    def test_leaving_local_ai_while_booting_suppresses_ready_message(self):
        class FakeManager:
            def __init__(self):
                self.shutdowns = 0

            def ensure_started(self):
                time.sleep(0.1)
                return True, "starting"

            def wait_until_ready(self, stop_event=None):
                return True, "ready"

            def shutdown(self):
                self.shutdowns += 1

            def update_config(self, config):
                pass

        user = "!aicancel"
        fake = FakeManager()
        self.bbs.local_ai_manager = fake

        self.bbs.handle_message(user, "7")
        menu = self.bbs.handle_message(user, "top")
        time.sleep(0.2)

        self.assertIn("Main Menu", menu)
        self.assertEqual(1, fake.shutdowns)
        self.assertEqual([], self.bbs.interface.sent)

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
        self.assertIn("4. Check In", menu)
        self.assertNotIn("My Saved", menu)
        self.assertNotIn("Hot Cold", menu)

    def test_location_checkin_shows_in_locations_and_checkins(self):
        user = "!abc12345"
        self.bbs.db.set_mail_listed(user, "CABN", True)
        self.bbs.update_node_location(user, {"latitude": 35.0, "longitude": -97.0, "altitude": 300})
        self.bbs.users[user] = {"menu": ["main"]}

        prompt = location_command(user, "4", self.bbs)
        self.assertIn("Send a comment", prompt)
        checked = location_command(user, "Very cool", self.bbs)
        self.assertIn("Checked in at your current location", checked)

        locations = self.bbs.db.active_locations()
        self.assertEqual(1, len(locations))
        self.assertEqual("checkin", locations[0]["kind"])
        self.assertIn("Very cool", locations[0]["body"])

        here = location_command(user, "1", self.bbs)
        self.assertIn("Check-in", here)
        self.assertIn("Very cool", here)

        checkins = CheckIns.enter_menu(user, self.bbs)
        self.assertIn("Recent Location Check-Ins", checkins)
        self.assertIn("CABN", checkins)
        self.assertIn("Very cool", checkins)

        main_menu_checkins = self.bbs.handle_message(user, "6")
        self.assertIn("Recent Location Check-Ins", main_menu_checkins)
        self.assertIn("Very cool", main_menu_checkins)

    def test_location_checkin_without_comment_is_allowed(self):
        user = "!skip1234"
        self.bbs.update_node_location(user, {"latitude": 35.0, "longitude": -97.0})
        self.bbs.users[user] = {"menu": ["main"]}

        location_command(user, "4", self.bbs)
        checked = location_command(user, "skip", self.bbs)

        self.assertIn("Checked in at your current location", checked)
        self.assertEqual("Checked in here.", self.bbs.db.location_checkins()[0]["body"])

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
        self.assertIn("Hello. This is MeshBoard", response)
        self.assertIn("Main Menu", response)
        self.assertNotIn("Invalid", response)

    def test_unknown_main_menu_text_shows_first_contact_help(self):
        user = "!passerby"
        self.bbs.handle_message(user, "top")

        response = self.bbs.handle_message(user, "hello there")

        self.assertIn("Hello. This is MeshBoard", response)
        self.assertIn("send top", response.lower())
        self.assertIn("Main Menu", response)
        self.assertNotIn("Invalid", response)

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
        self.assertEqual("top", normalize_command("menu"))
        self.assertEqual("top", normalize_command("Main Menu"))
        self.assertEqual("cd ..", normalize_command("cd .."))
        self.assertEqual("cd ..", normalize_command("Cd .. "))
        self.assertEqual("cd ..", normalize_command("cd.."))
        self.assertEqual("cd ..", normalize_command("Cd.."))

    def test_menu_aliases_show_main_menu_without_first_contact_help(self):
        for command in ("menu", "Main Menu"):
            with self.subTest(command=command):
                response = self.bbs.handle_message(f"!menu{command}", command)

                self.assertIn("Main Menu", response)
                self.assertNotIn("Hello. This is MeshBoard", response)

    def test_any_unknown_words_at_main_menu_show_first_contact_help(self):
        for command in ("hello", "test message", "what is this", "any words here"):
            with self.subTest(command=command):
                user = f"!words{len(command)}"
                self.bbs.handle_message(user, "top")

                response = self.bbs.handle_message(user, command)

                self.assertIn("Hello. This is MeshBoard", response)
                self.assertIn("Main Menu", response)
                self.assertNotIn("Invalid", response)

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
        self.assertIn("Added to AddressBook as nder", Mail.process_command(user, "yes", self.bbs))

        for index in range(9):
            self.bbs.db.set_mail_listed(f"!node{index}", f"User{index}", True)

        response = Mail.process_command(user, "send", self.bbs)
        self.assertIn("0. All", response)
        self.assertIn("1. nder", response)
        self.assertIn("9. Next", response)
        response = Mail.process_command(user, "9", self.bbs)
        self.assertIn("AddressBook 9-10", response)

    def test_mail_addressbook_custom_simple_id(self):
        user = "!sender"
        self.bbs.users[user] = {"menu": ["main"]}

        Mail.process_command(user, "add addressBook", self.bbs)
        response = Mail.process_command(user, "HOME", self.bbs)

        self.assertIn("Added to AddressBook as HOME", response)
        self.assertEqual("HOME", self.bbs.db.list_mail_contacts()[0]["display_name"])

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
        self.assertIn("From: Sender", detail)
        self.assertIn("1. Reply", detail)
        self.assertIn("2. Archive", detail)
        self.assertIn("3. Back", detail)
        self.assertEqual(0, self.bbs.db.unread_count(recipient))

        reply_prompt = Mail.process_command(recipient, "1", self.bbs)
        self.assertIn("Reply to Sender", reply_prompt)
        sent = Mail.process_command(recipient, "Thanks", self.bbs)
        self.assertIn("Message saved for Sender", sent)
        self.assertEqual("Thanks", self.bbs.db.inbox(sender)[0]["body"])

        Mail.process_command(recipient, "inbox", self.bbs)
        Mail.process_command(recipient, "1", self.bbs)
        archived = Mail.process_command(recipient, "2", self.bbs)
        self.assertIn("Message archived", archived)
        self.assertEqual([], self.bbs.db.inbox(recipient))

        archive = Mail.process_command(recipient, "archive", self.bbs)
        self.assertIn("Gate is fixed.", archive)
        deleted = Mail.process_command(recipient, "delete 1", self.bbs)
        self.assertIn("Archived message deleted", deleted)
        self.assertEqual([], self.bbs.db.archived_inbox(recipient))

    def test_mail_inbox_records_check_time_and_marks_unread_with_star(self):
        sender = "!sender"
        recipient = "!recipient"
        self.bbs.db.set_mail_listed(sender, "SNDR", True)
        self.bbs.db.set_mail_listed(recipient, "RCPT", True)
        self.bbs.db.send_message(sender, recipient, "Unread note")

        self.bbs.users[recipient] = {"menu": ["main"]}
        before = int(time.time())
        inbox = Mail.process_command(recipient, "inbox", self.bbs)
        after = int(time.time())
        user = self.bbs.db.get_user(recipient)

        self.assertIn("1. * SNDR", inbox)
        self.assertGreaterEqual(user["last_mail_check_at"], before)
        self.assertLessEqual(user["last_mail_check_at"], after)
        self.assertEqual(1, self.bbs.db.unread_count(recipient))

    def test_mail_only_shows_messages_for_current_user(self):
        user = "!user"
        other = "!other"
        sender = "!sender"
        self.bbs.db.set_mail_listed(user, "USER", True)
        self.bbs.db.set_mail_listed(other, "OTHR", True)
        self.bbs.db.set_mail_listed(sender, "SNDR", True)
        self.bbs.db.send_message(sender, user, "for user only")
        other_message_id = self.bbs.db.send_message(sender, other, "for other only")
        self.bbs.db.soft_delete_message(other_message_id, other)

        self.bbs.users[user] = {"menu": ["main"]}
        inbox = Mail.process_command(user, "inbox", self.bbs)
        self.assertIn("for user only", inbox)
        self.assertNotIn("for other only", inbox)

        archive = Mail.process_command(user, "archive", self.bbs)
        self.assertNotIn("for other only", archive)

    def test_mail_send_all_broadcasts_to_addressbook_contacts(self):
        sender = "!sender"
        first = "!first"
        second = "!second"
        self.bbs.db.set_mail_listed(sender, "SEND", True)
        self.bbs.db.set_mail_listed(first, "ONE1", True)
        self.bbs.db.set_mail_listed(second, "TWO2", True)
        self.bbs.users[sender] = {"menu": ["main"]}

        prompt = Mail.process_command(sender, "send", self.bbs)
        self.assertIn("0. All", prompt)
        body_prompt = Mail.process_command(sender, "0", self.bbs)
        self.assertIn("To: All AddressBook contacts", body_prompt)
        sent = Mail.process_command(sender, "Radio net at 7", self.bbs)

        self.assertIn("Broadcast message saved for 2 contacts", sent)
        self.assertEqual("Radio net at 7", self.bbs.db.inbox(first)[0]["body"])
        self.assertEqual("Radio net at 7", self.bbs.db.inbox(second)[0]["body"])
        self.assertEqual([], self.bbs.db.inbox(sender))

    def test_chunk_long_outgoing_messages(self):
        interface = Interface(test_config(self.db_path))
        chunks = interface.chunk_message("alpha beta gamma delta epsilon zeta eta theta")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 40 for chunk in chunks))
        self.assertTrue(chunks[0].endswith(f"1 of {len(chunks)}"))
        self.assertTrue(chunks[-1].endswith(f"{len(chunks)} of {len(chunks)}"))

    def test_first_screen_menus_fit_single_radio_packet(self):
        self.bbs.users["!abc12345"] = {"menu": ["main"]}
        menus = [
            self.bbs.display_menu("!abc12345"),
            self.bbs.display_submenu("Games"),
            Mail.display_menu(),
            WhosBeenHere.display_menu(),
            MessageBoard.display_menu(),
            CheckIns.display_menu(),
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
        self.assertIn("Add you", self.bbs.handle_message(user, "3"))
        self.assertIn("Added to AddressBook", self.bbs.handle_message(user, "yes"))
        self.assertIn("Archive", self.bbs.handle_message(user, "4"))

    def test_disabled_game_is_hidden_from_games_menu(self):
        self.bbs.db.set_game_enabled("zork", False)
        user = "!nogame"
        self.bbs.users[user] = {"menu": ["main", "Games"]}

        menu = self.bbs.display_submenu("Games")
        self.assertIn("Hot Cold", menu)
        self.assertNotIn("ZORK", menu)

        response = self.bbs.handle_submenu(user, "2", self.bbs.menu_modules["Games"]["submodules"])
        self.assertIn("Tic Tac Toe", response)

    def test_whos_been_here_lists_recent_users_newest_first(self):
        now = int(time.time())
        self.bbs.db.set_mail_listed("!old", "LAKE", True)
        self.bbs.db.upsert_user("!old", seen_at=now - 3 * 86400)
        self.bbs.db.set_mail_listed("!new", "CABN", True)
        self.bbs.db.upsert_user("!new", seen_at=now)

        self.bbs.users["!viewer"] = {"menu": ["main"]}
        response = self.bbs.handle_message("!viewer", "4")

        self.assertLess(response.index("CABN"), response.index("LAKE"))
        self.assertIn("Seen: Today", response)
        self.assertIn("Seen: 3 days ago", response)

    def test_whos_been_here_shows_command_counts(self):
        user = "!counter"

        self.bbs.handle_message(user, "top")
        self.bbs.handle_message(user, "top")
        self.bbs.db.create_board_post("general", user, "Posted outside message handling.")
        self.bbs.db.create_checkin_event(user)

        row = self.bbs.db.get_user(user)
        self.assertEqual(2, row["command_count"])

        self.bbs.users["!viewer"] = {"menu": ["main"]}
        response = self.bbs.handle_message("!viewer", "4")
        self.assertIn("Cmds: 2", response)

    def test_message_board_category_post_and_read(self):
        user = "!poster"
        self.bbs.db.set_mail_listed(user, "POST", True)

        menu = MessageBoard.display_menu()
        self.assertIn("1. General Discussion", menu)
        self.assertIn("5. Rumors & Gossip", menu)
        self.assertNotIn("Main Menu Header", menu)

        category = MessageBoard.process_command(user, "1", self.bbs)
        self.assertIn("General Discussion", category)
        self.assertIn("POST to add", category)

        prompt = MessageBoard.process_command(user, "POST", self.bbs)
        self.assertIn("New post", prompt)
        posted = MessageBoard.process_command(user, "Trail is clear.", self.bbs)
        self.assertIn("Posted", posted)
        self.assertIn("POST", posted)
        self.assertIn("Trail is clear.", posted)

        detail = MessageBoard.process_command(user, "1", self.bbs)
        self.assertIn("From: POST", detail)
        self.assertIn("Trail is clear.", detail)
        self.assertIn("3. Back", detail)

    def test_events_checkin_tracks_addressbook_contacts(self):
        self.bbs.db.set_mail_listed("!cabn", "CABN", True)
        self.bbs.db.set_mail_listed("!lake", "LAKE", True)
        self.bbs.users["!cabn"] = {"menu": ["main"]}

        self.bbs.handle_message("!cabn", "5")
        events = self.bbs.handle_message("!cabn", "4")
        self.assertIn("No active check-in", events)

        started = self.bbs.handle_message("!cabn", "1")

        self.assertIn("Check-in started for 24 hours", started)
        self.assertIn("In: CABN", started)
        self.assertIn("Out: LAKE", started)

        self.bbs.users["!lake"] = {"menu": ["main", "Message Board"], "module_control": MessageBoard}
        MessageBoard.process_command("!lake", "4", self.bbs)
        checked = MessageBoard.process_command("!lake", "1", self.bbs)

        self.assertIn("Checked in", checked)
        self.assertIn("In: CABN, LAKE", checked)
        self.assertIn("Out: None", checked)

    def test_events_checkin_expires_after_24_hours(self):
        event_id = self.bbs.db.create_checkin_event("!net", starts_at=1000, duration_seconds=86400)
        self.bbs.db.check_in(event_id, "!net", checked_in_at=1000)

        self.assertIsNotNone(self.bbs.db.active_checkin_event(now=1000 + 86399))
        self.assertIsNone(self.bbs.db.active_checkin_event(now=1000 + 86400))

    def test_event_post_back_returns_to_event_posts(self):
        user = "!eventposter"
        self.bbs.users[user] = {"menu": ["main"]}

        self.bbs.handle_message(user, "5")
        self.bbs.handle_message(user, "4")
        self.bbs.handle_message(user, "3")
        self.bbs.handle_message(user, "post")
        self.bbs.handle_message(user, "Net at 7pm.")
        detail = self.bbs.handle_message(user, "1")
        back = self.bbs.handle_message(user, "3")

        self.assertIn("From:", detail)
        self.assertIn("Events Posts", back)
        self.assertIn("Net at 7pm.", back)

    def test_new_menu_hardening_sequences_do_not_crash(self):
        cases = {
            "main": ["weather?", "0", "999", "menu", "main menu"],
            "seen": ["top", "4", "next", "wat", "cd .."],
            "mail": ["top", "3", "wat", "2", "x", "9", "back", "3", "12", "AB C", "HOME"],
            "board": ["top", "5", "wat", "0", "5", "post", "", "Rumor text", "back"],
            "events": ["top", "5", "4", "wat", "1", "2", "3", "post", "", "Event post", "1", "3"],
        }
        for name, commands in cases.items():
            with self.subTest(name=name):
                user = f"!hard{name}"
                self.bbs.db.set_mail_listed("!h1", "H001", True)
                self.bbs.db.set_mail_listed(user, name[:4].upper(), True)
                for command in commands:
                    response = self.bbs.handle_message(user, command)
                    self.assertIsInstance(response, str)
                    self.assertTrue(response.strip())

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
