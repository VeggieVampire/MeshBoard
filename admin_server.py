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
    ("header", "Main Menu Header"),
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
.tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }}
.tabs a {{ background: #151f2d; color: #e6edf3; border: 1px solid #38475b; border-radius: 6px; padding: 8px 10px; text-decoration: none; }}
.tabs a.active {{ background: #2d415d; border-color: #5b779b; }}
.muted {{ color: #9fb0c3; }}
table {{ width: 100%; border-collapse: collapse; background: #151f2d; }}
th, td {{ padding: 8px; border-bottom: 1px solid #2d3a4d; text-align: left; vertical-align: top; }}
th {{ color: #a9bdd3; }}
input {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 6px 0 12px; background: #101722; color: #e6edf3; border: 1px solid #38475b; border-radius: 6px; }}
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
            "/addressbook": self.show_addressbook,
            "/messages": self.show_messages,
            "/board": self.show_board,
            "/locations": self.show_locations,
            "/checkins": self.show_checkins,
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
            elif action == "/delete-board":
                self.mark_deleted("board_posts", data.get("id"))
                query = {"deleted": "1"}
                if data.get("category"):
                    query["category"] = data["category"]
                self.redirect("/board?" + urlencode(query))
            elif action == "/delete-location":
                self.mark_deleted("locations", data.get("id"))
                self.redirect("/locations?deleted=1")
            elif action == "/delete-user":
                self.delete_user(data.get("node_id"))
                self.redirect("/users?deleted=1")
            elif action == "/remove-addressbook":
                self.set_addressbook_listed(data.get("node_id"), False)
                self.redirect("/addressbook?removed=1")
            elif action == "/close-checkin":
                self.close_checkin(data.get("id"))
                self.redirect("/checkins?closed=1")
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
            counts = {}
            for table in ("users", "messages", "board_posts", "locations", "checkin_events"):
                counts[table] = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            counts["addressbook"] = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                WHERE mail_listed = 1 AND display_name IS NOT NULL AND display_name != ''
                """
            ).fetchone()["count"]
        body = "<div class='grid'>" + "".join(
            f"<div class='card'><h2>{esc(name.replace('_', ' ').title())}</h2><p>{count}</p></div>"
            for name, count in counts.items()
        ) + "</div>"
        body += "<p class='muted'>Local-only SysOp tools. Delete actions change meshboard.db immediately.</p>"
        self.send_html("Dashboard", body)

    def show_users(self):
        with db_connect(self.config) as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 200").fetchall()
        body = "<table><tr><th>Name</th><th>Node</th><th>Mail</th><th>Last Seen</th><th></th></tr>"
        for row in rows:
            body += (
                f"<tr><td>{esc(row['display_name'])}</td><td>{esc(row['node_id'])}</td>"
                f"<td>{'Yes' if row['mail_listed'] else 'No'}</td><td>{fmt_time(row['last_seen'])}</td>"
                f"<td>{form_button('/delete-user', {'node_id': row['node_id']}, 'Delete')}</td></tr>"
            )
        body += "</table>"
        self.send_html("Users", body)

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
            body += (
                f"<tr><td>{esc(row['display_name'])}</td><td>{esc(row['node_id'])}</td>"
                f"<td>{fmt_time(row['first_seen'])}</td><td>{fmt_time(row['last_seen'])}</td>"
                f"<td>{form_button('/remove-addressbook', {'node_id': row['node_id']}, 'Remove')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='5'>AddressBook is empty.</td></tr>"
        body += "</table>"
        self.send_html("AddressBook", body)

    def show_messages(self):
        with db_connect(self.config) as conn:
            rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC, id DESC LIMIT 300").fetchall()
        body = "<table><tr><th>ID</th><th>From</th><th>To</th><th>When</th><th>Body</th><th></th></tr>"
        for row in rows:
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['sender_id'])}</td><td>{esc(row['recipient_id'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{esc(clip(row['body']))}</td>"
                f"<td>{form_button('/delete-message', {'id': row['id']}, 'Delete')}</td></tr>"
            )
        body += "</table>"
        self.send_html("Mail", body)

    def show_board(self):
        selected_category = self.query_value("category")
        valid_categories = {category for category, _ in BOARD_CATEGORIES}
        if selected_category not in valid_categories:
            selected_category = ""
        with db_connect(self.config) as conn:
            count_rows = conn.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM board_posts
                WHERE deleted = 0
                GROUP BY category
                """
            ).fetchall()
            counts = {row["category"]: row["count"] for row in count_rows}
            params = []
            where = "WHERE board_posts.deleted = 0"
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
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(self.board_category_label(row['category']))}</td><td>{esc(row['author_name'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{esc(clip(row['body']))}</td>"
                f"<td>{form_button('/delete-board', {'id': row['id'], 'category': selected_category}, 'Delete')}</td></tr>"
            )
        if not rows:
            body += "<tr><td colspan='6'>No posts in this board.</td></tr>"
        body += "</table>"
        self.send_html("Board", body)

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
            body += (
                f"<tr><td>{row['id']}</td><td>{esc(row['creator_name'] or row['creator_id'])}</td>"
                f"<td>{fmt_time(row['created_at'])}</td><td>{row['latitude']:.6f}, {row['longitude']:.6f}</td>"
                f"<td>{esc(clip(row['body']))}</td>"
                f"<td>{form_button('/delete-location', {'id': row['id']}, 'Delete')}</td></tr>"
            )
        body += "</table>"
        self.send_html("Locations", body)

    def show_checkins(self):
        with db_connect(self.config) as conn:
            events = conn.execute("SELECT * FROM checkin_events ORDER BY starts_at DESC LIMIT 100").fetchall()
            entries = conn.execute("SELECT * FROM checkin_entries ORDER BY checked_in_at DESC").fetchall()
        by_event = {}
        for entry in entries:
            by_event.setdefault(entry["event_id"], []).append(entry)
        body = ""
        for event in events:
            body += f"<div class='card'><h2>{esc(event['title'])}</h2>"
            body += f"<p>Starts {fmt_time(event['starts_at'])} | Ends {fmt_time(event['ends_at'])} | Closed: {event['closed']}</p>"
            names = ", ".join(esc(entry["node_id"]) for entry in by_event.get(event["id"], [])) or "None"
            body += f"<p>Checked in: {names}</p>"
            body += form_button("/close-checkin", {"id": event["id"]}, "Close Check-In")
            body += "</div>"
        if not events:
            body = "<p>No check-ins yet.</p>"
        self.send_html("Check-Ins", body)

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

    def set_addressbook_listed(self, node_id, listed):
        if not node_id:
            return
        with db_connect(self.config) as conn:
            conn.execute("UPDATE users SET mail_listed = ? WHERE node_id = ?", (1 if listed else 0, node_id))

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
