import logging
import sqlite3
import time
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path="meshboard.db"):
        self.path = path
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    node_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    mail_listed INTEGER NOT NULL DEFAULT 0,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS address_book (
                    owner_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    display_name TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (owner_id, node_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    read_at INTEGER,
                    deleted_by_sender INTEGER NOT NULL DEFAULT 0,
                    deleted_by_recipient INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id TEXT NOT NULL,
                    creator_name TEXT,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    altitude REAL,
                    body TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    visibility TEXT NOT NULL DEFAULT 'public'
                );

                CREATE TABLE IF NOT EXISTS board_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS checkin_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    starts_at INTEGER NOT NULL,
                    ends_at INTEGER NOT NULL,
                    closed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS checkin_entries (
                    event_id INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    checked_in_at INTEGER NOT NULL,
                    PRIMARY KEY (event_id, node_id),
                    FOREIGN KEY (event_id) REFERENCES checkin_events(id)
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "mail_listed" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN mail_listed INTEGER NOT NULL DEFAULT 0")

    def upsert_user(self, node_id, display_name=None, seen_at=None):
        seen_at = int(seen_at or time.time())
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users (node_id, display_name, first_seen, last_seen)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        display_name = COALESCE(excluded.display_name, users.display_name),
                        last_seen = excluded.last_seen
                    """,
                    (node_id, display_name, seen_at, seen_at),
                )
        except sqlite3.Error as exc:
            logger.error("Could not update user %s: %s", node_id, exc)

    def get_user(self, node_id):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE node_id = ?", (node_id,)).fetchone()

    def list_users(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM users ORDER BY COALESCE(display_name, node_id) COLLATE NOCASE"
            ).fetchall()

    def recently_seen_users(self, limit=8, offset=0):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM users
                ORDER BY last_seen DESC, COALESCE(display_name, node_id) COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

    def set_display_name(self, node_id, display_name):
        self.upsert_user(node_id, display_name=display_name)

    def set_mail_listed(self, node_id, display_name, listed=True):
        self.upsert_user(node_id, display_name=display_name)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET mail_listed = ? WHERE node_id = ?",
                (1 if listed else 0, node_id),
            )

    def list_mail_contacts(self):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM users
                WHERE mail_listed = 1 AND display_name IS NOT NULL AND display_name != ''
                ORDER BY display_name COLLATE NOCASE, node_id
                """
            ).fetchall()

    def display_name_for(self, node_id):
        row = self.get_user(node_id)
        if row and row["display_name"]:
            return row["display_name"]
        return node_id

    def send_message(self, sender_id, recipient_id, body, created_at=None):
        created_at = int(created_at or time.time())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (sender_id, recipient_id, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (sender_id, recipient_id, body, created_at),
            )
            return cursor.lastrowid

    def inbox(self, recipient_id, include_deleted=False):
        sql = "SELECT * FROM messages WHERE recipient_id = ?"
        params = [recipient_id]
        if not include_deleted:
            sql += " AND deleted_by_recipient = 0"
        sql += " ORDER BY created_at DESC, id DESC"
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def archived_inbox(self, recipient_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM messages
                WHERE recipient_id = ? AND deleted_by_recipient = 1
                ORDER BY created_at DESC, id DESC
                """,
                (recipient_id,),
            ).fetchall()

    def sent(self, sender_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM messages
                WHERE sender_id = ? AND deleted_by_sender = 0
                ORDER BY created_at DESC, id DESC
                """,
                (sender_id,),
            ).fetchall()

    def get_message_for_user(self, message_id, user_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM messages
                WHERE id = ? AND (sender_id = ? OR recipient_id = ?)
                """,
                (message_id, user_id, user_id),
            ).fetchone()

    def mark_read(self, message_id, recipient_id, read_at=None):
        read_at = int(read_at or time.time())
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE messages SET read_at = COALESCE(read_at, ?)
                WHERE id = ? AND recipient_id = ?
                """,
                (read_at, message_id, recipient_id),
            )

    def unread_count(self, recipient_id):
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM messages
                WHERE recipient_id = ? AND read_at IS NULL AND deleted_by_recipient = 0
                """,
                (recipient_id,),
            ).fetchone()
            return row["count"]

    def soft_delete_message(self, message_id, user_id):
        message = self.get_message_for_user(message_id, user_id)
        if not message:
            return False
        column = "deleted_by_recipient" if message["recipient_id"] == user_id else "deleted_by_sender"
        with self.connect() as conn:
            conn.execute(f"UPDATE messages SET {column} = 1 WHERE id = ?", (message_id,))
        return True

    def delete_archived_message(self, message_id, user_id):
        with self.connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM messages
                WHERE id = ? AND recipient_id = ? AND deleted_by_recipient = 1
                """,
                (message_id, user_id),
            )
            return cursor.rowcount > 0

    def create_board_post(self, category, author_id, body, created_at=None):
        created_at = int(created_at or time.time())
        self.upsert_user(author_id, seen_at=created_at)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO board_posts (category, author_id, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (category, author_id, body, created_at),
            )
            return cursor.lastrowid

    def board_posts(self, category, limit=8, offset=0):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM board_posts
                WHERE category = ? AND deleted = 0
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (category, limit, offset),
            ).fetchall()

    def get_board_post(self, post_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM board_posts WHERE id = ? AND deleted = 0",
                (post_id,),
            ).fetchone()

    def active_checkin_event(self, now=None):
        now = int(now or time.time())
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM checkin_events
                WHERE closed = 0 AND starts_at <= ? AND ends_at > ?
                ORDER BY starts_at DESC, id DESC
                LIMIT 1
                """,
                (now, now),
            ).fetchone()

    def create_checkin_event(self, created_by, title=None, starts_at=None, duration_seconds=86400):
        starts_at = int(starts_at or time.time())
        title = title or time.strftime("Check-In %b %d", time.localtime(starts_at))
        self.upsert_user(created_by, seen_at=starts_at)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO checkin_events (title, created_by, starts_at, ends_at)
                VALUES (?, ?, ?, ?)
                """,
                (title, created_by, starts_at, starts_at + int(duration_seconds)),
            )
            return cursor.lastrowid

    def check_in(self, event_id, node_id, checked_in_at=None):
        checked_in_at = int(checked_in_at or time.time())
        self.upsert_user(node_id, seen_at=checked_in_at)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO checkin_entries (event_id, node_id, checked_in_at)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id, node_id) DO UPDATE SET
                    checked_in_at = excluded.checked_in_at
                """,
                (event_id, node_id, checked_in_at),
            )

    def checkin_entries(self, event_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM checkin_entries
                WHERE event_id = ?
                ORDER BY checked_in_at DESC, node_id
                """,
                (event_id,),
            ).fetchall()

    def save_location(self, creator_id, creator_name, latitude, longitude, altitude, body, visibility="public"):
        now = int(time.time())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO locations
                    (creator_id, creator_name, latitude, longitude, altitude, body, created_at, updated_at, visibility)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (creator_id, creator_name, latitude, longitude, altitude, body, now, now, visibility),
            )
            return cursor.lastrowid

    def active_locations(self):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM locations
                WHERE deleted = 0 AND visibility = 'public'
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()

    def locations_by_creator(self, creator_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM locations
                WHERE creator_id = ? AND deleted = 0
                ORDER BY created_at DESC, id DESC
                """,
                (creator_id,),
            ).fetchall()

    def get_location_for_creator(self, location_id, creator_id):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM locations
                WHERE id = ? AND creator_id = ? AND deleted = 0
                """,
                (location_id, creator_id),
            ).fetchone()

    def soft_delete_location(self, location_id, creator_id):
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE locations SET deleted = 1, updated_at = ?
                WHERE id = ? AND creator_id = ? AND deleted = 0
                """,
                (int(time.time()), location_id, creator_id),
            )
            return cursor.rowcount > 0
