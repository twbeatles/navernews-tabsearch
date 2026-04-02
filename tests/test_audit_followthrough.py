# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QTimer

from core.workers import DBQueryScope
from ui._main_window_settings_io import _MainWindowSettingsIOMixin
from ui._main_window_settings_io import export_scope_to_csv
from ui._main_window_tabs import _MainWindowTabsMixin
from ui.main_window import MainApp


class _DummyHistoryMain:
    _canonical_fetch_key_for_keyword = _MainWindowTabsMixin._canonical_fetch_key_for_keyword
    _history_identity_for_keyword = _MainWindowTabsMixin._history_identity_for_keyword
    _remember_search_history = _MainWindowTabsMixin._remember_search_history
    _merge_search_history = _MainWindowSettingsIOMixin._merge_search_history

    def __init__(self, search_history):
        self.search_history = list(search_history)


class _DummyTabs:
    def __init__(self):
        self.current_index = None

    def setCurrentIndex(self, index):
        self.current_index = index


class _FakeOpenTab:
    def __init__(self, keyword):
        self.keyword = keyword


class _DummyAddMain:
    add_news_tab = _MainWindowTabsMixin.add_news_tab
    _normalize_tab_keyword = _MainWindowTabsMixin._normalize_tab_keyword
    _canonical_fetch_key_for_keyword = _MainWindowTabsMixin._canonical_fetch_key_for_keyword
    _find_news_tab_by_fetch_key = _MainWindowTabsMixin._find_news_tab_by_fetch_key

    def __init__(self):
        self.tabs = _DummyTabs()
        self.theme_idx = 0
        self._fetch_cursor_by_key = {}
        self._fetch_total_by_key = {}
        self._tab_fetch_state = {}
        self._open_tabs = [_FakeOpenTab("북마크"), _FakeOpenTab("foo bar")]

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._open_tabs[start_index:], start_index):
            yield index, tab


class _DummyExportTab:
    def __init__(self, keyword, news_items, visible_items, all_filtered_items=None):
        self.keyword = keyword
        self.news_data_cache = list(news_items)
        self.filtered_data_cache = list(visible_items)
        self._all_filtered_items = (
            list(all_filtered_items) if all_filtered_items is not None else list(visible_items)
        )

    def get_all_filtered_items(self):
        return list(self._all_filtered_items)

    def _build_query_scope(self):
        return DBQueryScope(keyword=self.keyword)


class _FakeExportDB:
    def __init__(self, items):
        self.items = list(items)

    def count_news(self, **_kwargs):
        return len(self.items)

    def fetch_news(self, limit=50, offset=0, **_kwargs):
        return list(self.items[offset : offset + limit])


class _ImmediateExportContext:
    def report(self, **_kwargs):
        return None

    def check_cancelled(self):
        return None


class _DummyExportMain:
    export_data = _MainWindowSettingsIOMixin.export_data

    def __init__(self, widget, db=None, dialog_adapter=None):
        self._widget = widget
        self._db = db
        self.toast_messages = []
        self._dialog_adapter = dialog_adapter or _FakeDialogAdapter()

    def _current_news_tab(self):
        return self._widget

    def show_success_toast(self, message):
        self.toast_messages.append(message)

    def _start_export_job(self, scope, keyword, output_path):
        result = export_scope_to_csv(
            _ImmediateExportContext(),
            self._db,
            scope,
            output_path,
            keyword,
            chunk_size=1,
        )
        self.show_success_toast(f"총 {result['count']}개 항목을 저장했습니다.")
        self._dialog_adapter.information(self, "완료", f"파일이 저장되었습니다:\n{result['path']}")


class _DummyCheck:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeSyncTab:
    def __init__(self, keyword, *, is_bookmark_tab=False, unread_checked=False, change_result=False):
        self.keyword = keyword
        self.is_bookmark_tab = is_bookmark_tab
        self.chk_unread = _DummyCheck(unread_checked)
        self.change_result = change_result
        self.sync_calls = []
        self.load_calls = 0

    def apply_external_item_state(self, link, **kwargs):
        self.sync_calls.append((link, kwargs))
        return self.change_result

    def load_data_from_db(self):
        self.load_calls += 1


class _DummySyncMain:
    sync_link_state_across_tabs = MainApp.sync_link_state_across_tabs

    def __init__(self, tabs):
        self._tabs = list(tabs)
        self.badge_refresh_delays = []
        self.tooltip_calls = 0

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._tabs[start_index:], start_index):
            yield index, tab

    def _schedule_badge_refresh(self, delay_ms=200):
        self.badge_refresh_delays.append(delay_ms)

    def update_tray_tooltip(self):
        self.tooltip_calls += 1


class _FakeDialogAdapter:
    def __init__(
        self,
        *,
        save_result=("", ""),
        open_result=("", ""),
        ask_yes_no_result=False,
        corrupt_action="ignore",
    ):
        self.save_result = save_result
        self.open_result = open_result
        self.ask_yes_no_result = ask_yes_no_result
        self.corrupt_action = corrupt_action
        self.save_calls = []
        self.open_calls = []
        self.info_calls = []
        self.warning_calls = []
        self.critical_calls = []
        self.question_calls = []

    def get_save_file_name(self, parent, title, default_name, filters):
        self.save_calls.append((parent, title, default_name, filters))
        return self.save_result

    def get_open_file_name(self, parent, title, directory, filters):
        self.open_calls.append((parent, title, directory, filters))
        return self.open_result

    def information(self, parent, title, message):
        self.info_calls.append((parent, title, message))

    def warning(self, parent, title, message):
        self.warning_calls.append((parent, title, message))

    def critical(self, parent, title, message):
        self.critical_calls.append((parent, title, message))

    def ask_yes_no(self, parent, title, message, default=None):
        self.question_calls.append((parent, title, message, default))
        return self.ask_yes_no_result

    def ask_corrupt_backup_action(self, parent, backup_name, corrupt_error):
        return self.corrupt_action


class TestCanonicalHistory(unittest.TestCase):
    def test_remember_search_history_dedupes_by_canonical_query(self):
        dummy = _DummyHistoryMain(["foo bar", "baz"])

        dummy._remember_search_history("FOO   bar")

        self.assertEqual(dummy.search_history, ["FOO   bar", "baz"])

    def test_merge_search_history_prefers_first_canonical_entry(self):
        dummy = _DummyHistoryMain(["foo bar", "baz"])

        merged = dummy._merge_search_history(["FOO   bar", "qux"])

        self.assertEqual(merged, ["FOO   bar", "qux", "baz"])


class TestCanonicalTabDedupe(unittest.TestCase):
    def test_add_news_tab_focuses_existing_canonical_tab(self):
        dummy = _DummyAddMain()

        with mock.patch("ui._main_window_tabs.NewsTab", side_effect=AssertionError("should not create tab")):
            dummy.add_news_tab("FOO   BAR")

        self.assertEqual(dummy.tabs.current_index, 1)


class TestVisibleOnlyCsvExport(unittest.TestCase):
    def test_export_data_uses_full_filtered_scope_when_tab_supports_it(self):
        all_items = [
            {
                "title": "one",
                "link": "https://example.com/1",
                "pubDate": "2026-01-01",
                "publisher": "example.com",
                "description": "visible",
                "is_read": 0,
                "is_bookmarked": 0,
                "notes": "",
                "is_duplicate": 0,
            },
            {
                "title": "two",
                "link": "https://example.com/2",
                "pubDate": "2026-01-02",
                "publisher": "example.com",
                "description": "hidden",
                "is_read": 1,
                "is_bookmarked": 0,
                "notes": "",
                "is_duplicate": 0,
            },
        ]
        visible_items = [all_items[0]]
        dialogs = _FakeDialogAdapter()
        dummy = _DummyExportMain(
            _DummyExportTab("AI", all_items, visible_items, all_items),
            db=_FakeExportDB(all_items),
            dialog_adapter=dialogs,
        )

        with tempfile.TemporaryDirectory() as td:
            export_path = Path(td) / "export.csv"
            dialogs.save_result = (str(export_path), "CSV")
            dummy.export_data()

            rows = list(csv.reader(export_path.open("r", encoding="utf-8-sig")))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1][0], "one")
            self.assertEqual(rows[2][0], "two")
            self.assertEqual(dummy.toast_messages, ["총 2개 항목을 저장했습니다."])
            self.assertEqual(len(dialogs.info_calls), 1)

    def test_export_data_falls_back_to_loaded_slice_when_helper_missing(self):
        all_items = [
            {
                "title": "one",
                "link": "https://example.com/1",
                "pubDate": "2026-01-01",
                "publisher": "example.com",
                "description": "visible",
                "is_read": 0,
                "is_bookmarked": 0,
                "notes": "",
                "is_duplicate": 0,
            },
            {
                "title": "two",
                "link": "https://example.com/2",
                "pubDate": "2026-01-02",
                "publisher": "example.com",
                "description": "hidden",
                "is_read": 1,
                "is_bookmarked": 0,
                "notes": "",
                "is_duplicate": 0,
            },
        ]
        visible_items = [all_items[0]]

        class _LegacyTab:
            def __init__(self):
                self.keyword = "AI"
                self.news_data_cache = list(all_items)
                self.filtered_data_cache = list(visible_items)

        dialogs = _FakeDialogAdapter()
        dummy = _DummyExportMain(_LegacyTab(), dialog_adapter=dialogs)

        with tempfile.TemporaryDirectory() as td:
            export_path = Path(td) / "export.csv"
            dialogs.save_result = (str(export_path), "CSV")
            dummy.export_data()

            rows = list(csv.reader(export_path.open("r", encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][0], "one")
            self.assertEqual(dummy.toast_messages, ["총 1개 항목을 저장했습니다."])
            self.assertEqual(len(dialogs.info_calls), 1)

    def test_export_data_blocks_when_no_visible_items_exist(self):
        all_items = [
            {
                "title": "one",
                "link": "https://example.com/1",
                "pubDate": "2026-01-01",
                "publisher": "example.com",
                "description": "hidden",
                "is_read": 0,
                "is_bookmarked": 0,
                "notes": "",
                "is_duplicate": 0,
            }
        ]
        dialogs = _FakeDialogAdapter()
        dummy = _DummyExportMain(_DummyExportTab("AI", all_items, []), dialog_adapter=dialogs)

        dummy.export_data()

        self.assertEqual(dialogs.save_calls, [])
        self.assertEqual(len(dialogs.info_calls), 1)
        self.assertEqual(dummy.toast_messages, [])


class TestLinkStateSync(unittest.TestCase):
    def test_sync_link_state_reloads_bookmark_and_unread_only_tabs_when_needed(self):
        source_tab = _FakeSyncTab("AI", change_result=True)
        bookmark_tab = _FakeSyncTab("북마크", is_bookmark_tab=True)
        unread_tab = _FakeSyncTab("AI -광고", unread_checked=True)
        dummy = _DummySyncMain([source_tab, bookmark_tab, unread_tab])

        with mock.patch.object(QTimer, "singleShot", side_effect=lambda _ms, callback: callback()):
            dummy.sync_link_state_across_tabs(
                source_tab,
                "https://example.com/news",
                is_bookmarked=True,
                is_read=False,
            )

        self.assertEqual(bookmark_tab.load_calls, 1)
        self.assertEqual(unread_tab.load_calls, 1)
        self.assertEqual(dummy.badge_refresh_delays, [0])
        self.assertEqual(dummy.tooltip_calls, 2)
        self.assertEqual(bookmark_tab.sync_calls[0][0], "https://example.com/news")


if __name__ == "__main__":
    unittest.main()
