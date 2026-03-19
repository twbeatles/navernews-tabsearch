import unittest
from typing import Any, cast
from unittest import mock

from ui.settings_dialog import SettingsDialog


class _DummyParent:
    def __init__(self):
        self.calls = []
        self.maintenance_started = []
        self.maintenance_ended = 0
        self.start_result: tuple[bool, str] = (True, "")

    def begin_database_maintenance(self, operation):
        self.maintenance_started.append(operation)
        return self.start_result

    def end_database_maintenance(self):
        self.maintenance_ended += 1

    def on_database_maintenance_completed(self, operation, affected_count):
        self.calls.append((operation, affected_count))

    def export_settings(self):
        pass

    def import_settings(self):
        pass

    def show_log_viewer(self):
        pass

    def show_keyword_groups(self):
        pass


class _DummySettingsDialog:
    _notify_parent_data_changed = SettingsDialog._notify_parent_data_changed
    _start_data_task = cast(Any, SettingsDialog._start_data_task)
    _on_data_task_finished = cast(Any, SettingsDialog._on_data_task_finished)

    def __init__(self):
        self._is_closing = False
        self._maintenance_active_for_data_task = False
        self._parent = _DummyParent()
        self.btn_clean = mock.Mock()
        self.btn_all = mock.Mock()
        self._data_task_worker = None

    def parent(self):
        return self._parent

    def _typed_parent(self):
        return self._parent

    def isVisible(self):
        return True

    def _create_worker(self, _job_func):
        raise AssertionError("worker should not be created in this test")


class TestSettingsDialogMaintenanceHooks(unittest.TestCase):
    def test_clean_data_done_notifies_parent_refresh_hook(self):
        dialog = _DummySettingsDialog()

        with mock.patch("ui.settings_dialog.QMessageBox.information"):
            SettingsDialog._on_clean_data_done(cast(Any, dialog), 3)

        self.assertEqual(dialog._parent.calls, [("delete_old_news", 3)])

    def test_clean_all_done_notifies_parent_refresh_hook(self):
        dialog = _DummySettingsDialog()

        with mock.patch("ui.settings_dialog.QMessageBox.information"):
            SettingsDialog._on_clean_all_done(cast(Any, dialog), 7)

        self.assertEqual(dialog._parent.calls, [("delete_all_news", 7)])

    def test_start_data_task_blocks_when_parent_cannot_enter_maintenance(self):
        dialog = _DummySettingsDialog()
        dialog._parent.start_result = (False, "busy")

        with mock.patch("ui.settings_dialog.QMessageBox.warning") as warning_mock:
            dialog._start_data_task(lambda: 1, lambda _result: None, "delete_old_news")

        warning_mock.assert_called_once()
        self.assertEqual(dialog._parent.maintenance_started, ["delete_old_news"])
        self.assertFalse(dialog._maintenance_active_for_data_task)
        self.assertIsNone(dialog._data_task_worker)

    def test_data_task_finished_releases_parent_maintenance(self):
        dialog = _DummySettingsDialog()
        dialog._maintenance_active_for_data_task = True

        dialog._on_data_task_finished()

        self.assertEqual(dialog._parent.maintenance_ended, 1)
        self.assertFalse(dialog._maintenance_active_for_data_task)


if __name__ == "__main__":
    unittest.main()
