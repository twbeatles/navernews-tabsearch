import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.cloud_sync import (
    CloudSyncError,
    cloud_sync_path_conflicts_with_runtime,
    create_cloud_snapshot,
    import_cloud_snapshot,
    read_snapshot_manifest,
)
from core.constants import get_runtime_paths
from core.database import DatabaseManager, DatabaseWriteError


def _item(idx: int, title: str = ""):
    return {
        "title": title or f"Title {idx}",
        "description": f"Description {idx}",
        "link": f"https://example.com/{idx}",
        "pubDate": "Mon, 01 Jan 2024 00:00:00 +0000",
        "publisher": "example.com",
    }


class TestCloudSync(unittest.TestCase):
    def _db(self, path: Path) -> DatabaseManager:
        return DatabaseManager(str(path), max_connections=2)

    def test_snapshot_excludes_api_secrets_and_sqlite_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sync_dir = root / "sync"
            sync_dir.mkdir()
            db_path = root / "news.db"
            db = self._db(db_path)
            try:
                db.upsert_news([_item(1)], "AI", query_key="ai|")

                snapshot = create_cloud_snapshot(
                    sync_dir=str(sync_dir),
                    config={
                        "app_settings": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "client_secret_enc": "enc",
                            "client_secret_storage": "dpapi",
                            "cloud_sync_dir": str(sync_dir),
                            "theme_index": 1,
                        },
                        "tabs": ["AI"],
                    },
                    db_file=str(db_path),
                    machine_id="machine-a",
                    app_version="test",
                )

                with zipfile.ZipFile(snapshot.path, "r") as zf:
                    names = set(zf.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("settings.json", names)
                    self.assertIn("news_database.db", names)
                    self.assertNotIn("news_database.db-wal", names)
                    self.assertNotIn("news_database.db-shm", names)
                    settings = json.loads(zf.read("settings.json").decode("utf-8"))

                app_settings = settings["app_settings"]
                self.assertNotIn("client_id", app_settings)
                self.assertNotIn("client_secret", app_settings)
                self.assertNotIn("client_secret_enc", app_settings)
                self.assertNotIn("client_secret_storage", app_settings)
                self.assertNotIn("cloud_sync_dir", app_settings)
                self.assertEqual(app_settings["theme_index"], 1)
            finally:
                db.close()

    def test_corrupt_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            bad_zip = Path(td) / "news_scraper_sync_bad.zip"
            bad_zip.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(CloudSyncError):
                read_snapshot_manifest(str(bad_zip))

    def test_same_machine_and_seen_snapshots_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sync_dir = root / "sync"
            sync_dir.mkdir()
            source_db = self._db(root / "source.db")
            target_db = self._db(root / "target.db")
            try:
                source_db.upsert_news([_item(1)], "AI", query_key="ai|")
                snapshot = create_cloud_snapshot(
                    sync_dir=str(sync_dir),
                    config={"app_settings": {}, "tabs": ["AI"]},
                    db_file=source_db.db_file,
                    machine_id="machine-a",
                    app_version="test",
                )

                same_machine = import_cloud_snapshot(
                    db_manager=target_db,
                    zip_path=snapshot.path,
                    local_machine_id="machine-a",
                )
                self.assertTrue(same_machine["skipped"])
                self.assertEqual(same_machine["reason"], "same_machine")

                already_seen = import_cloud_snapshot(
                    db_manager=target_db,
                    zip_path=snapshot.path,
                    local_machine_id="machine-b",
                )
                self.assertTrue(already_seen["skipped"])
                self.assertEqual(already_seen["reason"], "already_seen")
            finally:
                source_db.close()
                target_db.close()

    def test_merge_unions_articles_scopes_tags_and_uses_latest_field_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._db(root / "source.db")
            target = self._db(root / "target.db")
            try:
                source.upsert_news([_item(1), _item(2, "Shared")], "AI", query_key="ai|")
                target.upsert_news([_item(2, "Shared"), _item(3)], "ECON", query_key="econ|")

                source.update_status("https://example.com/2", "is_read", 1)
                source.update_status("https://example.com/2", "is_bookmarked", 0)
                source.save_note("https://example.com/2", "source note")
                source.set_tags("https://example.com/2", ["source"])

                target.update_status("https://example.com/2", "is_read", 0)
                target.update_status("https://example.com/2", "is_bookmarked", 1)
                target.save_note("https://example.com/2", "target note")
                target.set_tags("https://example.com/2", ["target"])

                with source.connection() as conn:
                    conn.execute(
                        """
                        UPDATE news
                        SET read_updated_at=300, bookmark_updated_at=200, notes_updated_at=100
                        WHERE link='https://example.com/2'
                        """
                    )
                    conn.execute(
                        "UPDATE news_tag_state SET tags_updated_at=400 WHERE link='https://example.com/2'"
                    )
                    conn.commit()
                with target.connection() as conn:
                    conn.execute(
                        """
                        UPDATE news
                        SET read_updated_at=100, bookmark_updated_at=500, notes_updated_at=200
                        WHERE link='https://example.com/2'
                        """
                    )
                    conn.execute(
                        "UPDATE news_tag_state SET tags_updated_at=100 WHERE link='https://example.com/2'"
                    )
                    conn.commit()

                result = target.merge_cloud_snapshot_db(
                    source.db_file,
                    snapshot_id="snapshot-1",
                    source_machine_id="machine-a",
                    local_machine_id="machine-b",
                )

                self.assertTrue(result["merged"])
                self.assertEqual(result["news_added"], 1)
                ai_rows = target.fetch_news("AI", query_key="ai|")
                self.assertEqual({row["link"] for row in ai_rows}, {"https://example.com/1", "https://example.com/2"})
                econ_rows = target.fetch_news("ECON", query_key="econ|")
                self.assertEqual({row["link"] for row in econ_rows}, {"https://example.com/2", "https://example.com/3"})

                shared = next(row for row in target.fetch_news("AI", query_key="ai|") if row["link"].endswith("/2"))
                self.assertEqual(int(shared["is_read"]), 1)
                self.assertEqual(int(shared["is_bookmarked"]), 1)
                self.assertEqual(shared["notes"], "target note")
                self.assertEqual(target.get_tags("https://example.com/2"), ["source"])
            finally:
                source.close()
                target.close()

    def test_merge_failure_rolls_back_local_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = self._db(root / "target.db")
            bad_source = root / "bad.db"
            try:
                target.upsert_news([_item(1)], "AI", query_key="ai|")
                sqlite3.connect(str(bad_source)).close()

                with self.assertRaises(DatabaseWriteError):
                    target.merge_cloud_snapshot_db(str(bad_source), snapshot_id="bad")

                self.assertEqual(target.get_counts("AI", query_key="ai|"), 1)
            finally:
                target.close()

    def test_cloud_sync_folder_cannot_overlap_runtime_data(self):
        runtime_paths = get_runtime_paths(data_dir=r"C:\Users\tester\AppData\Local\NaverNewsScraperPro")
        self.assertTrue(
            cloud_sync_path_conflicts_with_runtime(
                r"C:\Users\tester\AppData\Local",
                runtime_paths,
            )
        )
        self.assertFalse(
            cloud_sync_path_conflicts_with_runtime(
                r"D:\OneDrive\NewsSnapshots",
                runtime_paths,
            )
        )


if __name__ == "__main__":
    unittest.main()
