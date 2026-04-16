import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from ui.news_tab import NewsTab


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _FakeWorker:
    def __init__(self, job_func, *args, **kwargs):
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.cancelled = _FakeSignal()
        self.progress = _FakeSignal()
        self.started = False

    def start(self):
        self.started = True


class _FakeMessageBoxInstance:
    def __init__(self, clicked_button):
        self._clicked_button = clicked_button

    def setIcon(self, *_args):
        pass

    def setWindowTitle(self, *_args):
        pass

    def setText(self, *_args):
        pass

    def setInformativeText(self, *_args):
        pass

    def addButton(self, label, _role=None):
        return label

    def setDefaultButton(self, *_args):
        pass

    def exec(self):
        pass

    def clickedButton(self):
        return self._clicked_button


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = str(text)


class _FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class _FakeCheck:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _DummyNewsTab:
    mark_all_read = NewsTab.mark_all_read

    def __init__(self):
        self.lbl_status = _FakeLabel()
        self.btn_read_all = _FakeButton()
        self.chk_hide_dup = _FakeCheck(True)
        self._total_filtered_count = 42
        self.db_keyword = "AI"
        self.exclude_words = ["coin"]
        self.is_bookmark_tab = False
        self.query_key = "ai launch|coin"
        self.db = SimpleNamespace(mark_query_as_read_chunked=mock.Mock(return_value=42))
        self.job_worker = None

    def _current_date_range(self):
        return "2026-01-01", "2026-01-31"

    def _current_filter_text(self):
        return "launch"

    def _main_window(self):
        return None

    def _on_mark_all_read_done(self, _count):
        pass

    def _on_mark_all_read_error(self, _err_msg):
        pass

    def _on_mark_all_read_cancelled(self):
        pass


class _FakeContext:
    def __init__(self):
        self.reports = []

    def check_cancelled(self):
        return None

    def report(self, **kwargs):
        self.reports.append(dict(kwargs))


class TestNewsTabMarkAllReadScope(unittest.TestCase):
    def test_visible_only_mode_uses_full_db_filter_scope(self):
        dummy = _DummyNewsTab()
        fake_message_box = _FakeMessageBoxInstance("현재 표시 결과만")

        with mock.patch("ui.news_tab.QMessageBox") as message_box_cls:
            message_box_cls.return_value = fake_message_box
            message_box_cls.Icon = SimpleNamespace(Question=1)
            message_box_cls.ButtonRole = SimpleNamespace(AcceptRole=1, ActionRole=2)
            message_box_cls.StandardButton = SimpleNamespace(Cancel=0)
            with mock.patch("ui.news_tab.IterativeJobWorker", _FakeWorker):
                dummy.mark_all_read()

        self.assertIsNotNone(dummy.job_worker)
        assert isinstance(dummy.job_worker, _FakeWorker)
        context = _FakeContext()
        result = dummy.job_worker.job_func(context)
        self.assertEqual(result, 42)
        dummy.db.mark_query_as_read_chunked.assert_called_once()
        _, kwargs = dummy.db.mark_query_as_read_chunked.call_args
        self.assertEqual(kwargs["keyword"], "AI")
        self.assertEqual(kwargs["exclude_words"], ["coin"])
        self.assertEqual(kwargs["only_bookmark"], False)
        self.assertEqual(kwargs["filter_txt"], "launch")
        self.assertEqual(kwargs["hide_duplicates"], True)
        self.assertEqual(kwargs["start_date"], "2026-01-01")
        self.assertEqual(kwargs["end_date"], "2026-01-31")
        self.assertEqual(kwargs["query_key"], "ai launch|coin")
        self.assertEqual(kwargs["chunk_size"], 200)
        self.assertTrue(callable(kwargs["progress_callback"]))
        self.assertTrue(callable(kwargs["cancel_check"]))
        self.assertTrue(dummy.job_worker.started)


if __name__ == "__main__":
    unittest.main()
