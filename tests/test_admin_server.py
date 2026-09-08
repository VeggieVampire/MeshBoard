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
                self.assertNotIn("extra batteries", board)

                delete_data = urlencode({"id": str(news_id), "category": "news"}).encode("utf-8")
                with opener.open(Request(f"{base}/delete-board", data=delete_data, method="POST")) as response:
                    redirected = response.geturl()

                self.assertIn("/board?deleted=1&category=news", redirected)
                with opener.open(f"{base}/board?category=news") as response:
                    board = response.read().decode("utf-8")
                self.assertNotIn("road is clear", board)
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
