import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.constants import get_data_dir, get_runtime_paths, migrate_legacy_runtime_files


class TestRuntimeStoragePaths(unittest.TestCase):
    def _create_sqlite_db(self, path: Path, value: int = 1) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS sample (value INTEGER)")
            conn.execute("DELETE FROM sample")
            conn.execute("INSERT INTO sample(value) VALUES (?)", (int(value),))
            conn.commit()
        finally:
            conn.close()

    def test_get_data_dir_prefers_explicit_override(self):
        env = {"NEWS_SCRAPER_DATA_DIR": r"D:\custom-runtime"}
        resolved = get_data_dir(env=env, platform="win32", app_dir=r"D:\portable-app")
        self.assertEqual(resolved, r"D:\custom-runtime")

    def test_get_data_dir_uses_localappdata_on_windows(self):
        env = {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}
        resolved = get_data_dir(env=env, platform="win32", app_dir=r"D:\portable-app")
        self.assertEqual(resolved, r"C:\Users\tester\AppData\Local\NaverNewsScraperPro")

    def test_get_data_dir_supports_portable_mode_override(self):
        env = {"NEWS_SCRAPER_PORTABLE": "1", "LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}
        resolved = get_data_dir(env=env, platform="win32", app_dir=r"D:\portable-app")
        self.assertEqual(resolved, r"D:\portable-app")

    def test_get_runtime_paths_exposes_runtime_files(self):
        runtime_paths = get_runtime_paths(
            env={"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"},
            platform="win32",
            app_dir=r"D:\portable-app",
        )
        self.assertEqual(runtime_paths.data_dir, r"C:\Users\tester\AppData\Local\NaverNewsScraperPro")
        self.assertEqual(runtime_paths.config_file, r"C:\Users\tester\AppData\Local\NaverNewsScraperPro\news_scraper_config.json")
        self.assertEqual(runtime_paths.db_file, r"C:\Users\tester\AppData\Local\NaverNewsScraperPro\news_database.db")
        self.assertEqual(runtime_paths.backup_dir, r"C:\Users\tester\AppData\Local\NaverNewsScraperPro\backups")

    def test_migrate_legacy_runtime_files_uses_sqlite_safe_copy_and_rebases_pending_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy_dir = root / "legacy"
            data_dir = root / "runtime"
            legacy_dir.mkdir(parents=True)

            self._create_sqlite_db(legacy_dir / "news_database.db", value=7)
            (legacy_dir / "news_scraper_config.json").write_text('{"app_settings": {"theme_index": 1}}', encoding="utf-8")
            (legacy_dir / "news_scraper.log").write_text("legacy-log", encoding="utf-8")
            (legacy_dir / "keyword_groups.json").write_text('{"AI": ["OpenAI"]}', encoding="utf-8")
            (legacy_dir / "pending_restore.json").write_text(
                json.dumps(
                    {
                        "backup_name": "backup_2",
                        "backup_dir": str(legacy_dir / "backups"),
                        "restore_db": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            legacy_backup_root = legacy_dir / "backups"
            (legacy_backup_root / "backup_1").mkdir(parents=True)
            (legacy_backup_root / "backup_1" / "backup_info.json").write_text('{"timestamp": "1"}', encoding="utf-8")
            (legacy_backup_root / "backup_2").mkdir(parents=True)
            (legacy_backup_root / "backup_2" / "backup_info.json").write_text('{"timestamp": "2"}', encoding="utf-8")

            (data_dir / "backups" / "backup_1").mkdir(parents=True)
            (data_dir / "backups" / "backup_1" / "backup_info.json").write_text('{"timestamp": "existing"}', encoding="utf-8")

            migrated = migrate_legacy_runtime_files(str(legacy_dir), str(data_dir))

            self.assertIn(str(data_dir / "news_scraper_config.json"), migrated)
            self.assertIn(str(data_dir / "news_database.db"), migrated)
            self.assertIn(str(data_dir / "pending_restore.json"), migrated)
            self.assertIn(str(data_dir / "backups"), migrated)
            self.assertTrue((data_dir / "news_scraper.log").exists())
            self.assertTrue((data_dir / "keyword_groups.json").exists())
            self.assertTrue((data_dir / "backups" / "backup_1" / "backup_info.json").exists())
            self.assertTrue((data_dir / "backups" / "backup_2" / "backup_info.json").exists())
            self.assertEqual(
                (data_dir / "backups" / "backup_1" / "backup_info.json").read_text(encoding="utf-8"),
                '{"timestamp": "existing"}',
            )

            pending_payload = json.loads((data_dir / "pending_restore.json").read_text(encoding="utf-8"))
            self.assertEqual(pending_payload["backup_dir"], str(data_dir / "backups"))

            conn = sqlite3.connect(str(data_dir / "news_database.db"))
            try:
                row = conn.execute("SELECT value FROM sample").fetchone()
            finally:
                conn.close()
            self.assertEqual(int(row[0]), 7)
            self.assertTrue((legacy_dir / "news_database.db").exists())

    def test_migrate_legacy_runtime_files_drops_invalid_db_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy_dir = root / "legacy"
            data_dir = root / "runtime"
            legacy_dir.mkdir(parents=True)

            (legacy_dir / "news_database.db").write_text("not-a-sqlite-db", encoding="utf-8")
            migrated = migrate_legacy_runtime_files(str(legacy_dir), str(data_dir))

            self.assertNotIn(str(data_dir / "news_database.db"), migrated)
            self.assertFalse((data_dir / "news_database.db").exists())


if __name__ == "__main__":
    unittest.main()
