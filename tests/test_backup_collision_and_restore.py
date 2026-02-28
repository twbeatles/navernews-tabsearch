import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.backup import AutoBackup


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 2, 27, 12, 0, 0, 123456)
        if tz is not None:
            return fixed.astimezone(tz)
        return fixed


class TestBackupCollisionAndRestore(unittest.TestCase):
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
            self.assertNotEqual(Path(p1).name, Path(p2).name)
            self.assertTrue(Path(p1).exists())
            self.assertTrue(Path(p2).exists())

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
            self.assertEqual(db.read_text(encoding="utf-8"), "live-db")

    def test_restore_backup_syncs_wal_shm_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            cfg.write_text("{}", encoding="utf-8")
            db.write_text("live-db", encoding="utf-8")
            Path(str(db) + "-wal").write_text("live-wal", encoding="utf-8")
            Path(str(db) + "-shm").write_text("live-shm", encoding="utf-8")

            backup = AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_dir = Path(backup.backup_dir) / "backup_sidecar_policy"
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / cfg.name).write_text("{}", encoding="utf-8")
            backup_db = backup_dir / db.name
            backup_db.write_text("backup-db", encoding="utf-8")
            Path(str(backup_db) + "-wal").write_text("backup-wal", encoding="utf-8")

            ok = backup.restore_backup("backup_sidecar_policy", restore_db=True)
            self.assertTrue(ok)
            self.assertEqual(db.read_text(encoding="utf-8"), "backup-db")
            self.assertEqual(Path(str(db) + "-wal").read_text(encoding="utf-8"), "backup-wal")
            self.assertFalse(Path(str(db) + "-shm").exists())
