import unittest
from pathlib import Path

from ui.main_window import MainApp


class _DummyButton:
    def __init__(self):
        self.enabled = None
        self.text = ""

    def setEnabled(self, value):
        self.enabled = value

    def setText(self, value):
        self.text = value


class _DummyTab:
    def __init__(self):
        self.btn_load = _DummyButton()


class _MainWindowShim:
    _compute_load_more_state = MainApp._compute_load_more_state
    _apply_load_more_button_state = MainApp._apply_load_more_button_state


class TestLoadMoreTotalGuard(unittest.TestCase):
    def test_helper_formula_source_guard(self):
        src = Path("ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("next_start = last_api_start_index + 100", src)
        self.assertIn("has_more = next_start <= min(1000, total)", src)

    def test_apply_load_more_button_state(self):
        app = _MainWindowShim()
        tab = _DummyTab()

        has_more = app._apply_load_more_button_state(tab, total=250, last_api_start_index=101)
        self.assertTrue(has_more)
        self.assertTrue(tab.btn_load.enabled)

        has_more = app._apply_load_more_button_state(tab, total=180, last_api_start_index=101)
        self.assertFalse(has_more)
        self.assertFalse(tab.btn_load.enabled)

    def test_on_fetch_done_uses_total_based_button_update(self):
        src = Path("ui/main_window.py").read_text(encoding="utf-8")
        start = src.index("def on_fetch_done")
        end = src.index("def on_fetch_error")
        block = src[start:end]
        self.assertIn("self._apply_load_more_button_state(w, total, last_api_start_index)", block)
