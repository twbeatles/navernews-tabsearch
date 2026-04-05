import os
import unittest
from typing import Any, cast
from unittest import mock

from PyQt6.QtWidgets import QApplication

from ui._main_window_tray import _MainWindowTrayMixin
from ui.news_tab import NewsTab


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeSignal:
    def __init__(self):
        self.disconnect_calls = 0

    def disconnect(self):
        self.disconnect_calls += 1

    def connect(self, _callback):
        return None


class _FakeWorker:
    def __init__(self, *, running=True, wait_result=True):
        self.running = running
        self.wait_result = wait_result
        self.stop_calls = 0
        self.wait_calls = []
        self.parent_values = []
        self.delete_later_calls = 0
        self.finished = _FakeSignal()
        self.error = _FakeSignal()

    def isRunning(self):
        return self.running

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return self.wait_result

    def requestInterruption(self):
        return None

    def quit(self):
        return None

    def setParent(self, value):
        self.parent_values.append(value)

    def deleteLater(self):
        self.delete_later_calls += 1


class _FakeTab:
    def __init__(self, keyword: str, call_log: list[str]):
        self.keyword = keyword
        self._call_log = call_log
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1
        self._call_log.append(f"tab.cleanup:{self.keyword}")


class _FakeHandle:
    def __init__(self, tab_keyword: str, request_id: int):
        self.tab_keyword = tab_keyword
        self.request_id = request_id


class _FakeRegistry:
    def __init__(self, handles):
        self._handles = list(handles)

    def all_handles(self):
        return list(self._handles)


class _FakeTimer:
    def __init__(self, call_log: list[str], label: str):
        self._call_log = call_log
        self._label = label

    def stop(self):
        self._call_log.append(f"timer.stop:{self._label}")


class _FakeExportWorker:
    def __init__(self, call_log: list[str]):
        self._call_log = call_log

    def isRunning(self):
        return True

    def requestInterruption(self):
        self._call_log.append("export.requestInterruption")

    def wait(self, timeout):
        self._call_log.append(f"export.wait:{timeout}")
        return True


class _FakeCloser:
    def __init__(self, call_log: list[str], label: str):
        self._call_log = call_log
        self._label = label

    def close(self):
        self._call_log.append(f"{self._label}.close")


class _FakeApp:
    def __init__(self, call_log: list[str]):
        self._call_log = call_log

    def quit(self):
        self._call_log.append("app.quit")


class _FakeEvent:
    def __init__(self):
        self.accept_calls = 0

    def accept(self):
        self.accept_calls += 1


class _DummyCloseMain:
    def _cleanup_open_tabs_for_shutdown(self):
        return cast(Any, _MainWindowTrayMixin)._cleanup_open_tabs_for_shutdown(cast(Any, self))

    def _perform_real_close(self, event):
        return cast(Any, _MainWindowTrayMixin)._perform_real_close(cast(Any, self), event)

    def __init__(self):
        self.call_log: list[str] = []
        self.timer = _FakeTimer(self.call_log, "main")
        self._countdown_timer = _FakeTimer(self.call_log, "countdown")
        self._tab_badge_timer = _FakeTimer(self.call_log, "badge")
        self._tabs = [_FakeTab("AI", self.call_log), _FakeTab("경제", self.call_log)]
        self._worker_registry = _FakeRegistry([_FakeHandle("AI", 7)])
        self.workers = {"AI": object()}
        self._export_worker = _FakeExportWorker(self.call_log)
        self.db = _FakeCloser(self.call_log, "db")
        self.session = _FakeCloser(self.call_log, "session")
        self._shutdown_in_progress = False
        self._app = _FakeApp(self.call_log)

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._tabs[start_index:], start_index):
            yield index, tab

    def cleanup_worker(self, keyword=None, request_id=None, only_if_active=False):
        self.call_log.append(f"cleanup_worker:{keyword}:{request_id}:{int(bool(only_if_active))}")
        return True

    def save_config(self):
        self.call_log.append("save_config")

    def _app_instance(self):
        return self._app


class _FakeDb:
    def fetch_news(self, **kwargs):
        return []


class TestShutdownCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_perform_real_close_cleans_tabs_before_db_close(self):
        dummy = _DummyCloseMain()
        event = _FakeEvent()

        dummy._perform_real_close(event)

        self.assertEqual(event.accept_calls, 1)
        self.assertIn("tab.cleanup:AI", dummy.call_log)
        self.assertIn("tab.cleanup:경제", dummy.call_log)
        self.assertIn("cleanup_worker:AI:7:0", dummy.call_log)
        self.assertIn("save_config", dummy.call_log)
        self.assertIn("db.close", dummy.call_log)
        self.assertIn("session.close", dummy.call_log)
        self.assertIn("app.quit", dummy.call_log)
        self.assertLess(dummy.call_log.index("tab.cleanup:AI"), dummy.call_log.index("db.close"))

    def test_news_tab_cleanup_is_idempotent_and_detaches_workers(self):
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab = NewsTab("AI", cast(Any, _FakeDb()), theme_mode=0)
        self.addCleanup(tab.deleteLater)

        worker = _FakeWorker(running=True, wait_result=True)
        job_worker = _FakeWorker(running=True, wait_result=False)
        tab.worker = cast(Any, worker)
        tab.job_worker = cast(Any, job_worker)

        tab.cleanup()
        tab.cleanup()

        self.assertTrue(tab._is_closing)
        self.assertEqual(worker.stop_calls, 1)
        self.assertGreaterEqual(worker.finished.disconnect_calls, 1)
        self.assertGreaterEqual(worker.error.disconnect_calls, 1)
        self.assertEqual(job_worker.stop_calls, 1)
        self.assertGreaterEqual(job_worker.finished.disconnect_calls, 1)
        self.assertGreaterEqual(job_worker.error.disconnect_calls, 1)
        self.assertEqual(job_worker.parent_values, [None])
        self.assertIsNone(tab.worker)
        self.assertIsNone(tab.job_worker)


if __name__ == "__main__":
    unittest.main()
