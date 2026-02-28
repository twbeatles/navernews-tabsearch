import unittest
from pathlib import Path
from unittest import mock

from ui.news_tab import NewsTab


class _DummyDB:
    def __init__(self):
        self.calls = []

    def update_status(self, link, field, value):
        self.calls.append((link, field, value))
        return True


class _DummyNewsTab:
    def __init__(self):
        self.db = _DummyDB()
        self.adjust_calls = 0
        self.refresh_calls = 0
        self.badge_calls = 0

    def _adjust_unread_cache(self, _was_read, _now_read):
        self.adjust_calls += 1

    def _refresh_after_local_change(self, requires_refilter=False):
        self.refresh_calls += 1

    def _notify_badge_change(self):
        self.badge_calls += 1


class TestNewsTabExtReadPolicy(unittest.TestCase):
    def test_ext_helper_marks_unread_item_as_read(self):
        tab = _DummyNewsTab()
        target = {"link": "https://example.com/news-1", "is_read": 0}

        with mock.patch("ui.news_tab.QDesktopServices.openUrl") as open_mock:
            NewsTab._open_external_link_and_mark_read(tab, target)

        open_mock.assert_called_once()
        self.assertEqual(tab.db.calls, [("https://example.com/news-1", "is_read", 1)])
        self.assertEqual(target["is_read"], 1)
        self.assertEqual(tab.adjust_calls, 1)
        self.assertEqual(tab.refresh_calls, 1)
        self.assertEqual(tab.badge_calls, 1)

    def test_ext_helper_keeps_read_item_without_duplicate_updates(self):
        tab = _DummyNewsTab()
        target = {"link": "https://example.com/news-2", "is_read": 1}

        with mock.patch("ui.news_tab.QDesktopServices.openUrl") as open_mock:
            NewsTab._open_external_link_and_mark_read(tab, target)

        open_mock.assert_called_once()
        self.assertEqual(tab.db.calls, [])
        self.assertEqual(tab.adjust_calls, 0)
        self.assertEqual(tab.refresh_calls, 0)
        self.assertEqual(tab.badge_calls, 0)

    def test_ext_paths_use_shared_helper(self):
        src = Path("ui/news_tab.py").read_text(encoding="utf-8")

        start = src.index("def on_link_clicked")
        end = src.index("def mark_all_read")
        link_block = src[start:end]
        self.assertIn("elif action == \"ext\":", link_block)
        self.assertIn("self._open_external_link_and_mark_read(target)", link_block)

        start = src.index("def on_browser_action")
        end = src.index("def cleanup")
        browser_block = src[start:end]
        self.assertIn("if action == \"ext\":", browser_block)
        self.assertIn("self._open_external_link_and_mark_read(target)", browser_block)
