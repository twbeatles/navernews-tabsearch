import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QUrl

from ui.news_tab import NewsTab


class _DummyDB:
    def __init__(self, update_result=True):
        self.calls = []
        self.update_result = update_result

    def update_status(self, link, field, value):
        self.calls.append((link, field, value))
        return self.update_result


class _DummyLabel:
    def __init__(self):
        self.last_text = ""

    def setText(self, text):
        self.last_text = text


class _DummyWindow:
    def __init__(self):
        self.warning_calls = []
        self.toast_calls = []

    def show_warning_toast(self, message):
        self.warning_calls.append(message)

    def show_toast(self, message):
        self.toast_calls.append(message)


class _DummyNewsTab:
    _set_read_state = NewsTab._set_read_state

    def __init__(self, update_result=True):
        self.db = _DummyDB(update_result=update_result)
        self.adjust_calls = 0
        self.refresh_calls = 0
        self.badge_calls = 0
        self.lbl_status = _DummyLabel()
        self._window = _DummyWindow()
        self.target = {"link": "https://example.com/news-1", "is_read": 0}

    def _adjust_unread_cache(self, _was_read, _now_read):
        self.adjust_calls += 1

    def _refresh_after_local_change(self, requires_refilter=False):
        self.refresh_calls += 1

    def _notify_badge_change(self):
        self.badge_calls += 1

    def _target_by_hash(self, _link_hash):
        return self.target

    def window(self):
        return self._window


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

    def test_open_action_does_not_mutate_ui_when_db_update_fails(self):
        tab = _DummyNewsTab(update_result=False)
        tab.target = {"link": "https://example.com/news-open", "is_read": 0, "is_bookmarked": 0}

        with mock.patch("ui.news_tab.QDesktopServices.openUrl") as open_mock:
            NewsTab.on_link_clicked(tab, QUrl("app://open/hash"))

        open_mock.assert_called_once()
        self.assertEqual(tab.target["is_read"], 0)
        self.assertEqual(tab.adjust_calls, 0)
        self.assertEqual(tab.refresh_calls, 0)
        self.assertEqual(tab.badge_calls, 0)
        self.assertTrue(tab._window.warning_calls)

    def test_unread_action_does_not_mutate_ui_when_db_update_fails(self):
        tab = _DummyNewsTab(update_result=False)
        tab.target = {"link": "https://example.com/news-unread", "is_read": 1, "is_bookmarked": 0}

        NewsTab.on_link_clicked(tab, QUrl("app://unread/hash"))

        self.assertEqual(tab.target["is_read"], 1)
        self.assertEqual(tab.adjust_calls, 0)
        self.assertEqual(tab.refresh_calls, 0)
        self.assertEqual(tab.badge_calls, 0)
        self.assertTrue(tab._window.warning_calls)
        self.assertEqual(tab._window.toast_calls, [])

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
