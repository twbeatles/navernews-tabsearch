import datetime
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.backup as backup_module
from core.backup import AutoBackup


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 2, 27, 12, 0, 0, 123456)
        if tz is not None:
            return fixed.astimezone(tz)
        return fixed


class TestBackupCollisionAndRestore(unittest.TestCase):
    @staticmethod
    def _create_sqlite_db(path: Path, value: str) -> bytes:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE sample (value TEXT)")
            conn.execute("INSERT INTO sample(value) VALUES (?)", (value,))
            conn.commit()
        finally:
            conn.close()
        return path.read_bytes()

    def test_create_backup_retries_on_name_collision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            db.write_text("db", encoding="utf-8")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))

            with mock.patch("core.backup.datetime.datetime", _FixedDateTime):
                p1 = backup.create_backup(include_db=False)
                p2 = backup.create_backup(include_db=False)

            self.assertIsNotNone(p1)
            self.assertIsNotNone(p2)
            assert p1 is not None
            assert p2 is not None
            path1 = Path(p1)
            path2 = Path(p2)
            self.assertNotEqual(path1.name, path2.name)
            self.assertTrue(path1.exists())
            self.assertTrue(path2.exists())

    def test_restore_backup_fails_when_db_backup_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text('{"app_settings":{"v":1}}', encoding="utf-8")
            db.write_text("live-db", encoding="utf-8")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_dir = Path(backup.backup_dir) / "backup_missing_db"
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / cfg.name).write_text('{"app_settings":{"v":2}}', encoding="utf-8")

            ok = backup.restore_backup("backup_missing_db", restore_db=True)
            self.assertFalse(ok)
            self.assertEqual(
                json.loads(cfg.read_text(encoding="utf-8")),
                {"app_settings": {"v": 1}},
            )
            self.assertEqual(db.read_text(encoding="utf-8"), "live-db")

    def test_restore_backup_syncs_wal_shm_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            live_db_bytes = self._create_sqlite_db(db, "live-db")
            Path(str(db) + "-wal").write_text("live-wal", encoding="utf-8")
            Path(str(db) + "-shm").write_text("live-shm", encoding="utf-8")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_dir = Path(backup.backup_dir) / "backup_sidecar_policy"
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / cfg.name).write_text("{}", encoding="utf-8")
            backup_db = backup_dir / db.name
            backup_db_bytes = self._create_sqlite_db(backup_db, "backup-db")
            Path(str(backup_db) + "-wal").write_text("backup-wal", encoding="utf-8")

            with mock.patch.object(backup_module, "_validate_sqlite_backup", return_value=""):
                ok = backup.restore_backup("backup_sidecar_policy", restore_db=True)
            self.assertTrue(ok)
            self.assertNotEqual(db.read_bytes(), live_db_bytes)
            self.assertEqual(db.read_bytes(), backup_db_bytes)
            self.assertEqual(Path(str(db) + "-wal").read_text(encoding="utf-8"), "backup-wal")
            self.assertFalse(Path(str(db) + "-shm").exists())

    def test_restore_backup_rolls_back_if_apply_fails_midway(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text('{"app_settings":{"v":1}}', encoding="utf-8")
            live_db_bytes = self._create_sqlite_db(db, "live-db")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_dir = Path(backup.backup_dir) / "backup_apply_fail"
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / cfg.name).write_text('{"app_settings":{"v":2}}', encoding="utf-8")
            self._create_sqlite_db(backup_dir / db.name, "backup-db")

            original_atomic_copy = backup_module._atomic_copy_replace
            call_counter = {"count": 0}

            def fail_on_second_copy(src_path: str, dst_path: str) -> None:
                call_counter["count"] += 1
                if call_counter["count"] == 2:
                    raise OSError("simulated restore failure")
                original_atomic_copy(src_path, dst_path)

            with mock.patch.object(
                backup_module,
                "_atomic_copy_replace",
                side_effect=fail_on_second_copy,
            ):
                ok = backup.restore_backup("backup_apply_fail", restore_db=True)

            self.assertFalse(ok)
            self.assertEqual(
                json.loads(cfg.read_text(encoding="utf-8")),
                {"app_settings": {"v": 1}},
            )
            self.assertEqual(db.read_bytes(), live_db_bytes)
