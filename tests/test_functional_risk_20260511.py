import inspect
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.automation_rules import evaluate_automation_rules
from core.cloud_sync import (
    create_cloud_snapshot,
    run_cloud_sync_cycle,
    sanitize_config_for_cloud,
    select_cloud_snapshots_for_import,
)
from core.database import DatabaseManager
from ui._main_window_settings_io import export_items_to_markdown
from ui.settings_dialog import SettingsDialog


def _item(idx: int, *, title: str = "", publisher: str = "example.com"):
    return {
        "title": title or f"Title {idx}",
        "description": f"Description {idx}",
        "link": f"https://example.com/{idx}",
        "pubDate": "Mon, 01 Jan 2024 00:00:00 +0000",
        "publisher": publisher,
    }


def _db(path: Path) -> DatabaseManager:
    return DatabaseManager(str(path), max_connections=2)


def _write_bad_schema_snapshot(path: Path, snapshot_id: str) -> None:
    db_path = path.with_suffix(".db")
    sqlite3.connect(str(db_path)).close()
    manifest = {
        "format": "navernews-tabsearch-cloud-snapshot",
        "format_version": "1.0",
        "snapshot_id": snapshot_id,
        "machine_id": "bad-machine",
        "created_at": "2026-05-11T00:00:00+00:00",
        "app_version": "test",
        "settings_file": "settings.json",
        "db_file": "news_database.db",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("settings.json", "{}")
        zf.write(db_path, "news_database.db")
    db_path.unlink()


class TestFunctionalRisk20260511(unittest.TestCase):
    def test_bulk_mark_read_updates_timestamp_and_cloud_merge_uses_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = _db(root / "source.db")
            target = _db(root / "target.db")
            try:
                source.upsert_news([_item(1)], "AI", query_key="ai|")
                target.upsert_news([_item(1)], "AI", query_key="ai|")
                updated = source.mark_query_as_read_chunked("AI", query_key="ai|", chunk_size=1)
                self.assertEqual(updated, 1)
                with source.connection() as conn:
                    row = conn.execute(
                        "SELECT is_read, read_updated_at FROM news WHERE link=?",
                        ("https://example.com/1",),
                    ).fetchone()
                self.assertEqual(int(row[0]), 1)
                self.assertGreater(float(row[1]), 0)

                result = target.merge_cloud_snapshot_db(
                    source.db_file,
                    snapshot_id="bulk-read",
                    source_machine_id="machine-a",
                    local_machine_id="machine-b",
                )
                self.assertTrue(result["merged"])
                merged = target.fetch_news("AI", query_key="ai|")[0]
                self.assertEqual(int(merged["is_read"]), 1)
            finally:
                source.close()
                target.close()

    def test_cloud_sync_continues_after_bad_snapshot_and_selects_oldest_unseen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sync_dir = root / "sync"
            sync_dir.mkdir()
            target = _db(root / "target.db")
            source = _db(root / "source.db")
            try:
                source.upsert_news([_item(2)], "AI", query_key="ai|")
                bad_zip = sync_dir / "news_scraper_sync_bad.zip"
                _write_bad_schema_snapshot(bad_zip, "bad")
                good = create_cloud_snapshot(
                    sync_dir=str(sync_dir),
                    config={"app_settings": {}, "tabs": ["AI"]},
                    db_file=source.db_file,
                    machine_id="machine-a",
                    app_version="test",
                )
                os.utime(bad_zip, (1_700_000_000, 1_700_000_000))
                os.utime(good.path, (1_700_000_100, 1_700_000_100))

                selection = select_cloud_snapshots_for_import(
                    db_manager=target,
                    sync_dir=str(sync_dir),
                    max_imports=1,
                )
                self.assertEqual(Path(selection["paths"][0]).name, bad_zip.name)

                result = run_cloud_sync_cycle(
                    db_manager=target,
                    sync_dir=str(sync_dir),
                    config={"app_settings": {}, "tabs": []},
                    db_file=target.db_file,
                    machine_id="machine-b",
                    app_version="test",
                    max_imports=20,
                )
                self.assertGreaterEqual(result["invalid_count"], 1)
                self.assertEqual(result["merged_count"], 1)
                self.assertEqual(
                    {row["link"] for row in target.fetch_news("AI", query_key="ai|")},
                    {"https://example.com/2"},
                )
            finally:
                source.close()
                target.close()

    def test_cloud_settings_sanitizes_private_rule_and_alias_payloads(self):
        sanitized = sanitize_config_for_cloud(
            {
                "app_settings": {"client_id": "cid", "theme_index": 1},
                "automation_rules": [{"name": "private"}],
                "publisher_aliases": {"raw": "alias"},
            }
        )
        self.assertNotIn("automation_rules", sanitized)
        self.assertNotIn("publisher_aliases", sanitized)
        self.assertNotIn("client_id", sanitized["app_settings"])
        self.assertEqual(sanitized["app_settings"]["theme_index"], 1)

    def test_tag_batch_archive_alias_markdown_and_automation_helpers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = _db(root / "news.db")
            try:
                db.upsert_news(
                    [_item(1, title="AI launch", publisher="naver:oid:001"), _item(2, title="Sports")],
                    "AI",
                    query_key="ai|",
                )
                self.assertTrue(db.set_tags("https://example.com/1", ["old"]))
                self.assertEqual(db.rename_tag("old", "important"), 1)
                self.assertEqual(db.bulk_add_tag_to_links(["https://example.com/1", "https://example.com/2"], "digest"), 2)
                self.assertEqual(db.get_tags("https://example.com/1"), ["digest", "important"])
                rows = db.search_archive(
                    publisher_filter="연합뉴스",
                    publisher_aliases={"naver:oid:001": "연합뉴스"},
                )
                self.assertEqual([row["link"] for row in rows], ["https://example.com/1"])

                out = root / "digest.md"
                export_items_to_markdown(
                    rows,
                    str(out),
                    "AI",
                    publisher_aliases={"naver:oid:001": "연합뉴스"},
                )
                text = out.read_text(encoding="utf-8")
                self.assertIn("# 뉴스 Digest - AI", text)
                self.assertIn("연합뉴스", text)

                actions = evaluate_automation_rules(
                    rows[0],
                    [{"name": "ai", "keywords": ["AI"], "add_tags": ["자동"], "mark_read": True}],
                    publisher_aliases={"naver:oid:001": "연합뉴스"},
                )
                self.assertTrue(actions.has_actions)
                self.assertEqual(actions.add_tags, ["자동"])
                self.assertTrue(actions.mark_read)
            finally:
                db.close()

    def test_settings_dialog_cloud_actions_use_overrides_not_parent_mutation(self):
        export_src = inspect.getsource(SettingsDialog.cloud_sync_export_dialog)
        import_src = inspect.getsource(SettingsDialog.cloud_sync_import_dialog)
        self.assertIn("sync_dir_override", export_src)
        self.assertIn("sync_dir_override", import_src)
        self.assertNotIn("parent.cloud_sync_dir =", export_src)
        self.assertNotIn("parent.cloud_sync_dir =", import_src)


if __name__ == "__main__":
    unittest.main()
