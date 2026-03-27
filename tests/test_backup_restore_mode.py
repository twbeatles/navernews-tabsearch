import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
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
        self.verify_calls = []
        self.backups = []

    def schedule_restore(self, backup_name: str, restore_db: bool = True):
        self.calls.append((backup_name, bool(restore_db)))
        return True

    def get_backup_list(self):
        return list(self.backups)

    def create_backup(self, include_db: bool = True, trigger: str = "manual"):
        self.calls.append(("create_backup", bool(include_db)))
        return str(Path(self.backup_dir) / "safeguard_backup")

    def verify_backup_by_name(self, backup_name: str, require_db: bool = True):
        self.verify_calls.append((backup_name, bool(require_db)))
        for backup in self.backups:
            current_name = str(backup.get("name", "") or backup.get("backup_name", ""))
            if current_name == backup_name:
                entry = dict(backup)
                break
        else:
            entry = {
                "name": backup_name,
                "backup_name": backup_name,
                "include_db": bool(require_db),
            }

        is_corrupt = bool(entry.get("is_corrupt", False))
        entry.setdefault("is_restorable", not is_corrupt)
        entry.setdefault("restore_error", "")
        entry.setdefault("error", "")
        entry.setdefault("verification_state", "verified")
        entry.setdefault("verification_error", "")
        return entry

    def delete_backup(self, backup_name: str):
        backup_path = Path(self.backup_dir) / backup_name
        if backup_path.exists():
            for child in backup_path.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            backup_path.rmdir()
            return True, ""
        return False, "missing backup"


class _DummyDialog:
    def __init__(self, backup_list, auto_backup):
        self.backup_list = backup_list
        self.auto_backup = auto_backup
        self.format_backup_timestamp = BackupDialog.format_backup_timestamp
        self.load_backups = lambda: None
        self.start_backup_verification = mock.Mock()
        self._backup_item_text = lambda backup: BackupDialog._backup_item_text(cast(Any, self), backup)
        self._backup_item_meta = lambda backup: BackupDialog._backup_item_meta(cast(Any, self), backup)
        self._apply_backup_item_state = (
            lambda item, backup: BackupDialog._apply_backup_item_state(cast(Any, self), item, backup)
        )
        self._handle_corrupt_backup = (
            lambda backup_name, corrupt_error: BackupDialog._handle_corrupt_backup(
                cast(Any, self), backup_name, corrupt_error
            )
        )


class TestBackupRestoreMode(unittest.TestCase):
    def test_restore_backup_uses_include_db_metadata(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        dialog = _DummyDialog(
            _FakeBackupList(_FakeItem({"backup_name": "backup_meta", "include_db": False})),
            auto_backup,
        )

        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            with mock.patch.object(QMessageBox, "information"):
                BackupDialog.restore_backup(cast(Any, dialog))

        self.assertEqual(auto_backup.verify_calls, [("backup_meta", False)])
        self.assertEqual(auto_backup.calls, [("create_backup", False), ("backup_meta", False)])

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
                    BackupDialog.restore_backup(cast(Any, dialog))

            self.assertEqual(auto_backup.verify_calls, [(backup_name, True)])
            self.assertEqual(auto_backup.calls, [("create_backup", True), (backup_name, True)])

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

        BackupDialog.load_backups(cast(Any, dialog))

        self.assertEqual(dialog.backup_list.count(), 1)
        self.assertIn("2026-03-06 10:15:30", dialog.backup_list.item(0).text)
        self.assertIn("자동", dialog.backup_list.item(0).text)
        self.assertEqual(
            dialog.backup_list.item(0).data(None),
            {
                "name": "backup_1",
                "backup_name": "backup_1",
                "path": "",
                "timestamp": "20260306_101530_123456",
                "app_version": "32.7.2",
                "include_db": True,
                "trigger": "auto",
                "created_at": "2026-03-06T10:15:30",
                "is_corrupt": False,
                "error": "",
                "is_restorable": True,
                "restore_error": "",
                "verification_state": "pending",
                "verification_error": "",
            },
        )

    def test_get_backup_list_keeps_valid_entries_when_one_is_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "news.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            db.write_text("", encoding="utf-8")

            auto_backup = app.AutoBackup(config_file=str(cfg), db_file=str(db))
            valid_path = auto_backup.create_backup(include_db=False, trigger="manual")
            self.assertIsNotNone(valid_path)
            assert valid_path is not None

            corrupt_dir = Path(auto_backup.backup_dir) / "backup_corrupt_meta"
            corrupt_dir.mkdir(parents=True, exist_ok=True)
            (corrupt_dir / "backup_info.json").write_text("{broken-json", encoding="utf-8")

            backups = auto_backup.get_backup_list()
            by_name = {entry["name"]: entry for entry in backups}

            self.assertIn(Path(valid_path).name, by_name)
            self.assertFalse(bool(by_name[Path(valid_path).name].get("is_corrupt")))
            self.assertIn("backup_corrupt_meta", by_name)
            self.assertTrue(bool(by_name["backup_corrupt_meta"].get("is_corrupt")))
            self.assertIn("error", by_name["backup_corrupt_meta"])

    def test_load_backups_marks_corrupt_items(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        auto_backup.backups = [
            {
                "name": "backup_broken",
                "timestamp": "20260307_010203_000000",
                "app_version": "32.7.2",
                "include_db": False,
                "trigger": "manual",
                "created_at": "2026-03-07T01:02:03",
                "is_corrupt": True,
                "error": "invalid json",
            }
        ]
        dialog = _DummyDialog(_FakeListWidget(), auto_backup)

        BackupDialog.load_backups(cast(Any, dialog))

        self.assertEqual(dialog.backup_list.count(), 1)
        self.assertIn("손상됨", dialog.backup_list.item(0).text)
        self.assertEqual(
            dialog.backup_list.item(0).data(None),
            {
                "name": "backup_broken",
                "backup_name": "backup_broken",
                "path": "",
                "timestamp": "20260307_010203_000000",
                "app_version": "32.7.2",
                "include_db": False,
                "trigger": "manual",
                "created_at": "2026-03-07T01:02:03",
                "is_corrupt": True,
                "error": "invalid json",
                "is_restorable": False,
                "restore_error": "",
                "verification_state": "pending",
                "verification_error": "",
            },
        )

    def test_load_backups_does_not_auto_start_verification(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        auto_backup.backups = [
            {
                "name": "backup_1",
                "timestamp": "20260306_101530_123456",
                "app_version": "32.7.2",
                "include_db": False,
                "trigger": "manual",
                "created_at": "2026-03-06T10:15:30",
            }
        ]
        dialog = _DummyDialog(_FakeListWidget(), auto_backup)

        BackupDialog.load_backups(cast(Any, dialog))

        dialog.start_backup_verification.assert_not_called()

    def test_restore_backup_corrupt_item_delete_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backup_name = "backup_broken"
            backup_path = root / backup_name
            backup_path.mkdir(parents=True, exist_ok=True)

            auto_backup = _FakeAutoBackup(backup_dir=str(root), db_file=str(root / "news_database.db"))
            dialog = _DummyDialog(
                _FakeBackupList(
                    _FakeItem(
                        {
                            "backup_name": backup_name,
                            "include_db": False,
                            "is_corrupt": True,
                            "error": "bad metadata",
                        }
                    )
                ),
                auto_backup,
            )
            dialog.load_backups = mock.Mock()

            delete_button = object()
            ignore_button = object()
            fake_message_box = mock.Mock()
            fake_message_box.addButton.side_effect = [delete_button, ignore_button]
            fake_message_box.clickedButton.return_value = delete_button

            with mock.patch("ui.dialogs.QMessageBox") as msgbox_cls:
                msgbox_cls.return_value = fake_message_box
                msgbox_cls.Icon = mock.Mock(Warning=1)
                msgbox_cls.ButtonRole = mock.Mock(AcceptRole=1, RejectRole=2)
                msgbox_cls.information = mock.Mock()
                msgbox_cls.warning = mock.Mock()

                BackupDialog.restore_backup(cast(Any, dialog))

            self.assertFalse(backup_path.exists())
            dialog.load_backups.assert_called_once()

    def test_restore_backup_blocks_non_restorable_item(self):
        auto_backup = _FakeAutoBackup(backup_dir="C:\\tmp", db_file="C:\\tmp\\news_database.db")
        dialog = _DummyDialog(
            _FakeBackupList(
                _FakeItem(
                    {
                        "backup_name": "backup_missing_db",
                        "include_db": True,
                        "is_restorable": False,
                        "restore_error": "데이터베이스 백업 파일이 없습니다.",
                    }
                )
            ),
            auto_backup,
        )

        with mock.patch.object(QMessageBox, "warning") as warning_mock:
            BackupDialog.restore_backup(cast(Any, dialog))

        warning_mock.assert_called_once()
        self.assertEqual(auto_backup.calls, [])

    def test_create_backup_returns_none_when_db_requested_but_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            cfg.write_text("{}", encoding="utf-8")
            db = root / "missing.sqlite"

            auto_backup = app.AutoBackup(config_file=str(cfg), db_file=str(db))

            self.assertIsNone(auto_backup.create_backup(include_db=True, trigger="manual"))

    def test_backup_dialog_prechecks_missing_db_before_create(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            auto_backup = _FakeAutoBackup(
                backup_dir=str(root / "backups"),
                db_file=str(root / "missing.sqlite"),
            )

            class _Check:
                def isChecked(self):
                    return True

            dialog = _DummyDialog(_FakeBackupList(None), auto_backup)
            setattr(dialog, "chk_include_db", _Check())

            with mock.patch.object(QMessageBox, "warning") as warning_mock:
                BackupDialog.create_backup(cast(Any, dialog))

            warning_mock.assert_called_once()
            self.assertEqual(auto_backup.calls, [])

    def test_get_backup_list_marks_missing_db_payload_as_not_restorable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "news.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            db.write_text("", encoding="utf-8")

            auto_backup = app.AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_path = auto_backup.create_backup(include_db=False, trigger="manual")
            self.assertIsNotNone(backup_path)
            assert backup_path is not None

            info_path = Path(backup_path) / "backup_info.json"
            info = info_path.read_text(encoding="utf-8")
            info_path.write_text(info.replace('"include_db": false', '"include_db": true'), encoding="utf-8")

            backups = auto_backup.get_backup_list()
            item = next(entry for entry in backups if entry["name"] == Path(backup_path).name)
            self.assertFalse(item["is_restorable"])
            self.assertIn("데이터베이스", item["restore_error"])


if __name__ == "__main__":
    unittest.main()
