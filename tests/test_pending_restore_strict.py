import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.backup as backup_module
from core.backup import apply_pending_restore_if_any


class TestPendingRestoreStrictPolicy(unittest.TestCase):
    def test_restore_db_requires_db_backup_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            pending = root / "pending_restore.json"
            backup_dir = root / "backups" / "backup_1"
            backup_dir.mkdir(parents=True, exist_ok=True)

            cfg.write_text(
                json.dumps({"app_settings": {"x": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            conn = sqlite3.connect(str(db))
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS t (v INTEGER)")
                conn.execute("DELETE FROM t")
                conn.execute("INSERT INTO t(v) VALUES (1)")
                conn.commit()
            finally:
                conn.close()

            # Intentionally omit DB backup file and keep only config backup.
            (backup_dir / cfg.name).write_text(
                json.dumps({"app_settings": {"x": 2}}, ensure_ascii=False),
                encoding="utf-8",
            )

            pending.write_text(
                json.dumps(
                    {
                        "backup_name": "backup_1",
                        "backup_dir": str(root / "backups"),
                        "restore_db": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ok = apply_pending_restore_if_any(
                pending_file=str(pending),
                config_file=str(cfg),
                db_file=str(db),
            )
            self.assertFalse(ok)
            self.assertTrue(pending.exists())

            loaded_cfg = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(loaded_cfg["app_settings"]["x"], 1)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute("SELECT v FROM t LIMIT 1").fetchone()
                self.assertEqual(int(row[0]), 1)
            finally:
                conn.close()

    def test_apply_failure_rolls_back_and_keeps_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "config.json"
            db = root / "db.sqlite"
            pending = root / "pending_restore.json"
            backup_dir = root / "backups" / "backup_2"
            backup_dir.mkdir(parents=True, exist_ok=True)

            cfg.write_text(
                json.dumps({"app_settings": {"x": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            conn = sqlite3.connect(str(db))
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS t (v INTEGER)")
                conn.execute("DELETE FROM t")
                conn.execute("INSERT INTO t(v) VALUES (1)")
                conn.commit()
            finally:
                conn.close()

            (backup_dir / cfg.name).write_text(
                json.dumps({"app_settings": {"x": 2}}, ensure_ascii=False),
                encoding="utf-8",
            )
            backup_db = backup_dir / db.name
            conn = sqlite3.connect(str(backup_db))
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS t (v INTEGER)")
                conn.execute("DELETE FROM t")
                conn.execute("INSERT INTO t(v) VALUES (2)")
                conn.commit()
            finally:
                conn.close()

            pending.write_text(
                json.dumps(
                    {
                        "backup_name": "backup_2",
                        "backup_dir": str(root / "backups"),
                        "restore_db": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_atomic_copy = backup_module._atomic_copy_replace
            call_counter = {"count": 0}

            def fail_on_second_copy(src_path: str, dst_path: str) -> None:
                call_counter["count"] += 1
                if call_counter["count"] == 2:
                    raise OSError("simulated db apply failure")
                original_atomic_copy(src_path, dst_path)

            with mock.patch.object(backup_module, "_atomic_copy_replace", side_effect=fail_on_second_copy):
                ok = apply_pending_restore_if_any(
                    pending_file=str(pending),
                    config_file=str(cfg),
                    db_file=str(db),
                )

            self.assertFalse(ok)
            self.assertTrue(pending.exists())

            loaded_cfg = json.loads(cfg.read_text(encoding="utf-8"))
            self.assertEqual(loaded_cfg["app_settings"]["x"], 1)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute("SELECT v FROM t LIMIT 1").fetchone()
                self.assertEqual(int(row[0]), 1)
            finally:
                conn.close()
