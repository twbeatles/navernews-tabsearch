import time
import unittest

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

from core.workers import connect_qthread_finished, delete_qthread_when_finished

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _ResultSignalThread(QThread):
    finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.delete_later_calls = 0

    def run(self):
        return

    def deleteLater(self):  # noqa: N802 - Qt API spelling
        self.delete_later_calls += 1


class TestQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _pump_until(self, ready, timeout_s=5.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.app.processEvents()
            if ready():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return ready()

    def test_connect_qthread_finished_ignores_shadowed_result_signal(self):
        worker = _ResultSignalThread()
        calls: list[str] = []

        self.assertTrue(connect_qthread_finished(worker, lambda: calls.append("thread-finished")))

        worker.finished.emit({"result": True})
        self.app.processEvents()
        self.assertEqual(calls, [])

        # PySide6 cannot emit the shadowed native finished() from Python, so
        # drive a real thread completion instead.
        worker.start()
        self.assertTrue(worker.wait(5000))
        self.assertTrue(self._pump_until(lambda: calls == ["thread-finished"]))
        self.assertEqual(calls, ["thread-finished"])

    def test_delete_qthread_when_finished_waits_for_native_finished_signal(self):
        worker = _ResultSignalThread()

        self.assertTrue(delete_qthread_when_finished(worker))

        worker.finished.emit({"result": True})
        self.app.processEvents()
        self.assertEqual(worker.delete_later_calls, 0)

        # PySide6 cannot emit the shadowed native finished() from Python, so
        # drive a real thread completion instead.
        worker.start()
        self.assertTrue(worker.wait(5000))
        self.assertTrue(self._pump_until(lambda: worker.delete_later_calls == 1))
        self.assertEqual(worker.delete_later_calls, 1)


if __name__ == "__main__":
    unittest.main()
