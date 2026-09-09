import argparse
import json
import os
import shutil
import time
import zipfile

from config import load_config
from database import Database


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BACKUP_DIR = os.path.join(APP_DIR, "backups")
RETENTION_SETTING = "backup_retention_days"
DEFAULT_RETENTION_DAYS = 7
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", "backups"}
EXCLUDED_FILES = {"listener.log", "admin.log", "wifi-connect.log", ".admin_install_info"}
INCLUDED_DIRS = {"modules", "scripts", "systemd", "tests"}
INCLUDED_ROOT_FILES = {".gitignore"}
INCLUDED_ROOT_EXTENSIONS = {".conf", ".db", ".example", ".json", ".md", ".py", ".service", ".txt"}


def backup_dir():
    return os.environ.get("MESHBOARD_BACKUP_DIR", DEFAULT_BACKUP_DIR)


def retention_days(database=None):
    database = database or Database(load_config()["database"]["path"])
    raw = database.get_app_setting(RETENTION_SETTING, DEFAULT_RETENTION_DAYS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_RETENTION_DAYS
    return max(1, value)


def set_retention_days(days, database=None):
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("Retention days must be a number.")
    if days < 1 or days > 365:
        raise ValueError("Retention days must be between 1 and 365.")
    database = database or Database(load_config()["database"]["path"])
    database.set_app_setting(RETENTION_SETTING, days)
    return days


def _backup_name(kind, now=None):
    now = int(now or time.time())
    if kind == "daily":
        suffix = time.strftime("%Y-%m-%d", time.localtime(now))
    else:
        suffix = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(now))
    return f"meshboard-{kind}-{suffix}.zip"


def _should_skip(rel_path):
    parts = rel_path.split(os.sep)
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    return os.path.basename(rel_path) in EXCLUDED_FILES


def _iter_backup_files(app_dir):
    backup_root = os.path.abspath(backup_dir())
    for root, dirs, files in os.walk(app_dir):
        rel_root = os.path.relpath(root, app_dir)
        if rel_root == ".":
            dirs[:] = [dirname for dirname in dirs if dirname in INCLUDED_DIRS and dirname not in EXCLUDED_DIRS]
        else:
            dirs[:] = [dirname for dirname in dirs if dirname not in EXCLUDED_DIRS]
        for filename in files:
            full_path = os.path.join(root, filename)
            if os.path.commonpath([backup_root, os.path.abspath(full_path)]) == backup_root:
                continue
            rel_path = os.path.relpath(full_path, app_dir)
            if rel_root == ".":
                _, extension = os.path.splitext(filename)
                if filename not in INCLUDED_ROOT_FILES and extension not in INCLUDED_ROOT_EXTENSIONS:
                    continue
            if not _should_skip(rel_path):
                yield full_path, rel_path


def create_backup(kind="manual", now=None, app_dir=APP_DIR):
    if kind not in ("manual", "daily"):
        raise ValueError("Backup kind must be manual or daily.")
    os.makedirs(backup_dir(), exist_ok=True)
    path = os.path.join(backup_dir(), _backup_name(kind, now))
    temp_path = f"{path}.tmp"
    manifest = {
        "created_at": int(now or time.time()),
        "kind": kind,
        "app_dir": app_dir,
        "format": 1,
    }
    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2) + "\n")
        for full_path, rel_path in _iter_backup_files(app_dir):
            archive.write(full_path, rel_path)
    os.replace(temp_path, path)
    if kind == "daily":
        prune_daily_backups(retention_days())
    return path


def list_backups():
    path = backup_dir()
    if not os.path.isdir(path):
        return []
    backups = []
    for filename in os.listdir(path):
        if not filename.endswith(".zip"):
            continue
        full_path = os.path.join(path, filename)
        backups.append(
            {
                "filename": filename,
                "path": full_path,
                "size": os.path.getsize(full_path),
                "modified_at": int(os.path.getmtime(full_path)),
                "kind": "daily" if filename.startswith("meshboard-daily-") else "manual",
            }
        )
    return sorted(backups, key=lambda item: (item["modified_at"], item["filename"]), reverse=True)


def prune_daily_backups(days):
    daily = [backup for backup in list_backups() if backup["kind"] == "daily"]
    for backup in daily[int(days) :]:
        try:
            os.remove(backup["path"])
        except OSError:
            pass


def _safe_restore_path(app_dir, member_name):
    if member_name == "backup_manifest.json" or member_name.endswith("/"):
        return None
    normalized = os.path.normpath(member_name)
    if normalized.startswith("..") or os.path.isabs(normalized):
        raise ValueError(f"Unsafe backup path: {member_name}")
    target = os.path.abspath(os.path.join(app_dir, normalized))
    app_root = os.path.abspath(app_dir)
    if os.path.commonpath([app_root, target]) != app_root:
        raise ValueError(f"Unsafe backup path: {member_name}")
    return target


def restore_backup(filename, app_dir=APP_DIR):
    filename = os.path.basename(filename or "")
    if not filename.endswith(".zip"):
        raise ValueError("Choose a backup zip file.")
    source = os.path.abspath(os.path.join(backup_dir(), filename))
    backup_root = os.path.abspath(backup_dir())
    if os.path.commonpath([backup_root, source]) != backup_root or not os.path.exists(source):
        raise ValueError("Backup file not found.")
    with zipfile.ZipFile(source, "r") as archive:
        for member in archive.infolist():
            target = _safe_restore_path(app_dir, member.filename)
            if not target:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(member, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return source


def main():
    parser = argparse.ArgumentParser(description="MeshBoard backup and restore")
    parser.add_argument("--daily", action="store_true", help="create or replace today's daily backup")
    parser.add_argument("--manual", action="store_true", help="create a timestamped manual backup")
    parser.add_argument("--restore", help="restore a backup filename from the backup directory")
    parser.add_argument("--retention-days", type=int, help="set daily backup retention days")
    args = parser.parse_args()

    if args.retention_days is not None:
        print(f"Retention days: {set_retention_days(args.retention_days)}")
    if args.restore:
        print(f"Restored {restore_backup(args.restore)}")
    elif args.daily:
        print(f"Created {create_backup('daily')}")
    elif args.manual:
        print(f"Created {create_backup('manual')}")
    else:
        for backup in list_backups():
            print(backup["filename"])


if __name__ == "__main__":
    main()
