# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Regression tests: a sequential (tab-by-tab) refresh must never get stuck.

Covered stall paths:
- ``fetch_news(..., is_sequential=True)`` early returns (shutdown, maintenance,
  empty keyword, cooldown) must advance/abort the chain instead of leaving
  ``_sequential_refresh_active`` set forever.
- Stale ``on_fetch_done`` / ``on_fetch_error`` callbacks for the currently
  awaited slot must advance the chain (worker detached by tab close/rename).
- Stale callbacks for other keywords must NOT advance the chain.
- Closing the tab that is currently being refreshed must advance the chain.
- A manual (non-sequential) fetch must not steal the worker of the slot the
  sequential chain is currently waiting for.
"""
import unittest
from typing import Any, cast
from unittest import mock

from PySide6.QtCore import QMutex

from core.worker_registry import WorkerHandle, WorkerRegistry
from ui._main_window_tabs import _MainWindowTabsMixin
from ui.main_window_fetch_support.refresh_flow import _MainWindowRefreshFlowMixin
from ui.main_window_fetch_support.worker_flow_support.completion import _FetchWorkerCompletionMixin
from ui.main_window_fetch_support.worker_flow_support.start import _FetchWorkerStartMixin
from ui.main_window_fetch_support.worker_flow_support.state import _FetchWorkerStateMixin


class _DummyButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class _DummyProgress:
    def setVisible(self, _value):
        return None

    def setRange(self, _start, _end):
        return None

    def setValue(self, _value):
        return None


class _DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, _timeout=0):
        self.messages.append(str(message))


class _FakeSignal:
    def connect(self, _slot):
        return None

    def disconnect(self):
        return None


class _FakeWorker:
    def __init__(self):
        self.stop_calls = 0
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.progress = _FakeSignal()

    def stop(self):
        self.stop_calls += 1

    def deleteLater(self):
        return None

    def moveToThread(self, _thread):
        return None


class _FakeThread:
    def __init__(self, wait_result=True):
        self.wait_result = wait_result
        self.quit_calls = 0

    def isRunning(self):
        return True

    def quit(self):
        self.quit_calls += 1

    def wait(self, _timeout):
        return self.wait_result

    def deleteLater(self):
        return None


class _FakeLoadButton:
    def setEnabled(self, _value):
        return None

    def setText(self, _value):
        return None


class _FakeTab:
    def __init__(self, keyword: str):
        self.keyword = keyword
        self.btn_load = _FakeLoadButton()
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1

    def deleteLater(self):
        return None


class _FakeTabs:
    def __init__(self, tabs):
        self._tabs = list(tabs)

    def count(self):
        return len(self._tabs)

    def widget(self, index):
        return self._tabs[index]

    def removeTab(self, index):
        self._tabs.pop(index)


class _SequentialStallMain(
    _MainWindowRefreshFlowMixin,
    _FetchWorkerStartMixin,
    _FetchWorkerCompletionMixin,
    _FetchWorkerStateMixin,
    _MainWindowTabsMixin,
):
    """Dummy combining the real fetch/refresh/close mixins."""

    def __init__(self):
        self._shutdown_in_progress = False
        self._maintenance_mode = False
        self._sequential_refresh_active = True
        self._pending_refresh_keywords = ["AI"]
        self._current_refresh_idx = 0
        self._total_refresh_count = 1
        self._sequential_new_count = 0
        self._sequential_added_count = 0
        self._sequential_dup_count = 0
        self._sequential_refresh_is_auto = False
        self._refresh_in_progress = False
        self._refresh_mutex = QMutex()
        self._fetch_cooldown_until = 0.0
        self._fetch_cooldown_reason = ""
        self._last_fetch_request_ts = {}
        self._fetch_dedupe_window_sec = 10.0
        self._fetch_dedupe_notified_keys = set()
        self._request_start_index = {}
        self._worker_registry = WorkerRegistry()
        self._worker_request_seq = 0
        self._worker_cleanup_timeout_count = 0
        self._worker_cleanup_diag_shown = False
        self.client_id = "valid-client-id"
        self.client_secret = "valid-client-secret"
        self.api_timeout = 15
        self._tab_fetch_state = {}
        self._fetch_cursor_by_key = {}
        self._fetch_total_by_key = {}
        self._last_auto_refresh_by_keyword = {}
        self.tab_refresh_policies = {}
        self._network_error_count = 0
        self._network_available = True
        self._max_network_errors = 3
        self.status_bar = _DummyStatusBar()
        self.progress = _DummyProgress()
        self.btn_refresh = _DummyButton()
        self.warning_toasts = []
        self.seq_done_keywords = []
        self.tabs = _FakeTabs([object(), _FakeTab("AI"), _FakeTab("B")])
        self.save_config_calls = 0
        self.removed_hydrations = []
        self.hydration_delays = []

    # -- stubs -------------------------------------------------------------
    def is_maintenance_mode_active(self):
        return bool(self._maintenance_mode)

    def _maintenance_block_message(self, action):
        return f"maintenance {action}"

    def _status_bar(self):
        return self.status_bar

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def show_toast(self, _message):
        return None

    def show_desktop_notification(self, _title, _message):
        return None

    def _on_sequential_fetch_done(self, keyword):
        self.seq_done_keywords.append(keyword)

    def _make_tab_fetch_state(self):
        from ui.main_window_support.base_support.state import TabFetchState

        return TabFetchState()

    def _find_news_tab(self, keyword):
        for index in range(1, self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "keyword", None) == keyword:
                return index, widget
        return None

    def _news_tab_at(self, index):
        widget = self.tabs.widget(index)
        if widget is None or index == 0:
            return None
        return widget

    def _iter_news_tabs(self, start_index=0):
        for index in range(start_index, self.tabs.count()):
            widget = self.tabs.widget(index)
            if index > 0 and isinstance(widget, _FakeTab):
                yield index, cast(Any, widget)

    def _remove_tab_hydration(self, keyword):
        self.removed_hydrations.append(keyword)

    def save_config(self):
        self.save_config_calls += 1

    def sync_tab_load_more_state(self, _keyword):
        return None

    def _schedule_tab_hydration(self, delay_ms=0):
        self.hydration_delays.append(delay_ms)

    def _require_db(self):
        return mock.Mock()

    def _require_http_client_config(self):
        config = mock.Mock()
        config.create_session.return_value = mock.Mock()
        return config


def _result(*, total=5):
    return {
        "items": [],
        "new_items": [],
        "new_count": 0,
        "added_count": 0,
        "dup_count": 0,
        "total": total,
        "filtered": 0,
    }


class TestSequentialRefreshStall(unittest.TestCase):
    def _fresh_main(self) -> _SequentialStallMain:
        return _SequentialStallMain()

    def test_sequential_fetch_aborts_chain_on_shutdown(self):
        main = self._fresh_main()
        main._shutdown_in_progress = True

        main.fetch_news("AI", is_sequential=True)

        self.assertFalse(main._sequential_refresh_active)
        self.assertEqual(main._pending_refresh_keywords, [])

    def test_sequential_fetch_advances_on_maintenance_block(self):
        main = self._fresh_main()
        main._maintenance_mode = True

        main.fetch_news("AI", is_sequential=True)

        self.assertEqual(main.seq_done_keywords, ["AI"])

    def test_sequential_fetch_advances_on_empty_keyword(self):
        main = self._fresh_main()
        main._pending_refresh_keywords = ["-광고"]

        main.fetch_news("-광고", is_sequential=True)

        self.assertEqual(main.seq_done_keywords, ["-광고"])

    def test_sequential_fetch_advances_when_cooldown_is_active(self):
        main = self._fresh_main()
        main._set_fetch_cooldown(60, reason="rate_limit")

        with mock.patch(
            "ui.main_window_fetch_support.worker_flow.ApiWorker",
            side_effect=AssertionError("worker must not start while cooling down"),
        ):
            main.fetch_news("AI", is_sequential=True)

        self.assertEqual(main.seq_done_keywords, ["AI"])

    def test_sequential_stale_error_advances_awaited_slot(self):
        main = self._fresh_main()
        handle = WorkerHandle(
            request_id=5,
            tab_keyword="AI",
            search_keyword="AI",
            db_keyword="AI",
            exclude_words=[],
            worker=cast(Any, _FakeWorker()),
            thread=cast(Any, _FakeThread()),
        )
        main._worker_registry.register(handle)
        # Simulate a force-detach (e.g. tab closed while its worker was stopping).
        main._worker_registry.pop_by_request_id(5)

        main.on_fetch_error(
            "boom",
            "AI",
            is_sequential=True,
            request_id=5,
            error_meta={"kind": "network_error"},
        )

        self.assertEqual(main.seq_done_keywords, ["AI"])

    def test_sequential_stale_done_advances_awaited_slot(self):
        main = self._fresh_main()
        handle = WorkerHandle(
            request_id=6,
            tab_keyword="AI",
            search_keyword="AI",
            db_keyword="AI",
            exclude_words=[],
            worker=cast(Any, _FakeWorker()),
            thread=cast(Any, _FakeThread()),
        )
        main._worker_registry.register(handle)
        main._worker_registry.pop_by_request_id(6)

        main.on_fetch_done(_result(), "AI", is_more=False, is_sequential=True, request_id=6)

        self.assertEqual(main.seq_done_keywords, ["AI"])

    def test_sequential_stale_callback_for_other_keyword_does_not_advance(self):
        main = self._fresh_main()

        main.on_fetch_done(_result(), "B", is_more=False, is_sequential=True, request_id=999)

        self.assertEqual(main.seq_done_keywords, [])

    def test_close_tab_advances_parked_sequential_chain(self):
        main = self._fresh_main()
        main._pending_refresh_keywords = ["AI", "B"]
        main._total_refresh_count = 2
        # The worker for "AI" was already detached; the chain is parked on it.
        self.assertIsNone(main._worker_registry.get_active_request_id("AI"))

        main.close_tab(1)

        self.assertEqual(main.seq_done_keywords, ["AI"])
        self.assertEqual(main.tabs.count(), 2)
        self.assertEqual(main.save_config_calls, 1)

    def test_manual_fetch_does_not_steal_awaited_sequential_worker(self):
        main = self._fresh_main()
        worker = _FakeWorker()
        thread = _FakeThread(wait_result=True)
        handle = WorkerHandle(
            request_id=11,
            tab_keyword="AI",
            search_keyword="AI",
            db_keyword="AI",
            exclude_words=[],
            worker=cast(Any, worker),
            thread=cast(Any, thread),
        )
        main._worker_registry.register(handle)

        with (
            mock.patch(
                "ui.main_window_fetch_support.worker_flow.ApiWorker",
                side_effect=AssertionError("must not start a second worker"),
            ),
            mock.patch("ui.main_window_fetch_support.worker_flow_support.start.QThread"),
        ):
            main.fetch_news("AI")

        self.assertEqual(worker.stop_calls, 0)
        self.assertEqual(main._worker_registry.get_active_request_id("AI"), 11)


if __name__ == "__main__":
    unittest.main()
