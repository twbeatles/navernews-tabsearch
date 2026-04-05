import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.backup import AutoBackup
from core.backup import verify_backup_payload
from core.config_store import DEFAULT_CONFIG
from core.config_store import load_config_file
from core.config_store import save_config_file_atomic
from core.config_store import save_primary_config_file
from core.database import DatabaseManager
from core.startup import StartupManager
from core.workers import DBQueryScope
from core.workers import JobCancelledError
from ui._main_window_settings_io import export_scope_to_csv


class _FakeExportDB:
    def __init__(self, items):
        self.items = list(items)
        self.fetch_calls = []

    def count_news(self, **_kwargs):
        return len(self.items)

    def fetch_news(self, limit=50, offset=0, **_kwargs):
        self.fetch_calls.append((limit, offset))
        return list(self.items[offset : offset + limit])


class _FakeExportContext:
    def __init__(self, cancel_on_check=None):
        self.cancel_on_check = cancel_on_check
        self.check_count = 0
        self.reports = []

    def report(self, **kwargs):
        self.reports.append(dict(kwargs))

    def check_cancelled(self):
        self.check_count += 1
        if self.cancel_on_check is not None and self.check_count >= self.cancel_on_check:
            raise JobCancelledError()


class _FakeRegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1

    def __init__(self, value):
        self.value = value

    def OpenKey(self, *_args, **_kwargs):
        return _FakeRegistryKey()

    def QueryValueEx(self, _key, _name):
        if self.value is None:
            raise FileNotFoundError
        return self.value, 1


class TestExportScopeToCsv(unittest.TestCase):
    def _item(self, index):
        return {
            "title": f"title-{index}",
            "link": f"https://example.com/{index}",
            "pubDate": "2026-03-25",
            "publisher": "example.com",
            "description": f"description-{index}",
            "is_read": 0,
            "is_bookmarked": 0,
            "notes": "",
            "is_duplicate": 0,
        }

    def test_chunked_export_streams_all_rows(self):
        items = [self._item(index) for index in range(5)]
        db = _FakeExportDB(items)
        context = _FakeExportContext()

        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "export.csv"
            result = export_scope_to_csv(
                context,
                db,
                DBQueryScope(keyword="AI"),
                str(output_path),
                "AI",
                chunk_size=2,
            )

            rows = list(csv.reader(output_path.open("r", encoding="utf-8-sig")))

        self.assertEqual(result["count"], 5)
        self.assertEqual(db.fetch_calls, [(2, 0), (2, 2), (2, 4)])
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[1][0], "title-0")
        self.assertEqual(rows[5][0], "title-4")
        self.assertTrue(any("내보내기 준비 중" in report.get("message", "") for report in context.reports))

    def test_cancelled_export_removes_tmp_file(self):
        items = [self._item(index) for index in range(3)]
        db = _FakeExportDB(items)
        context = _FakeExportContext(cancel_on_check=2)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output_path = root / "export.csv"

            with self.assertRaises(JobCancelledError):
                export_scope_to_csv(
                    context,
                    db,
                    DBQueryScope(keyword="AI"),
                    str(output_path),
                    "AI",
                    chunk_size=2,
                )

            self.assertFalse(output_path.exists())
            self.assertEqual(list(root.glob(".export_*.tmp")), [])


class TestBackupVerification(unittest.TestCase):
    @staticmethod
    def _create_sqlite_db(path: Path, value: str) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE sample (value TEXT)")
            conn.execute("INSERT INTO sample(value) VALUES (?)", (value,))
            conn.commit()
        finally:
            conn.close()

    def test_verify_backup_payload_flags_corrupt_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            backup_dir = root / "backup_corrupt_cfg"
            backup_dir.mkdir()
            (backup_dir / cfg.name).write_text("{broken-json", encoding="utf-8")

            result = verify_backup_payload(str(backup_dir), str(cfg), str(db), require_db=False)

        self.assertTrue(result["is_corrupt"])
        self.assertFalse(result["is_restorable"])
        self.assertEqual(result["verification_state"], "failed")
        self.assertIn("손상되었습니다", result["error"])

    def test_verify_backup_payload_flags_corrupt_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            backup_dir = root / "backup_corrupt_db"
            backup_dir.mkdir()
            (backup_dir / cfg.name).write_text("{}", encoding="utf-8")
            (backup_dir / db.name).write_text("not-a-sqlite-db", encoding="utf-8")

            result = verify_backup_payload(str(backup_dir), str(cfg), str(db), require_db=True)

        self.assertTrue(result["is_corrupt"])
        self.assertFalse(result["is_restorable"])
        self.assertEqual(result["verification_state"], "failed")
        self.assertIn("데이터베이스", result["error"])

    def test_auto_backup_entry_is_self_verified_before_listing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            self._create_sqlite_db(db, "live")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))
            created = backup.create_backup(include_db=True, trigger="manual")
            self.assertIsNotNone(created)
            assert created is not None
            backup_name = Path(created).name

            quick_entry = next(item for item in backup.get_backup_list() if item["name"] == backup_name)
            verified_entry = backup.verify_backup_by_name(backup_name, require_db=True)

        self.assertEqual(quick_entry["verification_state"], "ok")
        self.assertTrue(quick_entry["is_restorable"])
        self.assertEqual(verified_entry["verification_state"], "ok")
        self.assertTrue(verified_entry["is_restorable"])
        self.assertFalse(verified_entry["is_corrupt"])


class TestStartupStatus(unittest.TestCase):
    def test_get_startup_status_reports_healthy_registration(self):
        expected_command = '"C:\\Python311\\python.exe" "D:\\app\\news_scraper_pro.py" --minimized'
        fake_winreg = _FakeWinreg(expected_command)

        with mock.patch.object(StartupManager, "is_available", return_value=True):
            with mock.patch.object(StartupManager, "build_startup_command", return_value=expected_command):
                with mock.patch("core.startup._get_winreg", return_value=fake_winreg):
                    with mock.patch("core.startup.os.path.exists", return_value=True):
                        status = StartupManager.get_startup_status(start_minimized=True)

        self.assertTrue(status["has_registry_value"])
        self.assertTrue(status["command_matches"])
        self.assertTrue(status["target_exists"])
        self.assertTrue(status["is_healthy"])
        self.assertFalse(status["needs_repair"])
        self.assertEqual(status["actual_target"], "D:\\app\\news_scraper_pro.py")

    def test_get_startup_status_marks_stale_registration_for_repair(self):
        expected_command = '"C:\\Python311\\python.exe" "D:\\app\\news_scraper_pro.py" --minimized'
        actual_command = '"C:\\Python311\\python.exe" "D:\\app\\news_scraper_pro.py"'
        fake_winreg = _FakeWinreg(actual_command)

        with mock.patch.object(StartupManager, "is_available", return_value=True):
            with mock.patch.object(StartupManager, "build_startup_command", return_value=expected_command):
                with mock.patch("core.startup._get_winreg", return_value=fake_winreg):
                    with mock.patch("core.startup.os.path.exists", return_value=False):
                        status = StartupManager.get_startup_status(start_minimized=True)

        self.assertTrue(status["has_registry_value"])
        self.assertFalse(status["command_matches"])
        self.assertFalse(status["target_exists"])
        self.assertFalse(status["is_healthy"])
        self.assertTrue(status["needs_repair"])


class TestConfigDurability(unittest.TestCase):
    def test_save_primary_config_file_rotates_previous_valid_file_to_backup(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"

            initial = copy.deepcopy(DEFAULT_CONFIG)
            initial["app_settings"]["theme_index"] = 1
            save_config_file_atomic(str(cfg_path), initial)

            updated = copy.deepcopy(DEFAULT_CONFIG)
            updated["app_settings"]["theme_index"] = 2
            save_primary_config_file(str(cfg_path), updated)

            saved_main = json.loads(cfg_path.read_text(encoding="utf-8"))
            saved_backup = json.loads(Path(f"{cfg_path}.backup").read_text(encoding="utf-8"))

        self.assertEqual(saved_main["app_settings"]["theme_index"], 2)
        self.assertEqual(saved_backup["app_settings"]["theme_index"], 1)

    def test_load_config_file_recovers_from_backup_when_primary_is_corrupt(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            backup_path = Path(f"{cfg_path}.backup")

            healthy = copy.deepcopy(DEFAULT_CONFIG)
            healthy["app_settings"]["api_timeout"] = 33
            save_config_file_atomic(str(backup_path), healthy)
            cfg_path.write_text("{broken-json", encoding="utf-8")

            loaded = load_config_file(str(cfg_path))

        self.assertEqual(loaded["app_settings"]["api_timeout"], 33)


class TestDatabaseEmergencyCap(unittest.TestCase):
    def test_pool_exhaustion_raises_when_emergency_cap_is_zero(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "news.db"
            db = DatabaseManager(str(db_path), max_connections=1, max_emergency_connections=0)
            conn = db.get_connection(timeout=0.01)
            try:
                with self.assertRaises(RuntimeError):
                    db.get_connection(timeout=0.01)
                self.assertEqual(db._emergency_connection_rejections, 1)
            finally:
                db.return_connection(conn)
                db.close()

    def test_emergency_connection_is_tracked_and_released(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "news.db"
            db = DatabaseManager(str(db_path), max_connections=1, max_emergency_connections=1)
            pooled = db.get_connection(timeout=0.01)
            emergency = None
            try:
                emergency = db.get_connection(timeout=0.01)
                self.assertEqual(db._emergency_connection_uses, 1)
                self.assertEqual(len(db._emergency_connections), 1)
            finally:
                if emergency is not None:
                    db.return_connection(emergency)
                db.return_connection(pooled)
                self.assertEqual(len(db._emergency_connections), 0)
                db.close()


if __name__ == "__main__":
    unittest.main()
