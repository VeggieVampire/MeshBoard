import os
import tempfile
import unittest
import zipfile

import backup_manager


class BackupManagerTests(unittest.TestCase):
    def with_backup_dir(self, path):
        old_value = os.environ.get("MESHBOARD_BACKUP_DIR")
        os.environ["MESHBOARD_BACKUP_DIR"] = path
        return old_value

    def restore_backup_dir(self, old_value):
        if old_value is None:
            os.environ.pop("MESHBOARD_BACKUP_DIR", None)
        else:
            os.environ["MESHBOARD_BACKUP_DIR"] = old_value

    def test_daily_backup_overwrites_and_prunes_old_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(os.path.join(app_dir, "backups"))
            os.makedirs(os.path.join(app_dir, "__pycache__"))
            os.makedirs(os.path.join(app_dir, ".codex"))
            os.makedirs(os.path.join(app_dir, "modules"))
            with open(os.path.join(app_dir, "meshboard.db"), "w", encoding="utf-8") as handle:
                handle.write("db")
            with open(os.path.join(app_dir, "admin_config.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            with open(os.path.join(app_dir, ".codex", "huge.sqlite"), "w", encoding="utf-8") as handle:
                handle.write("skip")
            with open(os.path.join(app_dir, "modules", "plugin.py"), "w", encoding="utf-8") as handle:
                handle.write("keep")
            with open(os.path.join(app_dir, "listener.log"), "w", encoding="utf-8") as handle:
                handle.write("skip")
            with open(os.path.join(app_dir, "backups", "nested.zip"), "w", encoding="utf-8") as handle:
                handle.write("skip")

            old_value = self.with_backup_dir(backup_dir)
            try:
                first = backup_manager.create_backup("daily", now=1788830000, app_dir=app_dir)
                second = backup_manager.create_backup("daily", now=1788830060, app_dir=app_dir)
                self.assertEqual(first, second)

                with zipfile.ZipFile(second, "r") as archive:
                    names = set(archive.namelist())
                self.assertIn("meshboard.db", names)
                self.assertIn("admin_config.json", names)
                self.assertIn("modules/plugin.py", names)
                self.assertIn("backup_manifest.json", names)
                self.assertNotIn(".codex/huge.sqlite", names)
                self.assertNotIn("listener.log", names)
                self.assertNotIn("backups/nested.zip", names)

                for day in range(10):
                    backup_manager.create_backup("daily", now=1788830000 + day * 86400, app_dir=app_dir)
                backup_manager.prune_daily_backups(7)
                daily = [item for item in backup_manager.list_backups() if item["kind"] == "daily"]
                self.assertEqual(7, len(daily))
            finally:
                self.restore_backup_dir(old_value)

    def test_restore_backup_replaces_files_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(app_dir)
            target = os.path.join(app_dir, "meshboard.db")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")

            old_value = self.with_backup_dir(backup_dir)
            try:
                backup_path = backup_manager.create_backup("manual", now=1788830000, app_dir=app_dir)
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write("after")

                backup_manager.restore_backup(os.path.basename(backup_path), app_dir=app_dir)

                with open(target, "r", encoding="utf-8") as handle:
                    self.assertEqual("before", handle.read())
            finally:
                self.restore_backup_dir(old_value)

    def test_restore_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "app")
            backup_dir = os.path.join(tmpdir, "backups")
            os.makedirs(app_dir)
            os.makedirs(backup_dir)
            backup_path = os.path.join(backup_dir, "meshboard-manual-bad.zip")
            with zipfile.ZipFile(backup_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")

            old_value = self.with_backup_dir(backup_dir)
            try:
                with self.assertRaises(ValueError):
                    backup_manager.restore_backup(os.path.basename(backup_path), app_dir=app_dir)
            finally:
                self.restore_backup_dir(old_value)
