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
        self.deleted = False

    def start(self):
        self.started = True

    def deleteLater(self):
        self.deleted = True


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
    _begin_mark_all_read_maintenance = NewsTab._begin_mark_all_read_maintenance
    _release_mark_all_read_worker = NewsTab._release_mark_all_read_worker
    _end_mark_all_read_maintenance = NewsTab._end_mark_all_read_maintenance
    _finalize_mark_all_read = NewsTab._finalize_mark_all_read
    _on_mark_all_read_done = NewsTab._on_mark_all_read_done
    _on_mark_all_read_error = NewsTab._on_mark_all_read_error
    _on_mark_all_read_cancelled = NewsTab._on_mark_all_read_cancelled

    def __init__(self, parent=None):
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
        self._mark_all_mode_label = "탭 전체"
        self._mark_all_maintenance_active = False
        self._parent = parent
        self._is_closing = False

    def _current_date_range(self):
        return "2026-01-01", "2026-01-31"

    def _current_filter_text(self):
        return "launch"

    def _main_window(self):
        return self._parent

    def load_data_from_db(self):
        self.loaded = True


class _FakeMainWindow:
    def __init__(self, start_result=(True, "")):
        self.start_result = start_result
        self.events = []

    def begin_database_maintenance(self, operation):
        self.events.append(("begin", operation))
        return self.start_result

    def end_database_maintenance(self):
        self.events.append(("end",))

    def on_database_maintenance_completed(self, operation, affected_count=0):
        self.events.append(("complete", operation, affected_count))

    def show_toast(self, message):
        self.events.append(("toast", str(message)))

    def show_warning_toast(self, message):
        self.events.append(("warning", str(message)))

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

    def test_mark_all_read_enters_maintenance_and_releases_it_before_ui_sync(self):
        parent = _FakeMainWindow()
        dummy = _DummyNewsTab(parent=parent)
        fake_message_box = _FakeMessageBoxInstance("탭 전체")

        with mock.patch("ui.news_tab.QMessageBox") as message_box_cls:
            message_box_cls.return_value = fake_message_box
            message_box_cls.Icon = SimpleNamespace(Question=1)
            message_box_cls.ButtonRole = SimpleNamespace(AcceptRole=1, ActionRole=2)
            message_box_cls.StandardButton = SimpleNamespace(Cancel=0)
            with mock.patch("ui.news_tab.IterativeJobWorker", _FakeWorker):
                dummy.mark_all_read()

        self.assertEqual(parent.events, [("begin", "mark_all_read")])
        worker = dummy.job_worker
        self.assertIsNotNone(worker)
        assert isinstance(worker, _FakeWorker)
        dummy._on_mark_all_read_done(5)

        self.assertIsNone(dummy.job_worker)
        self.assertTrue(worker.deleted)
        self.assertEqual(parent.events[1:4], [("end",), ("complete", "mark_all_read", 5), ("toast", "✓ 탭 전체 5개의 기사를 읽음으로 표시했습니다.")])

    def test_mark_all_read_does_not_start_when_parent_cannot_enter_maintenance(self):
        parent = _FakeMainWindow(start_result=(False, "busy"))
        dummy = _DummyNewsTab(parent=parent)
        fake_message_box = _FakeMessageBoxInstance("탭 전체")

        with mock.patch("ui.news_tab.QMessageBox") as message_box_cls:
            message_box_cls.return_value = fake_message_box
            message_box_cls.Icon = SimpleNamespace(Question=1)
            message_box_cls.ButtonRole = SimpleNamespace(AcceptRole=1, ActionRole=2)
            message_box_cls.StandardButton = SimpleNamespace(Cancel=0)
            with mock.patch("ui.news_tab.IterativeJobWorker", _FakeWorker):
                dummy.mark_all_read()

        self.assertIsNone(dummy.job_worker)
        self.assertEqual(parent.events, [("begin", "mark_all_read")])
        message_box_cls.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
