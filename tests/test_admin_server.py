import os
import tempfile
import threading
import unittest
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from admin_server import AdminHandler, check_password, make_password_hash
from database import Database
from http.server import ThreadingHTTPServer


class AdminServerTests(unittest.TestCase):
    def test_password_hash_round_trip(self):
        hashed = make_password_hash("secret")

        self.assertTrue(check_password("secret", hashed))
        self.assertFalse(check_password("wrong", hashed))

    def test_dashboard_uses_clickable_section_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            Database(db_path).record_user_command("!cabn", "CABN")
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/") as response:
                    dashboard = response.read().decode("utf-8")
                for path, label in (
                    ("/users", "Users"),
                    ("/addressbook", "AddressBook"),
                    ("/messages", "Mail"),
                    ("/board", "Message Board"),
                    ("/locations", "Locations"),
                    ("/checkins", "Check-Ins"),
                    ("/logs", "Logs"),
                ):
                    self.assertIn(f"<a class='dashboard-link' href='{path}'>", dashboard)
                    self.assertIn(f"<h2>{label}</h2>", dashboard)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_login_and_delete_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            db = Database(db_path)
            message_id = db.send_message("!from", "!to", "remove me")
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/messages") as response:
                    messages = response.read().decode("utf-8")
                self.assertIn("remove me", messages)
                self.assertIn("Edit", messages)

                edit_data = urlencode(
                    {"id": str(message_id), "sender_id": "!from", "recipient_id": "!to", "body": "edited body"}
                ).encode("utf-8")
                with opener.open(Request(f"{base}/edit-message", data=edit_data, method="POST")):
                    pass
                self.assertIn("edited body", Database(db_path).inbox("!to", include_deleted=True)[0]["body"])

                delete_data = urlencode({"id": str(message_id)}).encode("utf-8")
                with opener.open(Request(f"{base}/delete-message", data=delete_data, method="POST")):
                    pass

                self.assertEqual([], Database(db_path).inbox("!to", include_deleted=True))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_users_page_shows_recent_activity_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            db = Database(db_path)
            db.record_user_command("!cabn", "CABN")
            db.record_user_command("!cabn")
            db.record_user_command("!raw")
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/users") as response:
                    users = response.read().decode("utf-8")
                self.assertIn("Users", users)
                self.assertIn("<th>User</th>", users)
                self.assertIn("<th>AddressBook</th>", users)
                self.assertIn("<th>Commands</th>", users)
                self.assertIn("<th>First Interaction</th>", users)
                self.assertIn("<th>Last Interaction</th>", users)
                self.assertIn("CABN", users)
                self.assertIn("!cabn", users)
                self.assertIn("!raw", users)
                self.assertIn("<td>No</td>", users)
                self.assertIn("<td>2</td>", users)

                edit_data = urlencode(
                    {"node_id": "!raw", "display_name": "RAW1", "mail_listed": "1", "command_count": "7"}
                ).encode("utf-8")
                with opener.open(Request(f"{base}/edit-user", data=edit_data, method="POST")):
                    pass
                raw = Database(db_path).get_user("!raw")
                self.assertEqual("RAW1", raw["display_name"])
                self.assertEqual(1, raw["mail_listed"])
                self.assertEqual(7, raw["command_count"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_board_category_submenu_filters_and_deletes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            db = Database(db_path)
            db.set_display_name("!author", "CABN")
            news_id = db.create_board_post("news", "!author", "road is clear")
            db.create_board_post("trade", "!seller", "extra batteries")
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/board?category=news") as response:
                    board = response.read().decode("utf-8")
                self.assertIn("Local News", board)
                self.assertIn("road is clear", board)
                self.assertIn("CABN", board)
                self.assertIn("Edit", board)
                self.assertNotIn("extra batteries", board)
                self.assertNotIn("Main Menu Header", board)

                edit_data = urlencode(
                    {"id": str(news_id), "category": "rumors", "author_id": "!author", "body": "edited rumor"}
                ).encode("utf-8")
                with opener.open(Request(f"{base}/edit-board", data=edit_data, method="POST")) as response:
                    redirected = response.geturl()
                self.assertIn("/board?edited=1&category=rumors", redirected)
                edited = Database(db_path).get_board_post(news_id)
                self.assertEqual("rumors", edited["category"])
                self.assertEqual("edited rumor", edited["body"])

                delete_data = urlencode({"id": str(news_id), "category": "rumors"}).encode("utf-8")
                with opener.open(Request(f"{base}/delete-board", data=delete_data, method="POST")) as response:
                    redirected = response.geturl()

                self.assertIn("/board?deleted=1&category=rumors", redirected)
                with opener.open(f"{base}/board?category=rumors") as response:
                    board = response.read().decode("utf-8")
                self.assertNotIn("edited rumor", board)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_location_and_checkin_edit_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            db = Database(db_path)
            location_id = db.save_location("!loc", "LOC1", 35.0, -97.0, None, "old note")
            checkin_id = db.create_checkin_event("!net", "Old Net", starts_at=1000, duration_seconds=86400)
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/locations") as response:
                    locations = response.read().decode("utf-8")
                self.assertIn("Edit", locations)
                location_data = urlencode(
                    {
                        "id": str(location_id),
                        "creator_id": "!loc",
                        "creator_name": "LOC2",
                        "latitude": "36.5",
                        "longitude": "-98.5",
                        "altitude": "123",
                        "visibility": "public",
                        "body": "new note",
                    }
                ).encode("utf-8")
                with opener.open(Request(f"{base}/edit-location", data=location_data, method="POST")):
                    pass
                edited_location = Database(db_path).active_locations()[0]
                self.assertEqual("LOC2", edited_location["creator_name"])
                self.assertEqual("new note", edited_location["body"])
                self.assertEqual(36.5, edited_location["latitude"])

                with opener.open(f"{base}/checkins") as response:
                    checkins = response.read().decode("utf-8")
                self.assertIn("Edit", checkins)
                checkin_data = urlencode(
                    {
                        "id": str(checkin_id),
                        "title": "New Net",
                        "created_by": "!net",
                        "starts_at": "2000",
                        "ends_at": "3000",
                        "closed": "1",
                    }
                ).encode("utf-8")
                with opener.open(Request(f"{base}/edit-checkin", data=checkin_data, method="POST")):
                    pass
                with Database(db_path).connect() as conn:
                    edited_checkin = conn.execute("SELECT * FROM checkin_events WHERE id = ?", (checkin_id,)).fetchone()
                self.assertEqual("New Net", edited_checkin["title"])
                self.assertEqual(3000, edited_checkin["ends_at"])
                self.assertEqual(1, edited_checkin["closed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_addressbook_page_lists_and_removes_contacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "meshboard.db")
            db = Database(db_path)
            db.set_mail_listed("!cabn", "CABN", True)
            db.set_display_name("!seen", "SEEN")
            config = {
                "host": "127.0.0.1",
                "port": 0,
                "username": "sysop",
                "password_hash": make_password_hash("secret"),
                "session_secret": "test-secret",
                "database": {"path": db_path},
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), AdminHandler)
            server.config = config
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                login_data = urlencode({"username": "sysop", "password": "secret"}).encode("utf-8")
                with opener.open(Request(f"{base}/login", data=login_data, method="POST")):
                    pass

                with opener.open(f"{base}/addressbook") as response:
                    addressbook = response.read().decode("utf-8")
                self.assertIn("AddressBook", addressbook)
                self.assertIn("CABN", addressbook)
                self.assertIn("!cabn", addressbook)
                self.assertIn("Edit", addressbook)
                self.assertNotIn("!seen", addressbook)

                with opener.open(f"{base}/edit-addressbook?node_id=%21cabn") as response:
                    edit_page = response.read().decode("utf-8")
                self.assertIn("Edit AddressBook ID", edit_page)
                self.assertIn("CABN", edit_page)

                edit_data = urlencode({"node_id": "!cabn", "display_name": "HOME"}).encode("utf-8")
                with opener.open(Request(f"{base}/edit-addressbook", data=edit_data, method="POST")):
                    pass
                self.assertEqual("HOME", Database(db_path).get_user("!cabn")["display_name"])

                remove_data = urlencode({"node_id": "!cabn"}).encode("utf-8")
                with opener.open(Request(f"{base}/remove-addressbook", data=remove_data, method="POST")):
                    pass

                self.assertEqual([], Database(db_path).list_mail_contacts())
                self.assertIsNotNone(Database(db_path).get_user("!cabn"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
