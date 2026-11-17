# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Regression: ApiWorker callbacks must run on the GUI thread.

PySide6 delivers a signal connected to a bare lambda as a direct call in the
emitting thread. ``on_fetch_done`` then ran on the worker QThread, and the
``QTimer.singleShot`` that advances the sequential chain was parked on a
thread that was quitting, so tab-by-tab refresh stopped after the first tab.
These tests use a real QThread and real signals (the fakes in
``test_sequential_refresh_stall`` cannot observe thread affinity).
"""

import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from test_sequential_refresh_stall import _FakeTabs, _result, _SequentialStallMain

from ui.main_window_fetch_support.refresh_flow import _MainWindowRefreshFlowMixin


class _ThreadedFakeApiWorker(QObject):
    finished = Signal(dict)
    error = Signal(str)
    progress = Signal(str)
    fail = False

    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.last_error_meta = None

    def run(self):
        if self.fail:
            self.error.emit("boom")
        else:
            self.finished.emit(_result())

    def stop(self):
        return None


class _ThreadedSequentialMain(_SequentialStallMain):
    def __init__(self):
        super().__init__()
        self.tabs = _FakeTabs([object()])
        self.callback_threads = []
        self.fetched_keywords = []
        self.finished_chain = False
        self.notify_on_refresh = False

    def fetch_news(self, keyword, is_more=False, is_sequential=False):
        self.fetched_keywords.append(keyword)
        return super().fetch_news(keyword, is_more=is_more, is_sequential=is_sequential)

    def _on_sequential_fetch_done(self, keyword):
        self.callback_threads.append(
            threading.current_thread() is threading.main_thread()
        )
        _MainWindowRefreshFlowMixin._on_sequential_fetch_done(self, keyword)

    def _finish_sequential_refresh(self):
        self.finished_chain = True
        self._sequential_refresh_active = False

    def update_tab_badge(self, _keyword):
        return None

    def _notify_fetch_new_items(self, *_args, **_kwargs):
        return None


def _app():
    return QApplication.instance() or QApplication([])


def _pump_until(predicate, timeout_sec=5.0):
    app = _app()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestApiWorkerThreadAffinity(unittest.TestCase):
    def _run_chain(self, *, fail: bool):
        _app()
        main = _ThreadedSequentialMain()
        with (
            mock.patch.object(_ThreadedFakeApiWorker, "fail", fail),
            mock.patch(
                "ui.main_window_fetch_support.worker_flow.ApiWorker",
                _ThreadedFakeApiWorker,
            ),
        ):
            main._sequential_refresh_active = False
            self.assertTrue(main._begin_sequential_refresh(["AI", "B", "C"]))
            completed = _pump_until(lambda: main.finished_chain)
            _pump_until(
                lambda: not main._worker_registry.all_handles(), timeout_sec=2.0
            )
        return main, completed

    def test_sequential_chain_advances_through_every_tab(self):
        main, completed = self._run_chain(fail=False)

        self.assertTrue(completed, f"chain stalled after {main.fetched_keywords}")
        self.assertEqual(main.fetched_keywords, ["AI", "B", "C"])
        self.assertEqual(main.callback_threads, [True, True, True])

    def test_sequential_chain_advances_after_worker_errors(self):
        main, completed = self._run_chain(fail=True)

        self.assertTrue(completed, f"chain stalled after {main.fetched_keywords}")
        self.assertEqual(main.fetched_keywords, ["AI", "B", "C"])
        self.assertEqual(main.callback_threads, [True, True, True])


class TestApiWorkerAlwaysSignals(unittest.TestCase):
    """run() must end in finished or error unless cancelled; otherwise the
    owning QThread never quits and the sequential chain waits forever."""

    def _run_worker(self, **kwargs):
        from core.workers_support.api_worker import ApiWorker

        worker = ApiWorker(
            "client-id",
            "client-secret",
            "AI",
            "AI",
            [],
            mock.Mock(),
            **kwargs,
        )
        errors = []
        finished = []
        worker.error.connect(errors.append)
        worker.finished.connect(finished.append)
        worker.run()
        return worker, errors, finished

    def test_session_factory_failure_emits_error(self):
        worker, errors, finished = self._run_worker(
            session_factory=mock.Mock(side_effect=RuntimeError("session boom")),
        )

        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("session boom", errors[0])
        self.assertEqual(worker.last_error_meta["kind"], "internal_error")

    def test_exhausted_retry_loop_emits_error(self):
        _worker, errors, finished = self._run_worker(
            session_factory=mock.Mock(return_value=mock.Mock()),
            max_retries=0,
        )

        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
