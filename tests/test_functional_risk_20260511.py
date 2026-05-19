import inspect
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, cast
from unittest import mock

from core.automation_rules import EXCLUDE_TAG, evaluate_automation_rules
from core.cloud_sync import (
    create_cloud_snapshot,
    run_cloud_sync_cycle,
    sanitize_config_for_cloud,
    select_cloud_snapshots_for_import,
)
from core.database import DatabaseManager
from core.workers import DBQueryScope
from ui._main_window_analysis import _MainWindowAnalysisMixin
from ui.dialogs import ArchiveSearchDialog, AutomationRulesDialog, PublisherAliasDialog
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


class _DummyAutomationMain(_MainWindowAnalysisMixin):
    def __init__(self, db: DatabaseManager, rules):
        self.db = db
        self.automation_rules = rules
        self.publisher_aliases = {}
        self.refresh_calls = []

    def _require_db(self):
        return self.db

    def _after_bulk_data_change(self, operation: str = "bulk_change") -> None:
        self.refresh_calls.append(operation)

    def apply_automation_rules_to_items(self, items, **kwargs):
        method = cast(Any, _MainWindowAnalysisMixin)._apply_automation_rules_to_items
        return method(self, items, **kwargs)


class _DummyScopeTab:
    def __init__(self, scope: DBQueryScope):
        self.scope = scope

    def _build_query_scope(self):
        return self.scope

    def get_all_filtered_items(self):
        raise AssertionError("current scope should use DB snapshot batches")


class _DummyScopeMain(_MainWindowAnalysisMixin):
    def __init__(self, db: DatabaseManager, tab: _DummyScopeTab):
        self.db = db
        self.tab = tab

    def _require_db(self):
        return self.db

    def _current_news_tab(self):
        return self.tab

    def current_scope_items(self, **kwargs):
        method = cast(Any, _MainWindowAnalysisMixin)._current_scope_items
        return method(self, **kwargs)


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
                self.assertFalse(bad_zip.exists())
                self.assertTrue((sync_dir / ".invalid").exists())
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

                exclude_actions = evaluate_automation_rules(
                    rows[0],
                    [{"name": "exclude", "keywords": ["AI"], "exclude": True}],
                    publisher_aliases={"naver:oid:001": "연합뉴스"},
                )
                self.assertTrue(exclude_actions.has_actions)
                self.assertIn(EXCLUDE_TAG, exclude_actions.add_tags)
                self.assertTrue(exclude_actions.mark_read)
                self.assertTrue(exclude_actions.suppress_notification)
            finally:
                db.close()

    def test_automation_exclude_updates_db_and_returns_suppressed_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = _db(root / "news.db")
            try:
                db.upsert_news([_item(1, title="AI launch")], "AI", query_key="ai|")
                rows = db.fetch_news("AI", query_key="ai|")
                dummy = _DummyAutomationMain(
                    db,
                    [{"name": "exclude", "keywords": ["AI"], "exclude": True}],
                )

                result = dummy.apply_automation_rules_to_items(rows, dry_run=False)

                self.assertEqual(result["matched"], 1)
                self.assertEqual(result["read"], 1)
                self.assertEqual(result["suppressed"], 1)
                self.assertEqual(result["suppressed_links"], ["https://example.com/1"])
                self.assertEqual(result["apply_result"]["read"], 1)
                updated = db.fetch_news("AI", query_key="ai|")[0]
                self.assertEqual(int(updated["is_read"]), 1)
                self.assertIn(EXCLUDE_TAG, db.get_tags("https://example.com/1"))
                self.assertEqual(dummy.refresh_calls, ["automation_rules"])
            finally:
                db.close()

    def test_automation_failure_preserves_evaluated_suppression_for_fetch_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = _db(root / "news.db")
            try:
                db.upsert_news([_item(1, title="AI launch")], "AI", query_key="ai|")
                rows = db.fetch_news("AI", query_key="ai|")
                dummy = _DummyAutomationMain(
                    db,
                    [{"name": "mute", "keywords": ["AI"], "suppress_notification": True, "mark_read": True}],
                )

                with mock.patch.object(db, "apply_automation_actions", side_effect=RuntimeError("locked")):
                    with self.assertRaises(RuntimeError):
                        dummy.apply_automation_rules_to_items(rows, dry_run=False)

                result = dummy._last_automation_rule_result
                self.assertTrue(result["apply_failed"])
                self.assertEqual(result["suppressed_links"], ["https://example.com/1"])
                updated = db.fetch_news("AI", query_key="ai|")[0]
                self.assertEqual(int(updated["is_read"]), 0)
                self.assertEqual(dummy.refresh_calls, [])
            finally:
                db.close()

    def test_automation_dry_run_counts_suppression_without_mutating_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = _db(root / "news.db")
            try:
                db.upsert_news([_item(1, title="AI launch")], "AI", query_key="ai|")
                rows = db.fetch_news("AI", query_key="ai|")
                dummy = _DummyAutomationMain(
                    db,
                    [{"name": "mute", "keywords": ["AI"], "suppress_notification": True}],
                )

                result = dummy.apply_automation_rules_to_items(rows, dry_run=True)

                self.assertEqual(result["matched"], 1)
                self.assertEqual(result["suppressed"], 1)
                self.assertEqual(result["suppressed_links"], ["https://example.com/1"])
                updated = db.fetch_news("AI", query_key="ai|")[0]
                self.assertEqual(int(updated["is_read"]), 0)
                self.assertEqual(db.get_tags("https://example.com/1"), [])
                self.assertEqual(dummy.refresh_calls, [])
            finally:
                db.close()

    def test_current_scope_items_reads_full_db_scope_not_loaded_slice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = _db(root / "news.db")
            try:
                rows = []
                tagged_links = []
                for idx in range(65):
                    publisher = "blocked.com" if idx >= 60 else "example.com"
                    link = f"https://example.com/scope-{idx}"
                    rows.append(
                        {
                            "title": f"AI scope article {idx}",
                            "description": "scope test",
                            "link": link,
                            "pubDate": "Mon, 01 Jan 2024 00:00:00 +0000",
                            "publisher": publisher,
                        }
                    )
                    if idx < 55:
                        tagged_links.append(link)
                db.upsert_news(rows, "AI", query_key="ai|")
                self.assertEqual(db.bulk_add_tag_to_links(tagged_links, "bulk"), 55)

                scope = DBQueryScope(
                    keyword="AI",
                    query_key="ai|",
                    filter_txt="scope",
                    tag_filter="bulk",
                    blocked_publishers=("blocked.com",),
                )
                dummy = _DummyScopeMain(db, _DummyScopeTab(scope))

                scoped_rows = dummy.current_scope_items(chunk_size=20)

                self.assertEqual(len(scoped_rows), 55)
                self.assertEqual({row["publisher"] for row in scoped_rows}, {"example.com"})
                self.assertTrue(all("scope" in row["title"] for row in scoped_rows))
            finally:
                db.close()

    def test_settings_dialog_cloud_actions_use_overrides_not_parent_mutation(self):
        export_src = inspect.getsource(SettingsDialog.cloud_sync_export_dialog)
        import_src = inspect.getsource(SettingsDialog.cloud_sync_import_dialog)
        self.assertIn("sync_dir_override", export_src)
        self.assertIn("sync_dir_override", import_src)
        self.assertNotIn("enabled_override", export_src)
        self.assertNotIn("enabled_override", import_src)
        self.assertNotIn("parent.cloud_sync_dir =", export_src)
        self.assertNotIn("parent.cloud_sync_dir =", import_src)

    def test_p1_dialog_contracts_keep_payload_actions_and_form_exports(self):
        archive_src = inspect.getsource(ArchiveSearchDialog)
        self.assertIn("Qt.ItemDataRole.UserRole", archive_src)
        self.assertIn("itemDoubleClicked", archive_src)
        self.assertIn("toggle_bookmark", archive_src)
        self.assertIn("edit_tags", archive_src)
        self.assertIn("include_deleted", archive_src)
        self.assertIn("restore_deleted_link", archive_src)

        automation_src = inspect.getsource(AutomationRulesDialog)
        self.assertIn("QFormLayout", automation_src)
        self.assertIn("suppress_notification", automation_src)
        self.assertIn("현재 탭 전체 적용", automation_src)

        alias_src = inspect.getsource(PublisherAliasDialog)
        self.assertIn("txt_source", alias_src)
        self.assertIn("txt_alias", alias_src)
        self.assertIn("JSON에서 목록으로 불러오기", alias_src)


if __name__ == "__main__":
    unittest.main()
