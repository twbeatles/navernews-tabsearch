import unittest
from typing import Any, Optional, cast
from unittest import mock
from pathlib import Path

from core.constants import get_runtime_paths
from ui.settings_dialog import SettingsDialog


class _DummyParent:
    def __init__(self):
        self.calls = []
        self.events = []
        self.maintenance_started = []
        self.maintenance_ended = 0
        self.maintenance_active = False
        self.start_result: tuple[bool, str] = (True, "")
        self.runtime_paths = get_runtime_paths(data_dir=str(Path.cwd() / ".pytest_tmp" / "custom-runtime"))

    def begin_database_maintenance(self, operation):
        self.maintenance_started.append(operation)
        self.events.append(("begin", operation))
        if self.start_result[0]:
            self.maintenance_active = True
        return self.start_result

    def end_database_maintenance(self):
        self.maintenance_ended += 1
        self.maintenance_active = False
        self.events.append(("end",))

    def on_database_maintenance_completed(self, operation, affected_count):
        self.calls.append((operation, affected_count))
        self.events.append(("complete", operation, affected_count, self.maintenance_active))

    def export_settings(self):
        pass

    def import_settings(self):
        pass

    def show_log_viewer(self):
        pass

    def show_keyword_groups(self):
        pass


class _DummySettingsDialog:
    _runtime_paths = cast(Any, SettingsDialog._runtime_paths)
    _notify_parent_data_changed = SettingsDialog._notify_parent_data_changed
    _start_data_task = cast(Any, SettingsDialog._start_data_task)
    _on_data_task_finished = cast(Any, SettingsDialog._on_data_task_finished)
    open_data_folder = cast(Any, SettingsDialog.open_data_folder)

    def __init__(self):
        self._is_closing = False
        self._maintenance_active_for_data_task = False
        self._pending_parent_data_change: Optional[tuple[str, int]] = None
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
    def test_clean_data_done_flushes_parent_refresh_after_maintenance_ends(self):
        dialog = _DummySettingsDialog()
        dialog._maintenance_active_for_data_task = True
        dialog._parent.maintenance_active = True

        with mock.patch("ui._settings_dialog_tasks.QMessageBox.information"):
            SettingsDialog._on_clean_data_done(cast(Any, dialog), 3)

        self.assertEqual(dialog._parent.calls, [])
        self.assertEqual(dialog._pending_parent_data_change, ("delete_old_news", 3))
        dialog._on_data_task_finished()
        self.assertEqual(dialog._parent.calls, [("delete_old_news", 3)])
        self.assertEqual(
            dialog._parent.events[-2:],
            [("end",), ("complete", "delete_old_news", 3, False)],
        )
        self.assertIsNone(dialog._pending_parent_data_change)

    def test_clean_all_done_flushes_parent_refresh_after_maintenance_ends(self):
        dialog = _DummySettingsDialog()
        dialog._maintenance_active_for_data_task = True
        dialog._parent.maintenance_active = True

        with mock.patch("ui._settings_dialog_tasks.QMessageBox.information"):
            SettingsDialog._on_clean_all_done(cast(Any, dialog), 7)

        self.assertEqual(dialog._parent.calls, [])
        dialog._on_data_task_finished()
        self.assertEqual(dialog._parent.calls, [("delete_all_news", 7)])

    def test_start_data_task_blocks_when_parent_cannot_enter_maintenance(self):
        dialog = _DummySettingsDialog()
        dialog._parent.start_result = (False, "busy")

        with mock.patch("ui._settings_dialog_tasks.QMessageBox.warning") as warning_mock:
            dialog._start_data_task(lambda: 1, lambda _result: None, "delete_old_news")

        warning_mock.assert_called_once()
        self.assertEqual(dialog._parent.maintenance_started, ["delete_old_news"])
        self.assertFalse(dialog._maintenance_active_for_data_task)
        self.assertIsNone(dialog._data_task_worker)

    def test_data_task_finished_releases_parent_maintenance(self):
        dialog = _DummySettingsDialog()
        dialog._maintenance_active_for_data_task = True
        dialog._parent.maintenance_active = True

        dialog._on_data_task_finished()

        self.assertEqual(dialog._parent.maintenance_ended, 1)
        self.assertFalse(dialog._maintenance_active_for_data_task)

    def test_error_and_cancel_clear_pending_parent_refresh(self):
        dialog = _DummySettingsDialog()
        dialog._pending_parent_data_change = ("delete_old_news", 5)

        with mock.patch("ui._settings_dialog_tasks.QMessageBox.critical"):
            SettingsDialog._on_data_task_error(cast(Any, dialog), "boom")
        self.assertIsNone(dialog._pending_parent_data_change)

        dialog._pending_parent_data_change = ("delete_all_news", 9)
        with mock.patch("ui._settings_dialog_tasks.QMessageBox.information"):
            SettingsDialog._on_data_task_cancelled(cast(Any, dialog))
        self.assertIsNone(dialog._pending_parent_data_change)

    def test_open_data_folder_prefers_parent_runtime_paths(self):
        dialog = _DummySettingsDialog()
        with mock.patch("ui._settings_dialog_tasks.QDesktopServices.openUrl") as open_url:
            dialog.open_data_folder()
        open_url.assert_called_once()
        self.assertIn("custom-runtime", open_url.call_args.args[0].toLocalFile().replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
