import ast
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
from contextlib import contextmanager
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode

import backup_manager
import config as mesh_config
from database import Database


APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("MESHBOARD_ADMIN_CONFIG", os.path.join(APP_DIR, "admin_config.json"))
MESH_CONFIG_PATH = os.environ.get("MESHBOARD_CONFIG", os.path.join(APP_DIR, mesh_config.CONFIG_FILE))
SESSION_COOKIE = "meshboard_admin"
SESSION_MAX_AGE = 12 * 60 * 60
BOARD_CATEGORIES = [
    ("general", "General Discussion"),
    ("news", "Local News"),
    ("trade", "Buy / Sell / Trade"),
    ("events", "Events"),
    ("rumors", "Rumors & Gossip"),
]
GAME_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        config = json.load(file)
    config.setdefault("host", "0.0.0.0")
    config.setdefault("port", 8080)
    config.setdefault("username", "sysop")
    config.setdefault("database", {"path": "meshboard.db"})
    return config


def make_password_hash(password, salt=None, iterations=200000):
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def check_password(password, password_hash):
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt_bytes = base64.urlsafe_b64decode(salt.encode("ascii"))
        expected_bytes = base64.urlsafe_b64decode(expected.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations))
        return hmac.compare_digest(actual, expected_bytes)
    except Exception:
        return False


def resolve_db_path(config):
    path = config.get("database", {}).get("path", "meshboard.db")
    if not os.path.isabs(path):
        path = os.path.join(APP_DIR, path)
    return path


def resolve_games_dir(config):
    path = config.get("games_dir", os.path.join(APP_DIR, "modules", "Games"))
    if not os.path.isabs(path):
        path = os.path.join(APP_DIR, path)
    return path


def resolve_backup_app_dir(config):
    path = config.get("app_dir", APP_DIR)
    if not os.path.isabs(path):
        path = os.path.join(APP_DIR, path)
    return path


def resolve_mesh_config_path(config):
    path = config.get("mesh_config_path", MESH_CONFIG_PATH)
    if not os.path.isabs(path):
        path = os.path.join(APP_DIR, path)
    return path


@contextmanager
def db_connect(config):
    conn = sqlite3.connect(resolve_db_path(config))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def fmt_time(timestamp):
    if not timestamp:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))


def clip(value, length=120):
    value = "" if value is None else str(value)
    value = " ".join(value.split())
    if len(value) <= length:
        return value
    return value[: length - 3].rstrip() + "..."


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def form_button(action, fields, label, danger=True):
    hidden = "\n".join(
        f'<input type="hidden" name="{esc(key)}" value="{esc(value)}">' for key, value in fields.items()
    )
    klass = "danger" if danger else "button"
    return f'<form method="post" action="{action}" class="inline">{hidden}<button class="{klass}">{esc(label)}</button></form>'


def link_button(path, label):
    return f'<a class="button" href="{esc(path)}">{esc(label)}</a>'


def checked(value):
    return " checked" if value else ""


def selected(value, expected):
    return " selected" if str(value) == str(expected) else ""


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "MeshBoardAdmin/1.0"

    @property
    def config(self):
        return self.server.config

    def log_message(self, fmt, *args):
        print("{} {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args))

    def signed_session(self, username):
        issued = str(int(time.time()))
        payload = f"{username}:{issued}"
        secret = self.config["session_secret"].encode("utf-8")
        signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("ascii")

    def current_user(self):
        header = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(header)
        except cookies.CookieError:
            return None
        morsel = jar.get(SESSION_COOKIE)
        if not morsel:
            return None
        try:
            raw = base64.urlsafe_b64decode(morsel.value.encode("ascii")).decode("utf-8")
            username, issued, signature = raw.rsplit(":", 2)
            if username != self.config["username"]:
                return None
            if int(time.time()) - int(issued) > SESSION_MAX_AGE:
                return None
            payload = f"{username}:{issued}"
            expected = hmac.new(
                self.config["session_secret"].encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(signature, expected):
                return username
        except Exception:
            return None
        return None

    def read_post(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return {key: values[-1] for key, values in parse_qs(body).items()}

    def redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, title, body, status=200):
        content = self.layout(title, body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def layout(self, title, body):
        nav = ""
        if self.current_user():
            links = [
                ("/", "Dashboard"),
                ("/users", "Users"),
                ("/addressbook", "AddressBook"),
                ("/messages", "Mail"),
                ("/board", "Board"),
                ("/locations", "Locations"),
                ("/games", "Games"),
                ("/checkins", "Check-Ins"),
                ("/backups", "Backups"),
                ("/config", "Config"),
                ("/logs", "Logs"),
                ("/logout", "Logout"),
            ]
            nav = "<nav>{}</nav>".format("".join(f'<a href="{path}">{label}</a>' for path, label in links))
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - MeshBoard Admin</title>
<style>
body {{ margin: 0; font-family: system-ui, sans-serif; background: #0f1720; color: #e6edf3; }}
header {{ background: #172233; padding: 12px 16px; border-bottom: 1px solid #2d3a4d; }}
h1 {{ margin: 0; font-size: 20px; }}
main {{ padding: 16px; max-width: 1100px; margin: 0 auto; }}
nav {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }}
nav a, .button, button {{ background: #243244; color: #e6edf3; border: 1px solid #38475b; border-radius: 6px; padding: 8px 10px; text-decoration: none; }}
button {{ cursor: pointer; }}
.danger {{ background: #5f1f2a; border-color: #8a2e3d; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }}
.card {{ background: #151f2d; border: 1px solid #2d3a4d; border-radius: 8px; padding: 12px; }}
.dashboard-link {{ display: block; background: #151f2d; border: 1px solid #2d3a4d; border-radius: 8px; padding: 14px; color: #e6edf3; text-decoration: none; }}
.dashboard-link:hover {{ border-color: #5b7190; background: #1a2636; }}
.dashboard-link h2 {{ margin-top: 0; }}
.tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }}
.tabs a {{ background: #151f2d; color: #e6edf3; border: 1px solid #38475b; border-radius: 6px; padding: 8px 10px; text-decoration: none; }}
.tabs a.active {{ background: #2d415d; border-color: #5b779b; }}
.muted {{ color: #9fb0c3; }}
table {{ width: 100%; border-collapse: collapse; background: #151f2d; }}
th, td {{ padding: 8px; border-bottom: 1px solid #2d3a4d; text-align: left; vertical-align: top; }}
th {{ color: #a9bdd3; }}
input, textarea, select {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 6px 0 12px; background: #101722; color: #e6edf3; border: 1px solid #38475b; border-radius: 6px; }}
textarea {{ min-height: 120px; }}
input[type="checkbox"] {{ width: auto; margin-right: 8px; }}
.inline {{ display: inline; }}
.flash {{ background: #19351f; border: 1px solid #2f693a; padding: 10px; border-radius: 6px; }}
</style>
</head>
<body>
<header><h1>MeshBoard Admin</h1>{nav}</header>
<main>{body}</main>
</body>
</html>"""

    def require_auth(self):
        if not self.current_user():
            self.redirect("/login")
            return False
        return True

    def do_GET(self):
        if self.path.startswith("/login"):
            self.show_login()
            return
        if self.path.startswith("/logout"):
            self.send_response(303)
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if not self.require_auth():
            return
        path = self.path.split("?", 1)[0]
        routes = {
            "/": self.show_dashboard,
            "/users": self.show_users,
            "/edit-user": self.show_edit_user,
            "/addressbook": self.show_addressbook,
            "/edit-addressbook": self.show_edit_addressbook,
            "/messages": self.show_messages,
            "/message-archives": self.show_message_archives,
            "/edit-message": self.show_edit_message,
            "/board": self.show_board,
            "/edit-board": self.show_edit_board,
            "/locations": self.show_locations,
            "/edit-location": self.show_edit_location,
            "/games": self.show_games,
            "/edit-game": self.show_edit_game,
            "/import-game": self.show_import_game,
            "/checkins": self.show_checkins,
            "/edit-checkin": self.show_edit_checkin,
            "/backups": self.show_backups,
            "/config": self.show_config,
            "/logs": self.show_logs,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self.send_html("Not Found", "<p>Not found.</p>", 404)

    def do_POST(self):
        if self.path == "/login":
            self.handle_login()
            return
        if not self.require_auth():
            return
        data = self.read_post()
        action = self.path
        try:
            if action == "/delete-message":
                self.delete_row("messages", data.get("id"))
                self.redirect("/messages?deleted=1")
            elif action == "/archive-message":
                self.archive_message(data.get("id"))
                self.redirect("/messages?archived=1")
            elif action == "/edit-message":
                error = self.update_message(data)
                if error:
                    self.show_edit_message(error, data)
                else:
                    self.redirect("/messages?edited=1")
            elif action == "/delete-board":
                self.mark_deleted("board_posts", data.get("id"))
                query = {"deleted": "1"}
                if data.get("category"):
                    query["category"] = data["category"]
                self.redirect("/board?" + urlencode(query))
            elif action == "/edit-board":
                error = self.update_board_post(data)
                if error:
                    self.show_edit_board(error, data)
                else:
                    query = {"edited": "1"}
                    if data.get("category"):
                        query["category"] = data["category"]
                    self.redirect("/board?" + urlencode(query))
            elif action == "/delete-location":
                self.mark_deleted("locations", data.get("id"))
                self.redirect("/locations?deleted=1")
            elif action == "/edit-location":
                error = self.update_location(data)
                if error:
                    self.show_edit_location(error, data)
                else:
                    self.redirect("/locations?edited=1")
            elif action == "/set-game-enabled":
                self.set_game_enabled(data.get("module_name"), data.get("enabled") == "1")
                self.redirect("/games?updated=1")
            elif action == "/edit-game":
                error = self.update_game(data)
                if error:
                    self.show_edit_game(error, data)
                else:
                    self.redirect("/games?edited=1")
            elif action == "/import-game":
                error = self.import_game(data)
                if error:
                    self.show_import_game(error, data)
                else:
                    self.redirect("/games?imported=1")
            elif action == "/delete-user":
                self.delete_user(data.get("node_id"))
                self.redirect("/users?deleted=1")
            elif action == "/edit-user":
                error = self.update_user(data)
                if error:
                    self.show_edit_user(error, data)
                else:
                    self.redirect("/users?edited=1")
            elif action == "/remove-addressbook":
                self.set_addressbook_listed(data.get("node_id"), False)
                self.redirect("/addressbook?removed=1")
            elif action == "/edit-addressbook":
                error = self.update_addressbook_id(data.get("node_id"), data.get("display_name"))
                if error:
                    self.show_edit_addressbook(error, data.get("node_id"), data.get("display_name"))
                else:
                    self.redirect("/addressbook?edited=1")
            elif action == "/close-checkin":
                self.close_checkin(data.get("id"))
                self.redirect("/checkins?closed=1")
            elif action == "/edit-checkin":
                error = self.update_checkin(data)
                if error:
                    self.show_edit_checkin(error, data)
                else:
                    self.redirect("/checkins?edited=1")
            elif action == "/create-backup":
                backup_manager.create_backup("manual", app_dir=resolve_backup_app_dir(self.config))
                self.redirect("/backups?created=1")
            elif action == "/restore-backup":
                error = self.restore_backup(data.get("filename"))
                if error:
                    self.show_backups(error)
                else:
                    self.redirect("/backups?restored=1")
            elif action == "/backup-retention":
                error = self.update_backup_retention(data.get("retention_days"))
                if error:
                    self.show_backups(error)
                else:
                    self.redirect("/backups?settings=1")
            elif action == "/config":
                error = self.update_config(data)
                if error:
                    self.show_config(error, data)
                else:
                    self.redirect("/config?saved=1")
            else:
                self.send_html("Not Found", "<p>Not found.</p>", 404)
        except sqlite3.Error as exc:
            self.send_html("Database Error", f"<p>{esc(exc)}</p>", 500)

    def show_login(self):
        body = """<div class="card">
<h2>Login</h2>
<form method="post" action="/login">
<label>Username</label>
<input name="username" autocomplete="username">
<label>Password</label>
<input name="password" type="password" autocomplete="current-password">
<button>Login</button>
</form>
</div>"""
        self.send_html("Login", body)

    def handle_login(self):
        data = self.read_post()
        ok = (
            data.get("username") == self.config.get("username")
            and check_password(data.get("password", ""), self.config.get("password_hash", ""))
        )
        if not ok:
            self.send_html("Login", "<p>Bad login.</p><p><a class='button' href='/login'>Try again</a></p>", 403)
            return
        session = self.signed_session(data["username"])
        self.send_response(303)
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax")
        self.send_header("Location", "/")
        self.end_headers()

    def show_dashboard(self):
        with db_connect(self.config) as conn:
            dashboard_links = [
                ("/users", "Users", conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"], "recent operators"),
                (
                    "/addressbook",
                    "AddressBook",
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM users
                        WHERE mail_listed = 1 AND display_name IS NOT NULL AND display_name != ''
                        """
                    ).fetchone()["count"],
                    "listed contacts",
                ),
                (
                    "/messages",
                    "Mail",
                    conn.execute("SELECT COUNT(*) AS count FROM messages WHERE deleted_by_recipient = 0").fetchone()["count"],
                    "active messages",
                ),
                (
                    "/board",
                    "Message Board",
                    conn.execute("SELECT COUNT(*) AS count FROM board_posts WHERE deleted = 0").fetchone()["count"],
                    "active posts",
                ),
                (
                    "/locations",
                    "Locations",
                    conn.execute("SELECT COUNT(*) AS count FROM locations WHERE deleted = 0").fetchone()["count"],
                    "active notes",
                ),
                ("/games", "Games", len(self.discover_games(conn)), "installed plugins"),
                ("/backups", "Backups", len(backup_manager.list_backups()), "saved restore points"),
                (
                    "/checkins",
                    "Check-Ins",
                    conn.execute("SELECT COUNT(*) AS count FROM checkin_events").fetchone()["count"],
                    "events",
                ),
                ("/logs", "Logs", "", "recent service output"),
                ("/config", "Config", "", "customization"),
            ]
        body = "<div class='grid'>" + "".join(
            (
                f"<a class='dashboard-link' href='{esc(path)}'>"
                f"<h2>{esc(label)}</h2>"
                f"<p>{esc(count)}</p>"
                f"<p class='muted'>{esc(description)}</p>"
                "</a>"
            )
            for path, label, count, description in dashboard_links
        ) + "</div>"
        body += "<p class='muted'>Local-only SysOp tools. Edit/delete/remove/close actions change meshboard.db immediately.</p>"
        self.send_html("Dashboard", body)

    def show_users(self):
        with db_connect(self.config) as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 200").fetchall()
        body = "<table><tr><th>User</th><th>Node</th><th>AddressBook</th><th>Commands</th><th>First Interaction</th><th>Last Interaction</th><th>Checked Mail</th><th></th></tr>"
        for row in rows:
            addressbook = row["display_name"] if row["mail_listed"] and row["display_name"] else "No"
            user_name = row["display_name"] or row["node_id"]
            edit_path = "/edit-user?" + urlencode({"node_id": row["node_id"]})
            body += (
                f"<tr><td>{esc(user_name)}</td><td>{esc(row['node_id'])}</td>"
                f"<td>{esc(addressbook)}</td><td>{row['command_count']}</td>"
                f"<td>{fmt_time(row['first_seen'])}</td><td>{fmt_time(row['last_seen'])}</td>"
                f"<td>{fmt_time(row['last_mail_check_at'])}</td>"
                f"<td>{link_button(edit_path, 'Edit')} {form_button('/delete-user', {'node_id': row['node_id']}, 'Delete')}</td></tr>"
            )
        body += "</table>"
        self.send_html("Users", body)

    def show_edit_user(self, error="", values=None):
        values = values or {}
        node_id = values.get("node_id") or self.query_value("node_id")
        with db_connect(self.config) as conn:
            row = conn.execute("SELECT * FROM users WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            self.send_html("Users", "<p>User not found.</p><p><a class='button' href='/users'>Back</a></p>", 404)
            return
        display_name = values.get("display_name", row["display_name"] or "")
        command_count = values.get("command_count", row["command_count"])
        mail_listed = values.get("mail_listed") if values else row["mail_listed"]
        body = "<div class='card'><h2>Edit User</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-user'>"
            f"<input type='hidden' name='node_id' value='{esc(row['node_id'])}'>"
            f"<p class='muted'>{esc(row['node_id'])}</p>"
            "<label>Display / AddressBook ID</label>"
            f"<input name='display_name' maxlength='32' value='{esc(display_name)}'>"
            "<label><input type='checkbox' name='mail_listed' value='1'"
            f"{checked(mail_listed)}> Listed in AddressBook</label>"
            "<label>Command Count</label>"
            f"<input name='command_count' type='number' min='0' value='{esc(command_count)}'>"
            "<button>Save</button> "
            "<a class='button' href='/users'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit User", body)

    def show_addressbook(self):
        with db_connect(self.config) as conn:
            rows = conn.execute(
                """
                SELECT node_id, display_name, first_seen, last_seen
                FROM users
                WHERE mail_listed = 1 AND display_name IS NOT NULL AND display_name != ''
                ORDER BY display_name COLLATE NOCASE, last_seen DESC
                LIMIT 300
                """
            ).fetchall()
        body = "<table><tr><th>ID</th><th>Node</th><th>First Seen</th><th>Last Seen</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-addressbook?" + urlencode({"node_id": row["node_id"]})
            body += (
                f"<tr><td>{esc(row['display_name'])}</td><td>{esc(row['node_id'])}</td>"
                f"<td>{fmt_time(row['first_seen'])}</td><td>{fmt_time(row['last_seen'])}</td>"
                f"<td>{link_button(edit_path, 'Edit')} {form_button('/remove-addressbook', {'node_id': row['node_id']}, 'Remove')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='5'>AddressBook is empty.</td></tr>"
        body += "</table>"
        self.send_html("AddressBook", body)

    def show_edit_addressbook(self, error="", node_id="", display_name=""):
        node_id = node_id or self.query_value("node_id")
        with db_connect(self.config) as conn:
            row = conn.execute(
                """
                SELECT node_id, display_name
                FROM users
                WHERE node_id = ? AND mail_listed = 1
                """,
                (node_id,),
            ).fetchone()
        if not row:
            self.send_html("AddressBook", "<p>AddressBook contact not found.</p><p><a class='button' href='/addressbook'>Back</a></p>", 404)
            return
        display_name = display_name if display_name is not None else row["display_name"]
        display_name = display_name or row["display_name"]
        body = "<div class='card'><h2>Edit AddressBook ID</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-addressbook'>"
            f"<input type='hidden' name='node_id' value='{esc(row['node_id'])}'>"
            f"<p class='muted'>{esc(row['node_id'])}</p>"
            "<label>4-character ID</label>"
            f"<input name='display_name' maxlength='4' value='{esc(display_name)}' autofocus>"
            "<button>Save</button> "
            "<a class='button' href='/addressbook'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit AddressBook", body)

    def show_messages(self):
        with db_connect(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE deleted_by_recipient = 0
                ORDER BY created_at DESC, id DESC
                LIMIT 300
                """
            ).fetchall()
        body = "<p>{}</p>".format(link_button("/message-archives", "Archived Mail"))
        body += "<table><tr><th>ID</th><th>From</th><th>To</th><th>When</th><th>Body</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-message?" + urlencode({"id": row["id"]})
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['sender_id'])}</td><td>{esc(row['recipient_id'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{esc(clip(row['body']))}</td>"
                f"<td>{link_button(edit_path, 'Edit')} "
                f"{form_button('/archive-message', {'id': row['id']}, 'Archive', False)} "
                f"{form_button('/delete-message', {'id': row['id']}, 'Delete')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='6'>No active mail messages.</td></tr>"
        body += "</table>"
        self.send_html("Mail", body)

    def show_message_archives(self):
        with db_connect(self.config) as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE deleted_by_recipient = 1
                ORDER BY created_at DESC, id DESC
                LIMIT 300
                """
            ).fetchall()
        body = "<p>{}</p>".format(link_button("/messages", "Active Mail"))
        body += "<table><tr><th>ID</th><th>From</th><th>To</th><th>When</th><th>Body</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-message?" + urlencode({"id": row["id"]})
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['sender_id'])}</td><td>{esc(row['recipient_id'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{esc(clip(row['body']))}</td>"
                f"<td>{link_button(edit_path, 'Edit')} {form_button('/delete-message', {'id': row['id']}, 'Delete')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='6'>No archived mail messages.</td></tr>"
        body += "</table>"
        self.send_html("Archived Mail", body)

    def show_edit_message(self, error="", values=None):
        values = values or {}
        row_id = values.get("id") or self.query_value("id")
        with db_connect(self.config) as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (row_id,)).fetchone()
        if not row:
            self.send_html("Mail", "<p>Message not found.</p><p><a class='button' href='/messages'>Back</a></p>", 404)
            return
        sender_id = values.get("sender_id", row["sender_id"])
        recipient_id = values.get("recipient_id", row["recipient_id"])
        body_text = values.get("body", row["body"])
        body = "<div class='card'><h2>Edit Mail Message</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-message'>"
            f"<input type='hidden' name='id' value='{row['id']}'>"
            "<label>From Node</label>"
            f"<input name='sender_id' value='{esc(sender_id)}'>"
            "<label>To Node</label>"
            f"<input name='recipient_id' value='{esc(recipient_id)}'>"
            "<label>Body</label>"
            f"<textarea name='body'>{esc(body_text)}</textarea>"
            "<button>Save</button> "
            "<a class='button' href='/messages'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit Mail", body)

    def show_board(self):
        selected_category = self.query_value("category")
        valid_categories = {category for category, _ in BOARD_CATEGORIES}
        if selected_category not in valid_categories:
            selected_category = ""
        with db_connect(self.config) as conn:
            category_keys = [category for category, _ in BOARD_CATEGORIES]
            placeholders = ",".join("?" for _ in category_keys)
            count_rows = conn.execute(
                f"""
                SELECT category, COUNT(*) AS count
                FROM board_posts
                WHERE deleted = 0 AND category IN ({placeholders})
                GROUP BY category
                """,
                category_keys,
            ).fetchall()
            counts = {row["category"]: row["count"] for row in count_rows}
            params = list(category_keys)
            where = f"WHERE board_posts.deleted = 0 AND board_posts.category IN ({placeholders})"
            if selected_category:
                where += " AND board_posts.category = ?"
                params.append(selected_category)
            rows = conn.execute(
                f"""
                SELECT board_posts.*, COALESCE(users.display_name, board_posts.author_id) AS author_name
                FROM board_posts
                LEFT JOIN users ON users.node_id = board_posts.author_id
                {where}
                ORDER BY board_posts.created_at DESC, board_posts.id DESC
                LIMIT 300
                """,
                params,
            ).fetchall()
        total = sum(counts.values())
        all_class = "active" if not selected_category else ""
        body = f"<div class='tabs'><a class='{all_class}' href='/board'>All ({total})</a>"
        for category, label in BOARD_CATEGORIES:
            klass = "active" if selected_category == category else ""
            body += f"<a class='{klass}' href='/board?category={esc(category)}'>{esc(label)} ({counts.get(category, 0)})</a>"
        body += "</div>"
        if selected_category:
            label = dict(BOARD_CATEGORIES)[selected_category]
            body += f"<h2>{esc(label)}</h2>"
        body += "<table><tr><th>ID</th><th>Category</th><th>Author</th><th>When</th><th>Body</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-board?" + urlencode({"id": row["id"], "category": selected_category})
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(self.board_category_label(row['category']))}</td><td>{esc(row['author_name'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{esc(clip(row['body']))}</td>"
                f"<td>{link_button(edit_path, 'Edit')} {form_button('/delete-board', {'id': row['id'], 'category': selected_category}, 'Delete')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='6'>No posts in this board.</td></tr>"
        body += "</table>"
        self.send_html("Board", body)

    def show_edit_board(self, error="", values=None):
        values = values or {}
        row_id = values.get("id") or self.query_value("id")
        with db_connect(self.config) as conn:
            row = conn.execute("SELECT * FROM board_posts WHERE id = ? AND deleted = 0", (row_id,)).fetchone()
        if not row:
            self.send_html("Board", "<p>Board post not found.</p><p><a class='button' href='/board'>Back</a></p>", 404)
            return
        category = values.get("category") or row["category"]
        author_id = values.get("author_id", row["author_id"])
        body_text = values.get("body", row["body"])
        options = ""
        for category_key, label in BOARD_CATEGORIES:
            selected = " selected" if category_key == category else ""
            options += f"<option value='{esc(category_key)}'{selected}>{esc(label)}</option>"
        body = "<div class='card'><h2>Edit Board Post</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-board'>"
            f"<input type='hidden' name='id' value='{row['id']}'>"
            "<label>Category</label>"
            f"<select name='category'>{options}</select>"
            "<label>Author Node</label>"
            f"<input name='author_id' value='{esc(author_id)}'>"
            "<label>Body</label>"
            f"<textarea name='body'>{esc(body_text)}</textarea>"
            "<button>Save</button> "
            f"<a class='button' href='/board?category={esc(category)}'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit Board", body)

    def query_value(self, name):
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
        values = parse_qs(query).get(name)
        return values[-1] if values else ""

    def board_category_label(self, category):
        return dict(BOARD_CATEGORIES).get(category, category)

    def show_locations(self):
        with db_connect(self.config) as conn:
            rows = conn.execute(
                "SELECT * FROM locations WHERE deleted = 0 ORDER BY created_at DESC, id DESC LIMIT 300"
            ).fetchall()
        body = "<table><tr><th>ID</th><th>Kind</th><th>Creator</th><th>When</th><th>Lat/Lon</th><th>Body</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-location?" + urlencode({"id": row["id"]})
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['kind'])}</td><td>{esc(row['creator_name'] or row['creator_id'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{row['latitude']:.6f}, {row['longitude']:.6f}</td>"
                f"<td>{esc(clip(row['body']))}</td>"
                f"<td>{link_button(edit_path, 'Edit')} {form_button('/delete-location', {'id': row['id']}, 'Delete')}</td></tr>"
            )
        body += "</table>"
        self.send_html("Locations", body)

    def show_edit_location(self, error="", values=None):
        values = values or {}
        row_id = values.get("id") or self.query_value("id")
        with db_connect(self.config) as conn:
            row = conn.execute("SELECT * FROM locations WHERE id = ? AND deleted = 0", (row_id,)).fetchone()
        if not row:
            self.send_html("Locations", "<p>Location not found.</p><p><a class='button' href='/locations'>Back</a></p>", 404)
            return
        creator_id = values.get("creator_id", row["creator_id"])
        creator_name = values.get("creator_name", row["creator_name"] or "")
        latitude = values.get("latitude", row["latitude"])
        longitude = values.get("longitude", row["longitude"])
        altitude = values.get("altitude", "" if row["altitude"] is None else row["altitude"])
        visibility = values.get("visibility", row["visibility"])
        kind = values.get("kind", row["kind"])
        body_text = values.get("body", row["body"])
        body = "<div class='card'><h2>Edit Location</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        public_selected = " selected" if visibility == "public" else ""
        private_selected = " selected" if visibility == "private" else ""
        note_selected = " selected" if kind == "note" else ""
        checkin_selected = " selected" if kind == "checkin" else ""
        body += (
            "<form method='post' action='/edit-location'>"
            f"<input type='hidden' name='id' value='{row['id']}'>"
            "<label>Creator Node</label>"
            f"<input name='creator_id' value='{esc(creator_id)}'>"
            "<label>Creator Name</label>"
            f"<input name='creator_name' value='{esc(creator_name)}'>"
            "<label>Latitude</label>"
            f"<input name='latitude' value='{esc(latitude)}'>"
            "<label>Longitude</label>"
            f"<input name='longitude' value='{esc(longitude)}'>"
            "<label>Altitude</label>"
            f"<input name='altitude' value='{esc(altitude)}'>"
            "<label>Visibility</label>"
            f"<select name='visibility'><option value='public'{public_selected}>public</option><option value='private'{private_selected}>private</option></select>"
            "<label>Kind</label>"
            f"<select name='kind'><option value='note'{note_selected}>note</option><option value='checkin'{checkin_selected}>checkin</option></select>"
            "<label>Body</label>"
            f"<textarea name='body'>{esc(body_text)}</textarea>"
            "<button>Save</button> "
            "<a class='button' href='/locations'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit Location", body)

    def discover_games(self, conn=None):
        games_dir = resolve_games_dir(self.config)
        settings = {}
        close_conn = False
        if conn is None:
            conn = sqlite3.connect(resolve_db_path(self.config))
            conn.row_factory = sqlite3.Row
            close_conn = True
        try:
            settings = {
                row["module_name"]: row["enabled"]
                for row in conn.execute("SELECT module_name, enabled FROM game_settings").fetchall()
            }
        finally:
            if close_conn:
                conn.close()

        games = []
        if not os.path.isdir(games_dir):
            return games
        for filename in sorted(os.listdir(games_dir)):
            if not filename.endswith(".py") or filename.startswith("__"):
                continue
            path = os.path.join(games_dir, filename)
            module_name = filename[:-3]
            menu_name = module_name
            valid = False
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
                for node in tree.body:
                    if (
                        isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "menu_name" for target in node.targets)
                    ):
                        menu_name = ast.literal_eval(node.value)
                valid = bool(menu_name and "process_command" in functions)
            except Exception:
                valid = False
            games.append(
                {
                    "module_name": module_name,
                    "filename": filename,
                    "menu_name": str(menu_name),
                    "enabled": bool(settings.get(module_name, 1)),
                    "valid": valid,
                }
            )
        return games

    def show_games(self):
        games = self.discover_games()
        body = "<p>{}</p>".format(link_button("/import-game", "Import Game Plugin"))
        body += "<table><tr><th>Game</th><th>File</th><th>Status</th><th>Valid</th><th></th></tr>"
        for game in games:
            enabled = "Enabled" if game["enabled"] else "Disabled"
            valid = "Yes" if game["valid"] else "No"
            action_label = "Disable" if game["enabled"] else "Enable"
            action_value = "0" if game["enabled"] else "1"
            edit_path = "/edit-game?" + urlencode({"module_name": game["module_name"]})
            body += (
                f"<tr><td>{esc(game['menu_name'])}</td><td>{esc(game['filename'])}</td>"
                f"<td>{enabled}</td><td>{valid}</td>"
                f"<td>{link_button(edit_path, 'Edit')} "
                f"{form_button('/set-game-enabled', {'module_name': game['module_name'], 'enabled': action_value}, action_label, False)}</td></tr>"
            )
        if not games:
            body += "<tr><td colspan='5'>No game plugins installed.</td></tr>"
        body += "</table>"
        body += "<p class='muted'>Enable/disable applies to the live Games menu. Imported plugins load after MeshBoard restarts.</p>"
        self.send_html("Games", body)

    def game_path(self, module_name):
        module_name = (module_name or "").strip()
        if not GAME_NAME_PATTERN.match(module_name):
            return None
        games_dir = os.path.abspath(resolve_games_dir(self.config))
        path = os.path.abspath(os.path.join(games_dir, f"{module_name}.py"))
        if os.path.dirname(path) != games_dir:
            return None
        return path

    def show_edit_game(self, error="", values=None):
        values = values or {}
        module_name = values.get("module_name") or self.query_value("module_name")
        path = self.game_path(module_name)
        if not path or not os.path.exists(path):
            self.send_html("Games", "<p>Game plugin not found.</p><p><a class='button' href='/games'>Back</a></p>", 404)
            return
        if "source" in values:
            source = values.get("source", "")
        else:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        body = "<div class='card'><h2>Edit Game Plugin</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-game'>"
            f"<input type='hidden' name='module_name' value='{esc(module_name)}'>"
            f"<p class='muted'>{esc(os.path.basename(path))}</p>"
            "<label>Python Source</label>"
            f"<textarea name='source'>{esc(source)}</textarea>"
            "<button>Save Plugin</button> "
            "<a class='button' href='/games'>Cancel</a>"
            "</form></div>"
            "<p class='muted'>Games receive process_command(user_id, command, bbs_system). Use bbs_system.db, bbs_system.get_recent_location_or_message(user_id), and bbs_system.ask_local_ai(prompt) when those features are enabled.</p>"
        )
        self.send_html("Edit Game", body)

    def show_import_game(self, error="", values=None):
        values = values or {}
        filename = values.get("filename", "")
        source = values.get("source", "")
        body = "<div class='card'><h2>Import Game Plugin</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/import-game'>"
            "<label>Plugin File Name</label>"
            f"<input name='filename' placeholder='my_game.py' value='{esc(filename)}'>"
            "<label>Python Source</label>"
            f"<textarea name='source' placeholder='menu_name = \"My Game\"&#10;&#10;def display_menu(): ...&#10;def process_command(user_id, command, bbs_system): ...'>{esc(source)}</textarea>"
            "<button>Import</button> "
            "<a class='button' href='/games'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Import Game", body)

    def show_checkins(self):
        with db_connect(self.config) as conn:
            events = conn.execute("SELECT * FROM checkin_events ORDER BY starts_at DESC LIMIT 100").fetchall()
            entries = conn.execute("SELECT * FROM checkin_entries ORDER BY checked_in_at DESC").fetchall()
        by_event = {}
        for entry in entries:
            by_event.setdefault(entry["event_id"], []).append(entry)
        body = ""
        for event in events:
            edit_path = "/edit-checkin?" + urlencode({"id": event["id"]})
            body += f"<div class='card'><h2>{esc(event['title'])}</h2>"
            body += f"<p>Starts {fmt_time(event['starts_at'])} | Ends {fmt_time(event['ends_at'])} | Closed: {event['closed']}</p>"
            names = ", ".join(esc(entry["node_id"]) for entry in by_event.get(event["id"], [])) or "None"
            body += f"<p>Checked in: {names}</p>"
            body += link_button(edit_path, "Edit") + " " + form_button("/close-checkin", {"id": event["id"]}, "Close Check-In")
            body += "</div>"
        if not events:
            body = "<p>No check-ins yet.</p>"
        self.send_html("Check-Ins", body)

    def show_edit_checkin(self, error="", values=None):
        values = values or {}
        row_id = values.get("id") or self.query_value("id")
        with db_connect(self.config) as conn:
            row = conn.execute("SELECT * FROM checkin_events WHERE id = ?", (row_id,)).fetchone()
        if not row:
            self.send_html("Check-Ins", "<p>Check-in not found.</p><p><a class='button' href='/checkins'>Back</a></p>", 404)
            return
        title = values.get("title", row["title"])
        created_by = values.get("created_by", row["created_by"])
        starts_at = values.get("starts_at", row["starts_at"])
        ends_at = values.get("ends_at", row["ends_at"])
        closed = values.get("closed") if values else row["closed"]
        body = "<div class='card'><h2>Edit Check-In</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<form method='post' action='/edit-checkin'>"
            f"<input type='hidden' name='id' value='{row['id']}'>"
            "<label>Title</label>"
            f"<input name='title' value='{esc(title)}'>"
            "<label>Created By Node</label>"
            f"<input name='created_by' value='{esc(created_by)}'>"
            "<label>Starts At Unix Time</label>"
            f"<input name='starts_at' type='number' value='{esc(starts_at)}'>"
            "<label>Ends At Unix Time</label>"
            f"<input name='ends_at' type='number' value='{esc(ends_at)}'>"
            "<label><input type='checkbox' name='closed' value='1'"
            f"{checked(closed)}> Closed</label>"
            "<button>Save</button> "
            "<a class='button' href='/checkins'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit Check-In", body)

    def show_backups(self, error=""):
        retention = backup_manager.retention_days(Database(resolve_db_path(self.config)))
        backups = backup_manager.list_backups()
        body = "<div class='card'><h2>Backup / Restore</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += (
            "<p class='muted'>Daily backups are overwritten once per day and retained by this setting. Manual backups are kept until deleted from the backup folder.</p>"
            f"{form_button('/create-backup', {}, 'Backup All Now', False)}"
            "<form method='post' action='/backup-retention'>"
            "<label>Daily Retention Days</label>"
            f"<input name='retention_days' type='number' min='1' max='365' value='{retention}'>"
            "<button>Save Retention</button>"
            "</form>"
            "</div>"
        )
        body += "<table><tr><th>Backup</th><th>Kind</th><th>When</th><th>Size</th><th></th></tr>"
        for backup in backups:
            body += (
                f"<tr><td>{esc(backup['filename'])}</td><td>{esc(backup['kind'])}</td>"
                f"<td>{fmt_time(backup['modified_at'])}</td><td>{backup['size']}</td>"
                f"<td>{form_button('/restore-backup', {'filename': backup['filename']}, 'Restore', False)}</td></tr>"
            )
        if not backups:
            body += "<tr><td colspan='5'>No backups yet.</td></tr>"
        body += "</table>"
        self.send_html("Backups", body)

    def show_config(self, error="", values=None):
        config_path = resolve_mesh_config_path(self.config)
        current = mesh_config.load_config(config_path)
        retention = backup_manager.retention_days(Database(resolve_db_path(self.config)))

        def value(name, fallback):
            if values is not None and name in values:
                return values.get(name, "")
            return fallback

        def is_checked(name, fallback):
            if values is not None:
                return name in values
            return bool(fallback)

        connection_type = value("connection_type", current.get("connection_type", "auto"))
        gps = current.get("gps", {})
        meshtastic = current.get("meshtastic", {})
        time_sync = current.get("time_sync", {})
        wifi = current.get("wifi", {})
        bluetooth = current.get("bluetooth", {})
        local_ai = current.get("local_ai", {})

        body = "<div class='card'><h2>Config</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        body += f"<p class='muted'>Editing {esc(config_path)}. Restart MeshBoard after saving runtime changes.</p>"
        body += "<form method='post' action='/config'>"
        body += (
            "<h2>Backups</h2>"
            "<label>Daily Retention Days</label>"
            f"<input name='backup_retention_days' type='number' min='1' max='365' value='{esc(value('backup_retention_days', retention))}'>"
            "<h2>Connection</h2>"
            "<label>Connection Type</label>"
            "<select name='connection_type'>"
            f"<option value='auto'{selected(connection_type, 'auto')}>auto</option>"
            f"<option value='serial'{selected(connection_type, 'serial')}>serial</option>"
            f"<option value='wifi'{selected(connection_type, 'wifi')}>wifi</option>"
            f"<option value='bluetooth'{selected(connection_type, 'bluetooth')}>bluetooth</option>"
            "</select>"
            "<label>USB Device Path</label>"
            f"<input name='device_path' value='{esc(value('device_path', current.get('device_path', '')))}'>"
            "<label>WiFi Hostname/IP</label>"
            f"<input name='wifi_hostname' value='{esc(value('wifi_hostname', wifi.get('hostname', '')))}'>"
            "<label>WiFi Port</label>"
            f"<input name='wifi_port' type='number' min='1' max='65535' value='{esc(value('wifi_port', wifi.get('port', 4403)))}'>"
            "<label>Bluetooth Address</label>"
            f"<input name='bluetooth_address' value='{esc(value('bluetooth_address', bluetooth.get('address', '')))}'>"
            "<h2>Meshtastic Replies</h2>"
            "<label>Max Text Length</label>"
            f"<input name='max_text_length' type='number' min='20' max='240' value='{esc(value('max_text_length', meshtastic.get('max_text_length', 140)))}'>"
            "<label>Chunk Delay Seconds</label>"
            f"<input name='chunk_delay_seconds' type='number' min='0' max='30' step='0.1' value='{esc(value('chunk_delay_seconds', meshtastic.get('chunk_delay_seconds', 0.5)))}'>"
            "<label>ACK Timeout Seconds</label>"
            f"<input name='ack_timeout_seconds' type='number' min='1' max='120' value='{esc(value('ack_timeout_seconds', meshtastic.get('ack_timeout_seconds', 7)))}'>"
            "<label>ACK Retries</label>"
            f"<input name='ack_retries' type='number' min='0' max='10' value='{esc(value('ack_retries', meshtastic.get('ack_retries', 3)))}'>"
            "<label>Reconnect Delay Seconds</label>"
            f"<input name='reconnect_delay_seconds' type='number' min='1' max='300' value='{esc(value('reconnect_delay_seconds', meshtastic.get('reconnect_delay_seconds', 10)))}'>"
            "<h2>GPS / Location</h2>"
            "<label>GPS Freshness Seconds</label>"
            f"<input name='gps_freshness_seconds' type='number' min='30' max='86400' value='{esc(value('gps_freshness_seconds', gps.get('freshness_seconds', 300)))}'>"
            "<label>What's Here Radius Meters</label>"
            f"<input name='whats_here_radius_meters' type='number' min='1' max='100000' value='{esc(value('whats_here_radius_meters', gps.get('whats_here_radius_meters', 100)))}'>"
            "<label>Nearby Radius Meters</label>"
            f"<input name='nearby_radius_meters' type='number' min='1' max='1000000' value='{esc(value('nearby_radius_meters', gps.get('nearby_radius_meters', 1000)))}'>"
            f"<label><input type='checkbox' name='log_raw_history' value='1'{checked(is_checked('log_raw_history', gps.get('log_raw_history', False)))}> Log Raw GPS History</label>"
            "<h2>Time Sync</h2>"
            f"<label><input type='checkbox' name='sync_on_startup' value='1'{checked(is_checked('sync_on_startup', time_sync.get('sync_on_startup', True)))}> Sync On Startup</label>"
            f"<label><input type='checkbox' name='sync_from_host' value='1'{checked(is_checked('sync_from_host', time_sync.get('sync_from_host', False)))}> Sync From Host Clock</label>"
            f"<label><input type='checkbox' name='sync_from_mesh' value='1'{checked(is_checked('sync_from_mesh', time_sync.get('sync_from_mesh', True)))}> Sync From Mesh Packets</label>"
            "<label>Sync Interval Seconds</label>"
            f"<input name='sync_interval_seconds' type='number' min='60' max='86400' value='{esc(value('sync_interval_seconds', time_sync.get('sync_interval_seconds', 3600)))}'>"
            "<label>Minimum Valid Epoch</label>"
            f"<input name='minimum_valid_epoch' type='number' min='0' value='{esc(value('minimum_valid_epoch', time_sync.get('minimum_valid_epoch', 1704067200)))}'>"
            "<label>Maximum Future Seconds</label>"
            f"<input name='maximum_future_seconds' type='number' min='0' max='31536000' value='{esc(value('maximum_future_seconds', time_sync.get('maximum_future_seconds', 172800)))}'>"
            f"<label><input type='checkbox' name='allow_receive_time' value='1'{checked(is_checked('allow_receive_time', time_sync.get('allow_receive_time', False)))}> Allow Local Receive Time</label>"
            "<h2>Local AI</h2>"
            f"<label><input type='checkbox' name='local_ai_enabled' value='1'{checked(is_checked('local_ai_enabled', local_ai.get('enabled', False)))}> Enable Local AI</label>"
            "<label>Local AI URL</label>"
            f"<input name='local_ai_url' value='{esc(value('local_ai_url', local_ai.get('url', 'http://127.0.0.1:11434/api/generate')))}'>"
            "<label>Local AI Model</label>"
            f"<input name='local_ai_model' value='{esc(value('local_ai_model', local_ai.get('model', 'tinyllama')))}'>"
            "<label>Local AI Timeout Seconds</label>"
            f"<input name='local_ai_timeout_seconds' type='number' min='1' max='300' value='{esc(value('local_ai_timeout_seconds', local_ai.get('timeout_seconds', 120)))}'>"
            "<label>Local AI Idle Shutdown Seconds</label>"
            f"<input name='local_ai_idle_shutdown_seconds' type='number' min='60' max='86400' value='{esc(value('local_ai_idle_shutdown_seconds', local_ai.get('idle_shutdown_seconds', 1200)))}'>"
            "<label>Local AI Startup Timeout Seconds</label>"
            f"<input name='local_ai_startup_timeout_seconds' type='number' min='10' max='600' value='{esc(value('local_ai_startup_timeout_seconds', local_ai.get('startup_timeout_seconds', 120)))}'>"
            "<button>Save Config</button> "
            "<a class='button' href='/'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Config", body)

    def show_logs(self):
        log_path = os.path.join(APP_DIR, "listener.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as file:
                lines = file.readlines()[-200:]
        except FileNotFoundError:
            lines = ["No listener.log found."]
        self.send_html("Logs", f"<pre>{esc(''.join(lines))}</pre>")

    def delete_row(self, table, row_id):
        if not row_id:
            return
        with db_connect(self.config) as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def archive_message(self, row_id):
        if not row_id:
            return
        with db_connect(self.config) as conn:
            conn.execute("UPDATE messages SET deleted_by_recipient = 1 WHERE id = ?", (row_id,))

    def mark_deleted(self, table, row_id):
        if not row_id:
            return
        with db_connect(self.config) as conn:
            conn.execute(f"UPDATE {table} SET deleted = 1 WHERE id = ?", (row_id,))

    def delete_user(self, node_id):
        if not node_id:
            return
        with db_connect(self.config) as conn:
            conn.execute("DELETE FROM checkin_entries WHERE node_id = ?", (node_id,))
            conn.execute("DELETE FROM users WHERE node_id = ?", (node_id,))

    def update_user(self, data):
        node_id = (data.get("node_id") or "").strip()
        display_name = (data.get("display_name") or "").strip() or None
        if not node_id:
            return "Missing node ID."
        try:
            command_count = max(0, int(data.get("command_count") or 0))
        except ValueError:
            return "Command count must be a number."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET display_name = ?, mail_listed = ?, command_count = ?
                WHERE node_id = ?
                """,
                (display_name, 1 if data.get("mail_listed") else 0, command_count, node_id),
            )
        if cursor.rowcount == 0:
            return "User not found."
        return ""

    def update_message(self, data):
        row_id = data.get("id")
        sender_id = (data.get("sender_id") or "").strip()
        recipient_id = (data.get("recipient_id") or "").strip()
        body = (data.get("body") or "").strip()
        if not row_id:
            return "Missing message ID."
        if not sender_id or not recipient_id:
            return "Sender and recipient are required."
        if not body:
            return "Message body is required."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE messages
                SET sender_id = ?, recipient_id = ?, body = ?
                WHERE id = ?
                """,
                (sender_id, recipient_id, body, row_id),
            )
        if cursor.rowcount == 0:
            return "Message not found."
        return ""

    def update_board_post(self, data):
        row_id = data.get("id")
        category = (data.get("category") or "").strip()
        author_id = (data.get("author_id") or "").strip()
        body = (data.get("body") or "").strip()
        valid_categories = {category_key for category_key, _ in BOARD_CATEGORIES}
        if not row_id:
            return "Missing board post ID."
        if category not in valid_categories:
            return "Choose a valid board category."
        if not author_id:
            return "Author node is required."
        if not body:
            return "Board post body is required."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE board_posts
                SET category = ?, author_id = ?, body = ?
                WHERE id = ? AND deleted = 0
                """,
                (category, author_id, body, row_id),
            )
        if cursor.rowcount == 0:
            return "Board post not found."
        return ""

    def update_location(self, data):
        row_id = data.get("id")
        creator_id = (data.get("creator_id") or "").strip()
        creator_name = (data.get("creator_name") or "").strip() or None
        body = (data.get("body") or "").strip()
        visibility = (data.get("visibility") or "public").strip()
        kind = (data.get("kind") or "note").strip()
        if not row_id:
            return "Missing location ID."
        if not creator_id:
            return "Creator node is required."
        if visibility not in ("public", "private"):
            return "Visibility must be public or private."
        if kind not in ("note", "checkin"):
            return "Kind must be note or checkin."
        try:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
            altitude = data.get("altitude")
            altitude = None if altitude in (None, "") else float(altitude)
        except (TypeError, ValueError):
            return "Latitude, longitude, and altitude must be numbers."
        if not body:
            return "Location body is required."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE locations
                SET creator_id = ?, creator_name = ?, latitude = ?, longitude = ?,
                    altitude = ?, body = ?, updated_at = ?, visibility = ?, kind = ?
                WHERE id = ? AND deleted = 0
                """,
                (creator_id, creator_name, latitude, longitude, altitude, body, int(time.time()), visibility, kind, row_id),
            )
        if cursor.rowcount == 0:
            return "Location not found."
        return ""

    def update_checkin(self, data):
        row_id = data.get("id")
        title = (data.get("title") or "").strip()
        created_by = (data.get("created_by") or "").strip()
        if not row_id:
            return "Missing check-in ID."
        if not title:
            return "Title is required."
        if not created_by:
            return "Created-by node is required."
        try:
            starts_at = int(data.get("starts_at"))
            ends_at = int(data.get("ends_at"))
        except (TypeError, ValueError):
            return "Start and end times must be Unix timestamps."
        if ends_at <= starts_at:
            return "End time must be after start time."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE checkin_events
                SET title = ?, created_by = ?, starts_at = ?, ends_at = ?, closed = ?
                WHERE id = ?
                """,
                (title, created_by, starts_at, ends_at, 1 if data.get("closed") else 0, row_id),
            )
        if cursor.rowcount == 0:
            return "Check-in not found."
        return ""

    def config_int(self, data, key, label, minimum=None, maximum=None):
        try:
            value = int(data.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a number.")
        if minimum is not None and value < minimum:
            raise ValueError(f"{label} must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{label} must be no more than {maximum}.")
        return value

    def config_float(self, data, key, label, minimum=None, maximum=None):
        try:
            value = float(data.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a number.")
        if minimum is not None and value < minimum:
            raise ValueError(f"{label} must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{label} must be no more than {maximum}.")
        return value

    def update_config(self, data):
        try:
            retention_error = self.update_backup_retention(data.get("backup_retention_days"))
            if retention_error:
                return retention_error
            connection_type = (data.get("connection_type") or "").strip()
            if connection_type not in ("auto", "serial", "wifi", "bluetooth"):
                return "Choose a valid connection type."
            config_path = resolve_mesh_config_path(self.config)
            current = mesh_config.load_config(config_path)
            current["connection_type"] = connection_type
            current["device_path"] = (data.get("device_path") or "").strip()
            current["wifi"] = {
                "hostname": (data.get("wifi_hostname") or "").strip(),
                "port": self.config_int(data, "wifi_port", "WiFi port", 1, 65535),
            }
            current["bluetooth"] = {"address": (data.get("bluetooth_address") or "").strip()}
            current["gps"] = {
                "freshness_seconds": self.config_int(data, "gps_freshness_seconds", "GPS freshness", 30, 86400),
                "whats_here_radius_meters": self.config_int(data, "whats_here_radius_meters", "What's Here radius", 1, 100000),
                "nearby_radius_meters": self.config_int(data, "nearby_radius_meters", "Nearby radius", 1, 1000000),
                "log_raw_history": "log_raw_history" in data,
            }
            current["meshtastic"] = {
                "max_text_length": self.config_int(data, "max_text_length", "Max text length", 20, 240),
                "chunk_delay_seconds": self.config_float(data, "chunk_delay_seconds", "Chunk delay", 0, 30),
                "ack_timeout_seconds": self.config_int(data, "ack_timeout_seconds", "ACK timeout", 1, 120),
                "ack_retries": self.config_int(data, "ack_retries", "ACK retries", 0, 10),
                "reconnect_delay_seconds": self.config_int(data, "reconnect_delay_seconds", "Reconnect delay", 1, 300),
            }
            current["time_sync"] = {
                "sync_on_startup": "sync_on_startup" in data,
                "sync_from_host": "sync_from_host" in data,
                "sync_from_mesh": "sync_from_mesh" in data,
                "sync_interval_seconds": self.config_int(data, "sync_interval_seconds", "Sync interval", 60, 86400),
                "minimum_valid_epoch": self.config_int(data, "minimum_valid_epoch", "Minimum valid epoch", 0, None),
                "maximum_future_seconds": self.config_int(data, "maximum_future_seconds", "Maximum future seconds", 0, 31536000),
                "allow_receive_time": "allow_receive_time" in data,
            }
            current["local_ai"] = {
                "enabled": "local_ai_enabled" in data,
                "url": (data.get("local_ai_url") or "").strip() or "http://127.0.0.1:11434/api/generate",
                "model": (data.get("local_ai_model") or "").strip() or "tinyllama",
                "timeout_seconds": self.config_int(data, "local_ai_timeout_seconds", "Local AI timeout", 1, 300),
                "idle_shutdown_seconds": self.config_int(data, "local_ai_idle_shutdown_seconds", "Local AI idle shutdown", 60, 86400),
                "startup_timeout_seconds": self.config_int(data, "local_ai_startup_timeout_seconds", "Local AI startup timeout", 10, 600),
            }
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            mesh_config.save_config(current, config_path)
        except ValueError as exc:
            return str(exc)
        return ""

    def update_backup_retention(self, retention_days):
        try:
            backup_manager.set_retention_days(retention_days, Database(resolve_db_path(self.config)))
        except ValueError as exc:
            return str(exc)
        backup_manager.prune_daily_backups(backup_manager.retention_days(Database(resolve_db_path(self.config))))
        return ""

    def restore_backup(self, filename):
        try:
            backup_manager.restore_backup(filename, app_dir=resolve_backup_app_dir(self.config))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return str(exc)
        return ""

    def set_game_enabled(self, module_name, enabled):
        module_name = (module_name or "").strip()
        if not GAME_NAME_PATTERN.match(module_name):
            return
        with db_connect(self.config) as conn:
            conn.execute(
                """
                INSERT INTO game_settings (module_name, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(module_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (module_name, 1 if enabled else 0, int(time.time())),
            )

    def validate_game_source(self, filename, source):
        if not source.strip():
            return "Paste the plugin Python source."
        try:
            tree = ast.parse(source, filename=filename)
            compile(source, filename, "exec")
        except SyntaxError as exc:
            return f"Python syntax error on line {exc.lineno}: {exc.msg}"

        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        menu_name = ""
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "menu_name" for target in node.targets)
            ):
                try:
                    menu_name = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    menu_name = ""
        if not menu_name:
            return "Plugin must set menu_name to a text value."
        if "process_command" not in functions:
            return "Plugin must define process_command(user_id, command, bbs_system)."
        return ""

    def update_game(self, data):
        module_name = data.get("module_name")
        source = data.get("source") or ""
        path = self.game_path(module_name)
        if not path or not os.path.exists(path):
            return "Game plugin not found."
        error = self.validate_game_source(os.path.basename(path), source)
        if error:
            return error
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source.rstrip() + "\n")
        return ""

    def import_game(self, data):
        filename = (data.get("filename") or "").strip()
        source = data.get("source") or ""
        if not filename.endswith(".py"):
            filename += ".py"
        module_name = filename[:-3]
        if not GAME_NAME_PATTERN.match(module_name) or filename.startswith("__"):
            return "Use a simple Python file name like my_game.py."
        error = self.validate_game_source(filename, source)
        if error:
            return error

        games_dir = resolve_games_dir(self.config)
        os.makedirs(games_dir, exist_ok=True)
        destination = os.path.abspath(os.path.join(games_dir, filename))
        if os.path.dirname(destination) != os.path.abspath(games_dir):
            return "Invalid plugin path."
        if os.path.exists(destination):
            return "A game plugin with that file name already exists."
        with open(destination, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source.rstrip() + "\n")
        self.set_game_enabled(module_name, True)
        return ""

    def set_addressbook_listed(self, node_id, listed):
        if not node_id:
            return
        with db_connect(self.config) as conn:
            conn.execute("UPDATE users SET mail_listed = ? WHERE node_id = ?", (1 if listed else 0, node_id))

    def update_addressbook_id(self, node_id, display_name):
        display_name = (display_name or "").strip()
        if not node_id:
            return "Missing node ID."
        if len(display_name) != 4:
            return "AddressBook ID must be exactly 4 characters."
        if any(char.isspace() for char in display_name):
            return "AddressBook ID cannot include spaces."
        with db_connect(self.config) as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET display_name = ?, mail_listed = 1
                WHERE node_id = ?
                """,
                (display_name, node_id),
            )
        if cursor.rowcount == 0:
            return "AddressBook contact not found."
        return ""

    def close_checkin(self, event_id):
        if not event_id:
            return
        with db_connect(self.config) as conn:
            conn.execute("UPDATE checkin_events SET closed = 1 WHERE id = ?", (event_id,))


def run(config):
    if not config.get("enabled", False):
        print(f"Admin server disabled in {CONFIG_PATH}. Set enabled=true to run.")
        return
    if not config.get("password_hash"):
        print("Admin password_hash is empty. Generate one with: python admin_server.py --hash-password")
        return
    from database import Database

    Database(resolve_db_path(config))
    server = ThreadingHTTPServer((config["host"], int(config["port"])), AdminHandler)
    server.config = config
    print(f"MeshBoard Admin listening on http://{config['host']}:{config['port']}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MeshBoard local SysOp admin server")
    parser.add_argument("--hash-password", action="store_true", help="prompt for a password and print a config hash")
    args = parser.parse_args()
    if args.hash_password:
        import getpass

        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match.")
        print(make_password_hash(password))
    else:
        run(load_config())
