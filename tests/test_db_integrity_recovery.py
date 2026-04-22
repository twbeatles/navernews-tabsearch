import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from core._db_schema import IntegrityCheckResult, _DatabaseSchemaMixin
from core.database import DatabaseManager


class _SchemaHarness(_DatabaseSchemaMixin):
    def __init__(self, db_file: str):
        self.db_file = db_file


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, _sql: str):
        return None

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._cursor = _FakeCursor(row)

    def cursor(self):
        return self._cursor

    def close(self):
        return None


class TestDatabaseIntegrityRecovery(unittest.TestCase):
    def test_check_integrity_distinguishes_corrupt_result(self):
        harness = _SchemaHarness("dummy.db")
        with mock.patch("core._db_schema.sqlite3.connect", return_value=_FakeConnection(("broken page",))):
            result = cast(Any, harness)._check_integrity()
        self.assertEqual(result.state, "corrupt")
        self.assertIn("broken page", result.detail)

    def test_check_integrity_distinguishes_unreadable_exception(self):
        harness = _SchemaHarness("dummy.db")
        with mock.patch("core._db_schema.sqlite3.connect", side_effect=sqlite3.OperationalError("database is locked")):
            result = cast(Any, harness)._check_integrity()
        self.assertEqual(result.state, "unreadable")
        self.assertIn("locked", result.detail)

    def test_database_manager_only_recovers_on_confirmed_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "news.db"
            db_path.write_text("placeholder", encoding="utf-8")

            with mock.patch.object(DatabaseManager, "_check_integrity", return_value=IntegrityCheckResult("unreadable", "locked")):
                with mock.patch.object(DatabaseManager, "_recover_database") as recover_mock:
                    with mock.patch.object(DatabaseManager, "init_db"):
                        manager = DatabaseManager(str(db_path), max_connections=0)
                        manager.close()
            recover_mock.assert_not_called()

            with mock.patch.object(DatabaseManager, "_check_integrity", return_value=IntegrityCheckResult("corrupt", "bad page")):
                with mock.patch.object(DatabaseManager, "_recover_database") as recover_mock:
                    with mock.patch.object(DatabaseManager, "init_db"):
                        manager = DatabaseManager(str(db_path), max_connections=0)
                        manager.close()
            recover_mock.assert_called_once()

    def test_recover_database_preserves_db_sidecar_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "news.db"
            wal_path = root / "news.db-wal"
            shm_path = root / "news.db-shm"
            db_path.write_text("db", encoding="utf-8")
            wal_path.write_text("wal", encoding="utf-8")
            shm_path.write_text("shm", encoding="utf-8")

            harness = _SchemaHarness(str(db_path))
            cast(Any, harness)._recover_database()

            self.assertFalse(db_path.exists())
            self.assertFalse(wal_path.exists())
            self.assertFalse(shm_path.exists())

            corrupt_dirs = [path for path in root.iterdir() if path.is_dir() and path.name.startswith("news.db.corrupt_")]
            self.assertEqual(len(corrupt_dirs), 1)
            corrupt_dir = corrupt_dirs[0]
            self.assertTrue((corrupt_dir / "news.db").exists())
            self.assertTrue((corrupt_dir / "news.db-wal").exists())
            self.assertTrue((corrupt_dir / "news.db-shm").exists())


if __name__ == "__main__":
    unittest.main()
