# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import unittest
from typing import Any, cast

from core.worker_registry import WorkerHandle, WorkerRegistry
from ui.main_window_fetch_support.worker_flow_support.completion import _FetchWorkerCompletionMixin
from ui.main_window_fetch_support.worker_flow_support.state import _FetchWorkerStateMixin


class _DummyStaleFetchMain(_FetchWorkerCompletionMixin, _FetchWorkerStateMixin):
    def __init__(self):
        self._worker_registry = WorkerRegistry()
        self._tab_fetch_state = {}
        self._fetch_cursor_by_key = {}
        self._fetch_total_by_key = {}
        self._request_start_index = {}
        self._last_fetch_request_ts = {}
        self._last_auto_refresh_by_keyword = {}
        self._network_error_count = 0
        self._network_available = True
        self.progress = cast(Any, object())
        self.btn_refresh = cast(Any, object())
        self.toasts = []
        self.status_messages = []

    def _make_tab_fetch_state(self):
        from ui.main_window_support.base_support.state import TabFetchState

        return TabFetchState()

    def _find_news_tab(self, _keyword):
        return None

    def _status_bar(self):
        bar = cast(Any, object())
        bar.showMessage = lambda *_args, **_kwargs: None
        return bar

    def show_toast(self, message):
        self.toasts.append(str(message))

    def show_warning_toast(self, _message):
        return None

    def _schedule_tab_hydration(self, _delay_ms=0):
        return None

    def update_tab_badge(self, _keyword):
        return None

    def _build_fetch_summary_message(self, *_args, **_kwargs):
        return "done"

    def _notify_fetch_new_items(self, *_args, **_kwargs):
        return None

    def _on_sequential_fetch_done(self, _keyword):
        return None


class TestFetchDoneAfterRenameStale(unittest.TestCase):
    def test_on_fetch_done_ignores_callback_without_request_id(self):
        main = _DummyStaleFetchMain()
        main.on_fetch_done(
            {"new_items": [], "new_count": 0, "added_count": 0, "dup_count": 0, "total": 10, "filtered": 0},
            "AI",
            is_more=False,
            request_id=None,
        )
        self.assertEqual(main._fetch_total_by_key, {})
        self.assertEqual(main.toasts, [])

    def test_on_fetch_done_ignores_stale_request_after_registry_cleanup(self):
        main = _DummyStaleFetchMain()
        handle = WorkerHandle(
            request_id=3,
            tab_keyword="AI",
            search_keyword="AI",
            db_keyword="AI",
            exclude_words=[],
            worker=cast(Any, object()),
            thread=cast(Any, object()),
        )
        main._worker_registry.register(handle)
        main._worker_registry.pop_by_request_id(3)

        main.on_fetch_done(
            {"new_items": [], "new_count": 0, "added_count": 0, "dup_count": 0, "total": 99, "filtered": 0},
            "AI",
            is_more=False,
            request_id=3,
        )
        self.assertEqual(main._fetch_total_by_key, {})


if __name__ == "__main__":
    unittest.main()