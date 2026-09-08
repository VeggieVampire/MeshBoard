import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode


APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("MESHBOARD_ADMIN_CONFIG", os.path.join(APP_DIR, "admin_config.json"))
SESSION_COOKIE = "meshboard_admin"
SESSION_MAX_AGE = 12 * 60 * 60
BOARD_CATEGORIES = [
    ("general", "General Discussion"),
    ("news", "Local News"),
    ("trade", "Buy / Sell / Trade"),
    ("events", "Events"),
    ("rumors", "Rumors & Gossip"),
]


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
                ("/checkins", "Check-Ins"),
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
            "/checkins": self.show_checkins,
            "/edit-checkin": self.show_edit_checkin,
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
                (
                    "/checkins",
                    "Check-Ins",
                    conn.execute("SELECT COUNT(*) AS count FROM checkin_events").fetchone()["count"],
                    "events",
                ),
                ("/logs", "Logs", "", "recent service output"),
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
        body = "<table><tr><th>ID</th><th>Creator</th><th>When</th><th>Lat/Lon</th><th>Body</th><th></th></tr>"
        for row in rows:
            edit_path = "/edit-location?" + urlencode({"id": row["id"]})
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['creator_name'] or row['creator_id'])}</td>"
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
        body_text = values.get("body", row["body"])
        body = "<div class='card'><h2>Edit Location</h2>"
        if error:
            body += f"<p class='flash'>{esc(error)}</p>"
        public_selected = " selected" if visibility == "public" else ""
        private_selected = " selected" if visibility == "private" else ""
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
            "<label>Body</label>"
            f"<textarea name='body'>{esc(body_text)}</textarea>"
            "<button>Save</button> "
            "<a class='button' href='/locations'>Cancel</a>"
            "</form></div>"
        )
        self.send_html("Edit Location", body)

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
        if not row_id:
            return "Missing location ID."
        if not creator_id:
            return "Creator node is required."
        if visibility not in ("public", "private"):
            return "Visibility must be public or private."
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
                    altitude = ?, body = ?, updated_at = ?, visibility = ?
                WHERE id = ? AND deleted = 0
                """,
                (creator_id, creator_name, latitude, longitude, altitude, body, int(time.time()), visibility, row_id),
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
