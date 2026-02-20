import unittest
from pathlib import Path

from core.query_parser import has_positive_keyword


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
        src = self._read()
        start = src.index("def _safe_refresh_all")
        end = src.index("def refresh_all")
        block = src[start:end]
        self.assertIn("started = False", block)
        self.assertIn("started = self.refresh_all()", block)
        self.assertIn("if not started:", block)
        self.assertIn("self._refresh_in_progress = False", block)

    def test_refresh_all_returns_bool_contract(self):
        src = self._read()
        start = src.index("def refresh_all")
        end = src.index("def _process_next_refresh")
        block = src[start:end]
        self.assertIn("def refresh_all(self) -> bool", block)
        self.assertIn("return True", block)
        self.assertIn("return False", block)

    def test_add_news_tab_load_more_uses_live_tab_keyword(self):
        src = self._read()
        start = src.index("def add_news_tab")
        end = src.index("def add_tab_dialog")
        block = src[start:end]
        self.assertIn("lambda _checked=False, tab_ref=tab: self.fetch_news(tab_ref.keyword, is_more=True)", block)
        self.assertNotIn("self.fetch_news(keyword, is_more=True)", block)

    def test_fetch_tracks_tab_pagination_state(self):
        src = self._read()
        self.assertIn("class TabFetchState", src)
        self.assertIn("self._tab_fetch_state", src)
        self.assertIn("self._request_start_index", src)
        self.assertIn("fetch_state.last_api_start_index + 100", src)

    def test_minimize_to_tray_is_handled_in_change_event(self):
        src = self._read()
        start = src.index("def changeEvent")
        end = src.index("def close_current_tab")
        block = src[start:end]
        self.assertIn("QEvent.Type.WindowStateChange", block)
        self.assertIn("self.minimize_to_tray", block)
        self.assertIn("QTimer.singleShot(0, self.hide)", block)

