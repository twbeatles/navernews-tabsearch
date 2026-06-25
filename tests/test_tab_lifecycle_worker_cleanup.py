# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import unittest
from typing import Any, cast
from unittest import mock

from core.worker_registry import WorkerHandle, WorkerRegistry
from ui._main_window_tabs import _MainWindowTabsMixin
from ui.main_window_fetch_support.worker_flow_support.completion import _FetchWorkerCompletionMixin


class _FakeWorker:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1

    def finished(self):
        return _FakeSignal()

    def error(self):
        return _FakeSignal()

    def progress(self):
        return _FakeSignal()

    def deleteLater(self):
        return None


class _FakeSignal:
    def disconnect(self):
        return None


class _FakeThread:
    def __init__(self, *, wait_result: bool = True):
        self._running = not wait_result
        self.wait_result = wait_result

    def isRunning(self):
        return self._running

    def quit(self):
        return None

    def wait(self, _timeout):
        if self.wait_result:
            self._running = False
        return self.wait_result

    def deleteLater(self):
        return None


class _FakeNewsTab:
    def __init__(self, keyword: str):
        self.keyword = keyword
        self.cleanup_calls = 0
        self.total_api_count = 0
        self.last_update = None

    def cleanup(self):
        self.cleanup_calls += 1

    def load_data_from_db(self):
        return None

    def needs_initial_hydration(self):
        return False

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

    def setTabText(self, index, text):
        self._tab_texts[index] = text

    def currentIndex(self):
        return 1


class _DummyTabsMain(_MainWindowTabsMixin, _FetchWorkerCompletionMixin):
    close_tab = _MainWindowTabsMixin.close_tab

    def __init__(self):
        self._news_tab = _FakeNewsTab("AI")
        self.tabs = _FakeTabs([object(), self._news_tab])
        self.tabs._tab_texts = {1: "AI"}
        self._worker_registry = WorkerRegistry()
        self._worker_cleanup_timeout_count = 0
        self._tab_fetch_state = {}
        self._last_auto_refresh_by_keyword = {}
        self.tab_refresh_policies = {}
        self._fetch_cursor_by_key = {}
        self._fetch_total_by_key = {}
        self._last_fetch_request_ts = {}
        self._request_start_index = {}
        self._remove_tab_hydration_calls = []
        self.save_config_calls = 0
        self.warning_toasts = []
        self.status_messages = []

    def _news_tab_at(self, index):
        widget = self.tabs.widget(index)
        if widget is None or index == 0:
            return None
        return widget

    def _iter_news_tabs(self, start_index=0):
        for index in range(start_index, self.tabs.count()):
            widget = self.tabs.widget(index)
            if widget is not None and index > 0:
                yield index, cast(Any, widget)

    def _status_bar(self):
        bar = mock.Mock()
        bar.showMessage = lambda message, _timeout=0: self.status_messages.append(str(message))
        return bar

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def _remove_tab_hydration(self, keyword):
        self._remove_tab_hydration_calls.append(keyword)

    def _prune_fetch_key_state(self, _fetch_key, skip_keyword=None):
        return None

    def save_config(self):
        self.save_config_calls += 1

    def _make_tab_fetch_state(self):
        from ui.main_window_support.base_support.state import TabFetchState

        return TabFetchState()

    def _schedule_tab_hydration(self, _delay_ms=0):
        return None


class TestTabLifecycleWorkerCleanup(unittest.TestCase):
    def _register_running_worker(self, main: _DummyTabsMain, *, wait_result: bool = True) -> int:
        request_id = 11
        handle = WorkerHandle(
            request_id=request_id,
            tab_keyword="AI",
            search_keyword="AI",
            db_keyword="AI",
            exclude_words=[],
            worker=cast(Any, _FakeWorker()),
            thread=cast(Any, _FakeThread(wait_result=wait_result)),
        )
        main._worker_registry.register(handle)
        main._request_start_index[request_id] = 1
        main._tab_fetch_state["AI"] = main._make_tab_fetch_state()
        return request_id

    def test_close_tab_force_detaches_worker_and_removes_tab(self):
        main = _DummyTabsMain()
        self._register_running_worker(main, wait_result=False)

        main.close_tab(1)

        self.assertEqual(main.tabs.count(), 1)
        self.assertIsNone(main._worker_registry.get_active_request_id("AI"))
        self.assertNotIn("AI", main._tab_fetch_state)
        self.assertEqual(main._news_tab.cleanup_calls, 1)
        self.assertEqual(main.save_config_calls, 1)
        self.assertTrue(any("백그라운드 새로고침" in msg for msg in main.warning_toasts))

    def test_ensure_tab_worker_stopped_uses_force_detach_after_timeout(self):
        main = _DummyTabsMain()
        self._register_running_worker(main, wait_result=False)

        self.assertTrue(main._ensure_tab_worker_stopped("AI", 11, "탭 닫기", wait_ms=10))
        self.assertIsNone(main._worker_registry.get_active_request_id("AI"))


if __name__ == "__main__":
    unittest.main()