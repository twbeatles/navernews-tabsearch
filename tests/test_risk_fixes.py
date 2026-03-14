import inspect
import unittest
from pathlib import Path

from core.query_parser import has_positive_keyword
from ui.main_window import MainApp


class TestKeywordValidation(unittest.TestCase):
    def test_has_positive_keyword(self):
        self.assertTrue(has_positive_keyword("AI -광고"))
        self.assertTrue(has_positive_keyword("경제"))
        self.assertFalse(has_positive_keyword("-광고 -코인"))
        self.assertFalse(has_positive_keyword(""))


class TestMainWindowRiskFixes(unittest.TestCase):
    def _read(self) -> str:
        return Path("ui/main_window.py").read_text(encoding="utf-8")

    def test_safe_refresh_all_recovers_lock_when_not_started(self):
        block = inspect.getsource(MainApp._safe_refresh_all)
        self.assertIn("started = False", block)
        self.assertIn("started = self.refresh_all()", block)
        self.assertIn("if not started:", block)
        self.assertIn("self._refresh_in_progress = False", block)

    def test_refresh_all_returns_bool_contract(self):
        block = inspect.getsource(MainApp.refresh_all)
        self.assertIn("def refresh_all(", block)
        self.assertIn("-> bool", block)
        self.assertIn("return True", block)
        self.assertIn("return False", block)

    def test_add_news_tab_load_more_uses_live_tab_keyword(self):
        block = inspect.getsource(MainApp.add_news_tab)
        self.assertIn("lambda _checked=False, tab_ref=tab: self.fetch_news(tab_ref.keyword, is_more=True)", block)
        self.assertNotIn("self.fetch_news(keyword, is_more=True)", block)

    def test_fetch_tracks_tab_pagination_state(self):
        src = Path("ui/main_window.py").read_text(encoding="utf-8")
        fetch_src = inspect.getsource(MainApp.fetch_news)
        self.assertIn("class TabFetchState", src)
        self.assertIn("self._tab_fetch_state", src)
        self.assertIn("self._request_start_index", src)
        self.assertIn("fetch_state.last_api_start_index + 100", fetch_src)

    def test_minimize_to_tray_is_handled_in_change_event(self):
        block = inspect.getsource(MainApp.changeEvent)
        self.assertIn("QEvent.Type.WindowStateChange", block)
        self.assertIn("self.minimize_to_tray", block)
        self.assertIn("QTimer.singleShot(0, self.hide)", block)

    def test_show_window_restores_hidden_or_minimized_window(self):
        block = inspect.getsource(MainApp.show_window)
        self.assertIn("if self.isHidden():", block)
        self.assertIn("if self.isMinimized():", block)
        self.assertIn("self.showNormal()", block)
        self.assertIn("self.raise_()", block)

    def test_init_ui_uses_normalized_window_geometry(self):
        src = self._read()
        start = src.index("def init_ui")
        end = src.index("def setup_shortcuts")
        block = src[start:end]
        self.assertIn("initial_geometry = self._normalize_window_geometry(self._saved_geometry)", block)
        self.assertIn("self.setGeometry(", block)
        self.assertIn("tab_bar = self._tab_bar()", block)
        self.assertIn("tab_bar.setUsesScrollButtons(True)", block)
        self.assertIn("tab_bar.setElideMode(Qt.TextElideMode.ElideRight)", block)
        self.assertNotIn("self.resize(1100, 850)", block)

    def test_main_window_has_screen_aware_geometry_helpers(self):
        src = self._read()
        self.assertIn("def _get_available_screen_geometry", src)
        self.assertIn("def _build_default_window_geometry", src)
        self.assertIn("def _normalize_window_geometry", src)

    def test_rename_tab_resets_fetch_state_when_fetch_key_changes(self):
        block = inspect.getsource(MainApp.rename_tab)
        self.assertIn("old_fetch_key = build_fetch_key(old_search_keyword, old_exclude_words)", block)
        self.assertIn("new_fetch_key = build_fetch_key(new_search_keyword, new_exclude_words)", block)
        self.assertIn("if old_fetch_key != new_fetch_key:", block)
        self.assertIn("self._prune_fetch_key_state(old_fetch_key, skip_keyword=new_keyword)", block)
        self.assertIn("self._tab_fetch_state[new_keyword] = self._make_tab_fetch_state()", block)
        self.assertNotIn("UPDATE news_keywords SET keyword=? WHERE keyword=?", block)
        self.assertNotIn("UPDATE news SET keyword=? WHERE keyword=?", block)
        self.assertIn("w.load_data_from_db()", block)
        self.assertIn("self.fetch_news(new_keyword)", block)

    def test_main_window_has_no_split_index_fallback(self):
        src = inspect.getsource(MainApp.on_fetch_done)
        self.assertNotIn("w.keyword.split()[0]", src)

    def test_badge_update_uses_tab_keyword_cache_and_exclude_aware_count(self):
        src = self._read()
        start = src.index("def update_all_tab_badges")
        end = src.index("def update_tab_badge")
        block = src[start:end]
        self.assertIn("build_fetch_key(search_keyword, exclude_words)", block)
        self.assertIn("self._require_db().get_unread_counts_by_query_keys(", block)
        self.assertIn("self._badge_unread_cache[keyword]", block)

        start = src.index("def update_tab_badge")
        end = src.index("def switch_to_tab")
        block = src[start:end]
        self.assertIn("cached = self._badge_unread_cache.get(keyword)", block)

    def test_update_tray_tooltip_uses_db_total_unread_count(self):
        block = inspect.getsource(MainApp.update_tray_tooltip)
        self.assertIn("self.db.get_total_unread_count()", block)

    def test_desktop_notification_uses_toast_fallback_without_tray(self):
        block = inspect.getsource(MainApp.show_desktop_notification)
        self.assertIn('self.show_toast(f"{title}: {message}")', block)
        self.assertIn("if self.sound_enabled:", block)

    def test_rename_tab_cleans_active_worker_and_uses_common_title_formatter(self):
        block = inspect.getsource(MainApp.rename_tab)
        self.assertIn("self._worker_registry.get_active_request_id(old_keyword)", block)
        self.assertIn("self.cleanup_worker(", block)
        self.assertIn("self._format_tab_title(new_keyword, unread_count=0)", block)

    def test_close_tab_cleans_active_worker_before_widget_cleanup(self):
        block = inspect.getsource(MainApp.close_tab)
        self.assertIn("self._worker_registry.get_active_request_id(removed_keyword)", block)
        self.assertIn("self.cleanup_worker(", block)
        self.assertLess(block.index("self.cleanup_worker("), block.index("widget.cleanup()"))


class TestStyleRiskFixes(unittest.TestCase):
    def test_tab_style_has_min_height_for_emoji_clipping(self):
        src = Path("ui/styles.py").read_text(encoding="utf-8")
        self.assertIn("QTabBar::tab {{", src)
        self.assertIn("min-height: 30px;", src)


class TestNewsTabRiskFixes(unittest.TestCase):
    def test_mark_all_read_supports_two_modes(self):
        src = Path("ui/news_tab.py").read_text(encoding="utf-8")
        start = src.index("def mark_all_read")
        end = src.index("def _on_mark_all_read_done")
        block = src[start:end]
        self.assertIn("현재 표시 결과만", block)
        self.assertIn("탭 전체", block)
        self.assertIn("self.db.mark_links_as_read", block)
        self.assertIn("self.db.mark_query_as_read", block)

    def test_stats_analysis_uses_raw_tab_query_data(self):
        block = inspect.getsource(MainApp.show_stats_analysis)
        self.assertIn("tab_combo.addItem(w.keyword, w.keyword)", block)
        self.assertIn("db_keyword, exclude_words = parse_tab_query(tab_query)", block)
        self.assertIn("exclude_words=exclude_words", block)
        self.assertIn("query_key=query_key", block)

