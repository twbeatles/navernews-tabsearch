import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtWidgets import QMessageBox

from ui.dialogs import BackupDialog


class _FakeItem:
    def __init__(self, meta):
        self._meta = meta

    def data(self, _role):
        return self._meta


class _FakeBackupList:
    def __init__(self, item):
        self._item = item

    def currentItem(self):
        return self._item


class _FakeAutoBackup:
    def __init__(self, backup_dir: str, db_file: str):
        self.backup_dir = backup_dir
        self.db_file = db_file
        self.calls = []

    def schedule_restore(self, backup_name: str, restore_db: bool = True):
        self.calls.append((backup_name, bool(restore_db)))
        return True


class _DummyDialog:
    def __init__(self, backup_list, auto_backup):
        self.backup_list = backup_list
        self.auto_backup = auto_backup


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


if __name__ == "__main__":
    unittest.main()
