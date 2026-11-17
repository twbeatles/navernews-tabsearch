import inspect
import re
import unittest
from typing import Any, cast

from ui.main_window import MainApp


def _norm(text):
    # Format-tolerant source matching: ruff format may reflow code
    # lines and add/remove grouping parentheses. Compare the token
    # stream, ignoring grouping brackets.
    toks = re.findall(r"\w+|[^\w\s]", text)
    return " ".join(t for t in toks if t not in "()[]{}")


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
    _compute_load_more_state = cast(Any, MainApp._compute_load_more_state)
    _apply_load_more_button_state = cast(Any, MainApp._apply_load_more_button_state)


class TestLoadMoreTotalGuard(unittest.TestCase):
    def test_helper_formula_source_guard(self):
        src = inspect.getsource(MainApp._compute_load_more_state)
        self.assertIn("next_start = last_api_start_index + 100", src)
        self.assertIn("if next_start > 1000:", src)
        self.assertIn("if total is None:", src)
        self.assertIn("return next_start <= min(1000, max(0, int(total or 0)))", src)

    def test_apply_load_more_button_state(self):
        app = _MainWindowShim()
        tab = _DummyTab()

        has_more = app._apply_load_more_button_state(
            cast(Any, tab), total=250, last_api_start_index=101
        )
        self.assertTrue(has_more)
        self.assertTrue(tab.btn_load.enabled)

        has_more = app._apply_load_more_button_state(
            cast(Any, tab), total=180, last_api_start_index=101
        )
        self.assertFalse(has_more)
        self.assertFalse(tab.btn_load.enabled)

    def test_on_fetch_done_uses_total_based_button_update(self):
        block = inspect.getsource(MainApp.on_fetch_done)
        self.assertIn(
            _norm(
                "self._apply_load_more_button_state(tab_widget, total, last_api_start_index)"
            ),
            _norm(block),
        )
        self.assertIn("self._fetch_total_by_key[fetch_key] = total", block)
