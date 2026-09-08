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
