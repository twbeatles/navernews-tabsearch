import tempfile
import unittest
from pathlib import Path
from unittest import mock

import news_scraper_pro as app
from PyQt6.QtWidgets import QMessageBox

from ui.dialogs import BackupDialog


class _FakeItem:
    def __init__(self, meta=None, text=""):
        self._meta = meta
        self.text = text

    def data(self, _role):
        return self._meta

    def setData(self, _role, meta):
        self._meta = meta


class _FakeBackupList:
    def __init__(self, item):
        self._item = item

    def currentItem(self):
        return self._item


class _FakeListWidget:
    def __init__(self):
        self.items = []

    def clear(self):
        self.items.clear()

    def addItem(self, text):
        self.items.append(_FakeItem(text=text))

    def item(self, index):
        return self.items[index]

    def count(self):
        return len(self.items)


class _FakeAutoBackup:
    def __init__(self, backup_dir: str, db_file: str):
        self.backup_dir = backup_dir
        self.db_file = db_file
        self.calls = []
        self.backups = []

    def schedule_restore(self, backup_name: str, restore_db: bool = True):
        self.calls.append((backup_name, bool(restore_db)))
        return True

    def get_backup_list(self):
        return list(self.backups)


class _DummyDialog:
    def __init__(self, backup_list, auto_backup):
        self.backup_list = backup_list
        self.auto_backup = auto_backup
        self.format_backup_timestamp = BackupDialog.format_backup_timestamp


class TestBackupRestoreMode(unittest.TestCase):
    def test_restore_backup_uses_include_db_metadata(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        dialog = _DummyDialog(
            _FakeBackupList(_FakeItem({"backup_name": "backup_meta", "include_db": False})),
            auto_backup,
        )

        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            with mock.patch.object(QMessageBox, "information"):
                BackupDialog.restore_backup(dialog)

        self.assertEqual(auto_backup.calls, [("backup_meta", False)])

    def test_restore_backup_legacy_fallback_detects_db_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backup_name = "backup_legacy"
            backup_dir = root / backup_name
            backup_dir.mkdir(parents=True, exist_ok=True)

            db_file = root / "news_database.db"
            db_backup = backup_dir / db_file.name
            db_backup.write_text("db", encoding="utf-8")

            auto_backup = _FakeAutoBackup(backup_dir=str(root), db_file=str(db_file))
            dialog = _DummyDialog(
                _FakeBackupList(_FakeItem(backup_name)),
                auto_backup,
            )

            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                with mock.patch.object(QMessageBox, "information"):
                    BackupDialog.restore_backup(dialog)

            self.assertEqual(auto_backup.calls, [(backup_name, True)])

    def test_backup_cleanup_keeps_manual_backups_when_auto_backups_rotate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "news.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            db.write_text("", encoding="utf-8")

            auto_backup = app.AutoBackup(config_file=str(cfg), db_file=str(db))
            auto_backup.MAX_AUTO_BACKUPS = 2
            auto_backup.MAX_MANUAL_BACKUPS = 5

            manual_path = auto_backup.create_backup(include_db=False, trigger="manual")
            self.assertIsNotNone(manual_path)

            for _ in range(3):
                self.assertIsNotNone(auto_backup.create_backup(include_db=False, trigger="auto"))

            backups = auto_backup.get_backup_list()
            manual_backups = [backup for backup in backups if backup.get("trigger") == "manual"]
            auto_backups = [backup for backup in backups if backup.get("trigger") == "auto"]

            self.assertEqual(len(manual_backups), 1)
            self.assertEqual(len(auto_backups), 2)

    def test_load_backups_formats_microsecond_timestamp_and_trigger_label(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        auto_backup.backups = [
            {
                "name": "backup_1",
                "timestamp": "20260306_101530_123456",
                "app_version": "32.7.2",
                "include_db": True,
                "trigger": "auto",
                "created_at": "2026-03-06T10:15:30",
            }
        ]
        dialog = _DummyDialog(_FakeListWidget(), auto_backup)

        BackupDialog.load_backups(dialog)

        self.assertEqual(dialog.backup_list.count(), 1)
        self.assertIn("2026-03-06 10:15:30", dialog.backup_list.item(0).text)
        self.assertIn("🤖 자동", dialog.backup_list.item(0).text)
        self.assertEqual(
            dialog.backup_list.item(0).data(None),
            {"backup_name": "backup_1", "include_db": True, "trigger": "auto"},
        )


if __name__ == "__main__":
    unittest.main()
