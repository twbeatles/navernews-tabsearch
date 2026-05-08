import unittest

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.workers import connect_qthread_finished, delete_qthread_when_finished

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _ResultSignalThread(QThread):
    finished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.delete_later_calls = 0

    def deleteLater(self):  # noqa: N802 - Qt API spelling
        self.delete_later_calls += 1


class TestQThreadLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_connect_qthread_finished_ignores_shadowed_result_signal(self):
        worker = _ResultSignalThread()
        calls: list[str] = []

        self.assertTrue(connect_qthread_finished(worker, lambda: calls.append("thread-finished")))

        worker.finished.emit({"result": True})
        self.app.processEvents()
        self.assertEqual(calls, [])

        QThread.finished.__get__(worker, type(worker)).emit()
        self.app.processEvents()
        self.assertEqual(calls, ["thread-finished"])

    def test_delete_qthread_when_finished_waits_for_native_finished_signal(self):
        worker = _ResultSignalThread()

        self.assertTrue(delete_qthread_when_finished(worker))

        worker.finished.emit({"result": True})
        self.app.processEvents()
        self.assertEqual(worker.delete_later_calls, 0)

        QThread.finished.__get__(worker, type(worker)).emit()
        self.app.processEvents()
        self.assertEqual(worker.delete_later_calls, 1)


if __name__ == "__main__":
    unittest.main()
