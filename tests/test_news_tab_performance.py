import os
import unittest
from unittest import mock
from typing import Any, cast

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from ui.news_tab import NewsTab


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeDb:
    def fetch_news(self, **kwargs):
        return []


class TestNewsTabPerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _drain_events(self):
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()

    def _make_tab(self) -> NewsTab:
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab = NewsTab("AI -coin", cast(Any, _FakeDb()), theme_mode=0)
        self.addCleanup(tab.cleanup)
        self.addCleanup(tab.deleteLater)
        return tab

    def test_constructor_can_defer_initial_db_load(self):
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True) as load_mock:
            tab = NewsTab("AI", cast(Any, _FakeDb()), theme_mode=0, defer_initial_load=True)
        self.addCleanup(tab.cleanup)
        self.addCleanup(tab.deleteLater)

        load_mock.assert_not_called()
        self.assertTrue(tab.needs_initial_hydration())
        self.assertIn("로딩 대기", tab.lbl_status.text())

    def _seed_rows(self, tab: NewsTab, rows):
        tab.news_data_cache = [tab._prepare_item(dict(row)) for row in rows]
        tab.filtered_data_cache = list(tab.news_data_cache)
        tab._loaded_offset = len(tab.news_data_cache)
        tab._total_filtered_count = len(tab.filtered_data_cache)
        tab._rebuild_item_indexes()
        tab._recount_unread_cache()

    def test_link_indexes_stay_correct_across_local_change_append_and_reload(self):
        tab = self._make_tab()
        first = {
            "title": "one",
            "description": "desc-one",
            "link": "https://example.com/1",
            "pubDate": "2026-01-01T09:00:00",
            "publisher": "example.com",
            "is_read": 0,
            "is_bookmarked": 0,
            "is_duplicate": 0,
            "notes": "",
        }
        self._seed_rows(tab, [first])

        with mock.patch.object(tab, "_schedule_render"):
            self.assertTrue(tab.apply_external_item_state(first["link"], is_read=True, is_bookmarked=True, notes="memo"))

        target = tab._target_by_link(first["link"])
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["is_read"], 1)
        self.assertEqual(target["is_bookmarked"], 1)
        self.assertEqual(target["notes"], "memo")

        scope = tab._scope_signature(tab._build_query_scope())
        second = {
            "title": "two",
            "description": "desc-two",
            "link": "https://example.com/2",
            "pubDate": "2026-01-02T09:00:00",
            "publisher": "example.com",
            "is_read": 0,
            "is_bookmarked": 0,
            "is_duplicate": 0,
            "notes": "",
        }

        tab._load_request_id = 1
        tab._pending_append_request_ids.add(1)
        tab._request_scope_signatures[1] = scope
        tab._last_loaded_scope_signature = scope
        with mock.patch.object(tab, "_schedule_render"):
            tab.on_data_loaded([second], total_count=2, request_id=1)

        self.assertIsNotNone(tab._target_by_link(second["link"]))

        replacement = {
            "title": "replacement",
            "description": "desc-replacement",
            "link": "https://example.com/3",
            "pubDate": "2026-01-03T09:00:00",
            "publisher": "example.com",
            "is_read": 0,
            "is_bookmarked": 0,
            "is_duplicate": 0,
            "notes": "",
        }
        tab._load_request_id = 2
        tab._request_scope_signatures[2] = scope
        with mock.patch.object(tab, "_schedule_render"):
            tab.on_data_loaded([replacement], total_count=1, request_id=2)

        self.assertIsNone(tab._target_by_link(first["link"]))
        self.assertIsNone(tab._target_by_link(second["link"]))
        self.assertIsNotNone(tab._target_by_link(replacement["link"]))

        with mock.patch.object(tab, "load_data_from_db"):
            self.assertTrue(tab.apply_external_item_state(replacement["link"], deleted=True))
        self.assertIsNone(tab._target_by_link(replacement["link"]))

    def test_render_html_coalesces_multiple_requests_into_single_flush(self):
        tab = self._make_tab()
        self._seed_rows(
            tab,
            [
                {
                    "title": "one",
                    "description": "desc-one",
                    "link": "https://example.com/1",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                    "is_read": 0,
                    "is_bookmarked": 0,
                    "is_duplicate": 0,
                    "notes": "",
                }
            ],
        )

        with mock.patch.object(tab.browser, "setHtml") as set_html:
            tab.render_html()
            tab.render_html()
            tab._refresh_after_local_change()
            self._drain_events()

        self.assertEqual(set_html.call_count, 1)

    def test_render_append_reuses_existing_body_when_scope_is_unchanged(self):
        tab = self._make_tab()
        first = {
            "title": "one",
            "description": "desc-one",
            "link": "https://example.com/1",
            "pubDate": "2026-01-01T09:00:00",
            "publisher": "example.com",
            "is_read": 0,
            "is_bookmarked": 0,
            "is_duplicate": 0,
            "notes": "",
        }
        second = {
            "title": "two",
            "description": "desc-two",
            "link": "https://example.com/2",
            "pubDate": "2026-01-02T09:00:00",
            "publisher": "example.com",
            "is_read": 0,
            "is_bookmarked": 0,
            "is_duplicate": 0,
            "notes": "",
        }
        self._seed_rows(tab, [first])

        with mock.patch.object(tab.browser, "setHtml"):
            tab.render_html()
            self._drain_events()

        initial_body = tab._rendered_body_html
        scope = tab._scope_signature(tab._build_query_scope())
        tab._load_request_id = 5
        tab._pending_append_request_ids.add(5)
        tab._request_scope_signatures[5] = scope
        tab._last_loaded_scope_signature = scope
        tab.on_data_loaded([second], total_count=2, request_id=5)
        self._drain_events()

        self.assertIn("desc-one", initial_body)
        self.assertIn("desc-two", tab._rendered_body_html)
        self.assertTrue(tab._rendered_body_html.startswith(initial_body))


if __name__ == "__main__":
    unittest.main()
