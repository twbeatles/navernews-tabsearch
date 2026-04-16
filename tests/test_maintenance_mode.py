import unittest
from collections import deque
from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QMutex

from ui._main_window_fetch import _MainWindowFetchMixin
from ui.main_window import MainApp


class _DummyButton:
    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = str(value)


class _DummyProgress:
    def __init__(self):
        self.visible = False

    def setVisible(self, value):
        self.visible = bool(value)


class _DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append((str(message), int(timeout)))


class _DummyTab:
    def __init__(self, keyword):
        self.keyword = keyword
        self.is_bookmark_tab = False
        self.btn_load = _DummyButton()


class _DummyRegistry:
    def __init__(self, handles):
        self._handles = list(handles)

    def all_handles(self):
        return list(self._handles)


class _DummyMain:
    is_maintenance_mode_active = MainApp.is_maintenance_mode_active
    _maintenance_block_message = MainApp._maintenance_block_message
    _set_fetch_controls_enabled = MainApp._set_fetch_controls_enabled
    _apply_maintenance_ui_state = MainApp._apply_maintenance_ui_state
    _cancel_active_fetch_workers = MainApp._cancel_active_fetch_workers
    begin_database_maintenance = MainApp.begin_database_maintenance
    end_database_maintenance = MainApp.end_database_maintenance

    def __init__(self, cleanup_results):
        self._maintenance_mode = False
        self._maintenance_reason = ""
        self._sequential_refresh_active = False
        self._pending_refresh_keywords = []
        self._current_refresh_idx = 0
        self._total_refresh_count = 0
        self.progress = _DummyProgress()
        self._refresh_mutex = QMutex()
        self.btn_refresh = _DummyButton()
        self.btn_add = _DummyButton()
        self._tabs = [_DummyTab("AI")]
        self._status = _DummyStatusBar()
        self.warning_toasts = []
        self.toasts = []
        self.hydration_delays = []
        self.fts_pause_delays = []
        self.fts_resume_delays = []
        self.cleanup_results = dict(cleanup_results)
        self.cleanup_calls = []
        self._worker_registry = _DummyRegistry(
            [SimpleNamespace(tab_keyword=keyword, request_id=request_id) for request_id, keyword in cleanup_results]
        )

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._tabs[start_index:], start_index):
            yield index, tab

    def _status_bar(self):
        return self._status

    def cleanup_worker(self, keyword=None, request_id=None, only_if_active=False, wait_ms=1000):
        self.cleanup_calls.append((keyword, request_id, only_if_active, wait_ms))
        return bool(self.cleanup_results.get((request_id, keyword), False))

    def sync_tab_load_more_state(self, keyword):
        for tab in self._tabs:
            if tab.keyword == keyword:
                tab.btn_load.setEnabled(True)
                tab.btn_load.setText("📄 더 불러오기")

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def show_toast(self, message):
        self.toasts.append(str(message))

    def _schedule_tab_hydration(self, delay_ms=0):
        self.hydration_delays.append(int(delay_ms))

    def _pause_fts_backfill(self, *, retry_delay_ms=1000):
        self.fts_pause_delays.append(int(retry_delay_ms))

    def _request_fts_backfill_resume(self, *, delay_ms=250):
        self.fts_resume_delays.append(int(delay_ms))


class _DummyFetchBlockMain:
    is_maintenance_mode_active = MainApp.is_maintenance_mode_active
    _maintenance_block_message = MainApp._maintenance_block_message

    def __init__(self):
        self._maintenance_mode = True
        self._maintenance_reason = "오래된 기사 정리"
        self._status = _DummyStatusBar()
        self.warning_toasts = []

    def _status_bar(self):
        return self._status

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def fetch_news(self, keyword: str, is_more: bool = False, is_sequential: bool = False):
        return cast(Any, _MainWindowFetchMixin).fetch_news(
            cast(Any, self),
            keyword,
            is_more=is_more,
            is_sequential=is_sequential,
        )


class _DummyHydrationTab:
    def __init__(self, keyword, *, needs=True, cancel_result=True):
        self.keyword = keyword
        self.is_bookmark_tab = False
        self._needs = needs
        self.request_calls = 0
        self.cancel_calls = []
        self.cancel_result = bool(cancel_result)

    def needs_initial_hydration(self):
        return self._needs

    def is_initial_hydration_inflight(self):
        return False

    def request_initial_hydration(self):
        self.request_calls += 1
        return True

    def cancel_initial_hydration(self, wait_ms=300):
        self.cancel_calls.append(int(wait_ms))
        return self.cancel_result


class _DummyHydrationMain:
    _remove_tab_hydration = MainApp._remove_tab_hydration
    _enqueue_tab_hydration = MainApp._enqueue_tab_hydration
    _is_tab_hydration_paused = MainApp._is_tab_hydration_paused
    _start_tab_hydration = MainApp._start_tab_hydration
    _cancel_active_tab_hydration = MainApp._cancel_active_tab_hydration
    _process_tab_hydration = MainApp._process_tab_hydration

    def __init__(self):
        self._shutdown_in_progress = False
        self._maintenance_mode = False
        self._refresh_in_progress = False
        self._sequential_refresh_active = False
        self._hydration_inflight_keyword = ""
        self._tab_hydration_queue = deque(["OTHER"])
        self.current_tab = _DummyHydrationTab("AI", needs=True)
        self.other_tab = _DummyHydrationTab("OTHER", needs=True)
        self._worker_registry = _DummyRegistry([])
        self.hydration_delays = []

    def is_maintenance_mode_active(self):
        return self._maintenance_mode

    def _current_news_tab(self):
        return self.current_tab

    def _find_news_tab(self, keyword):
        if keyword == "AI":
            return 1, self.current_tab
        if keyword == "OTHER":
            return 2, self.other_tab
        return None

    def _schedule_tab_hydration(self, delay_ms=0):
        self.hydration_delays.append(int(delay_ms))


class TestMaintenanceMode(unittest.TestCase):
    def test_begin_database_maintenance_cancels_workers_and_disables_fetch_controls(self):
        dummy = _DummyMain({(1, "AI"): True})

        started, reason = dummy.begin_database_maintenance("delete_old_news")

        self.assertTrue(started)
        self.assertEqual(reason, "")
        self.assertTrue(dummy.is_maintenance_mode_active())
        self.assertEqual(dummy.cleanup_calls[0][0:2], ("AI", 1))
        self.assertFalse(dummy.btn_refresh.enabled)
        self.assertFalse(dummy.btn_add.enabled)
        self.assertFalse(dummy._tabs[0].btn_load.enabled)
        self.assertIn("유지보수 모드", dummy.warning_toasts[0])
        self.assertEqual(dummy.fts_pause_delays, [1000])

        dummy.end_database_maintenance()
        self.assertFalse(dummy.is_maintenance_mode_active())
        self.assertTrue(dummy.btn_refresh.enabled)
        self.assertTrue(dummy.btn_add.enabled)
        self.assertEqual(dummy._tabs[0].btn_load.text, "📄 더 불러오기")
        self.assertEqual(dummy.hydration_delays, [50])
        self.assertEqual(dummy.fts_resume_delays, [250])

    def test_begin_database_maintenance_fails_when_worker_cleanup_times_out(self):
        dummy = _DummyMain({(1, "AI"): False})

        started, reason = dummy.begin_database_maintenance("delete_old_news")

        self.assertFalse(started)
        self.assertIn("1.5초", reason)
        self.assertFalse(dummy.is_maintenance_mode_active())

    def test_fetch_entrypoints_are_blocked_during_maintenance(self):
        dummy = _DummyFetchBlockMain()

        dummy.fetch_news("AI")

        self.assertEqual(len(dummy.warning_toasts), 1)
        self.assertIn("유지보수 중", dummy.warning_toasts[0])
        self.assertIn("유지보수 중", dummy._status.messages[0][0])

    def test_tab_hydration_prioritizes_current_tab_before_queue(self):
        dummy = _DummyHydrationMain()

        dummy._process_tab_hydration()

        self.assertEqual(dummy.current_tab.request_calls, 1)
        self.assertEqual(dummy.other_tab.request_calls, 0)
        self.assertEqual(dummy._hydration_inflight_keyword, "AI")

    def test_cancel_active_tab_hydration_requeues_even_when_worker_wait_times_out(self):
        dummy = _DummyHydrationMain()
        dummy.current_tab = _DummyHydrationTab("AI", needs=True, cancel_result=False)
        dummy._hydration_inflight_keyword = "AI"

        finished = dummy._cancel_active_tab_hydration(requeue=True, wait_ms=200)

        self.assertFalse(finished)
        self.assertEqual(dummy._hydration_inflight_keyword, "")
        self.assertEqual(dummy.current_tab.cancel_calls, [200])
        self.assertEqual(list(dummy._tab_hydration_queue), ["OTHER", "AI"])


if __name__ == "__main__":
    unittest.main()
