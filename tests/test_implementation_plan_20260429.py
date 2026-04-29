import inspect
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from core.content_filters import normalize_publisher_filter_lists
from core.database import DatabaseManager
from core.query_parser import build_fetch_key
from core.workers import DBQueryScope
from ui.main_window import MainApp
from ui.news_tab import NewsTab


def _item(index: int, publisher: str = "example.com") -> dict:
    return {
        "title": f"title {index}",
        "description": f"description {index}",
        "link": f"https://example.com/{index}",
        "pubDate": f"2026-04-{index:02d}T09:00:00",
        "publisher": publisher,
    }


class TestImplementationPlanDb(unittest.TestCase):
    def test_query_key_lookup_ignores_representative_keyword_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.sqlite"), max_connections=2)
            try:
                query_key = build_fetch_key("AI", [])
                db.upsert_news([_item(1)], "AI", query_key=query_key)

                rows = db.fetch_news("ai", query_key=query_key)
                self.assertEqual([row["link"] for row in rows], ["https://example.com/1"])
                self.assertEqual(db.count_news("ai", query_key=query_key), 1)
                self.assertEqual(db.get_unread_count("ai", query_key=query_key), 1)
                self.assertEqual(
                    db.get_existing_links_for_query(
                        ["https://example.com/1"],
                        keyword="ai",
                        query_key=query_key,
                    ),
                    {"https://example.com/1"},
                )
                self.assertEqual(db.mark_query_as_read("ai", query_key=query_key), 1)
                self.assertEqual(db.get_unread_count("AI", query_key=query_key), 0)
            finally:
                db.close()

    def test_publisher_visibility_uses_domain_suffix_not_plain_substring(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.sqlite"), max_connections=2)
            try:
                db.upsert_news(
                    [
                        _item(1, "example.com"),
                        _item(2, "news.example.com"),
                        _item(3, "badexample.com"),
                    ],
                    "AI",
                )

                blocked_links = {
                    row["link"]
                    for row in db.fetch_news("AI", blocked_publishers=["example.com"])
                }
                preferred_links = {
                    row["link"]
                    for row in db.fetch_news(
                        "AI",
                        preferred_publishers=["example.com"],
                        only_preferred_publishers=True,
                    )
                }

                self.assertEqual(blocked_links, {"https://example.com/3"})
                self.assertEqual(
                    preferred_links,
                    {"https://example.com/1", "https://example.com/2"},
                )
            finally:
                db.close()

    def test_visibility_aware_total_unread_and_statistics_exclude_blocked_publishers(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.sqlite"), max_connections=2)
            try:
                db.upsert_news(
                    [
                        _item(1, "visible.com"),
                        _item(2, "blocked.com"),
                        _item(3, "news.blocked.com"),
                    ],
                    "AI",
                )
                db.set_tags("https://example.com/1", ["visible"])
                db.set_tags("https://example.com/2", ["blocked"])

                self.assertEqual(db.get_total_unread_count(blocked_publishers=["blocked.com"]), 1)
                stats = db.get_statistics(blocked_publishers=["blocked.com"])
                self.assertEqual(stats["total"], 1)
                self.assertEqual(stats["unread"], 1)
                self.assertEqual(stats["with_tags"], 1)
            finally:
                db.close()


class _FakeFilterInput:
    def __init__(self):
        self.object_name = ""

    def setObjectName(self, name):
        self.object_name = str(name)

    def style(self):
        return None

    def setStyle(self, _style):
        return None


class _DummyFilterTab:
    PAGE_SIZE = 50

    def __init__(self):
        self.keyword = "AI"
        self.news_data_cache = []
        self._loaded_offset = 1
        self._last_loaded_scope_signature = ("old",)
        self._last_filter_text = ""
        self.inp_filter = _FakeFilterInput()
        self.reload_calls = []
        self.status_updates = 0

    def _current_filter_text(self):
        return ""

    def _build_query_scope(self):
        return DBQueryScope(keyword="AI", tag_filter="important")

    def _scope_signature(self, _scope):
        return ("new",)

    def update_status_label(self):
        self.status_updates += 1

    def _request_db_reload(self, reason, append=False):
        self.reload_calls.append((reason, append))


class TestImplementationPlanUiGuards(unittest.TestCase):
    def test_pending_restore_runs_after_single_instance_guard_before_main_window(self):
        src = Path("core/bootstrap.py").read_text(encoding="utf-8")
        single_guard_idx = src.index("if not instance_lock.tryLock(0):")
        restore_idx = src.index("if apply_pending_restore_if_any(")
        main_window_idx = src.index("window = MainApp(runtime_paths=RUNTIME_PATHS)")
        self.assertLess(single_guard_idx, restore_idx)
        self.assertLess(restore_idx, main_window_idx)

    def test_tag_filter_scope_change_triggers_reload_even_when_text_is_unchanged(self):
        dummy = _DummyFilterTab()

        NewsTab.apply_filter(cast(Any, dummy))

        self.assertEqual(dummy.reload_calls, [("필터 변경", False)])
        self.assertEqual(dummy.status_updates, 0)

    def test_publisher_filter_conflict_helper_supports_preferred_add_policy(self):
        blocked, preferred = normalize_publisher_filter_lists(
            ["Example.com"],
            ["example.COM", "good.com"],
        )
        self.assertEqual(blocked, ["Example.com"])
        self.assertEqual(preferred, ["good.com"])

        blocked, preferred = normalize_publisher_filter_lists(
            ["Example.com"],
            ["example.COM", "good.com"],
            preferred_wins=True,
        )
        self.assertEqual(blocked, [])
        self.assertEqual(preferred, ["example.COM", "good.com"])

    def test_saved_search_ui_supports_delete_and_keyword_target_application(self):
        setup_src = inspect.getsource(NewsTab.setup_ui)
        apply_src = inspect.getsource(NewsTab._apply_saved_search)
        self.assertIn("btn_delete_search", setup_src)
        self.assertIn("open_saved_search_target_tab", apply_src)
        self.assertIn("def delete_saved_search", inspect.getsource(MainApp.delete_saved_search))
        self.assertIn(
            "def open_saved_search_target_tab",
            inspect.getsource(MainApp.open_saved_search_target_tab),
        )


if __name__ == "__main__":
    unittest.main()
