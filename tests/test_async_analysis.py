import inspect
import unittest

from ui.main_window import MainApp


class TestAsyncAnalysis(unittest.TestCase):
    def test_show_statistics_uses_interruptible_read_worker(self):
        block = inspect.getsource(MainApp.show_statistics)
        self.assertIn("InterruptibleReadWorker", block)
        self.assertIn("dialog.finished.connect", block)

    def test_show_stats_analysis_uses_interruptible_workers_and_stale_guard(self):
        block = inspect.getsource(MainApp.show_stats_analysis)
        self.assertIn("InterruptibleReadWorker", block)
        self.assertIn("publisher_request_id", block)
        self.assertIn("dialog.finished.connect", block)


if __name__ == "__main__":
    unittest.main()
