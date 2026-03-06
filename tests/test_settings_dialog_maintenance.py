import unittest
from unittest import mock

from ui.settings_dialog import SettingsDialog


class _DummyParent:
    def __init__(self):
        self.calls = []

    def on_database_maintenance_completed(self, operation, affected_count):
        self.calls.append((operation, affected_count))


class _DummySettingsDialog:
    _notify_parent_data_changed = SettingsDialog._notify_parent_data_changed

    def __init__(self):
        self._is_closing = False
        self._parent = _DummyParent()

    def parent(self):
        return self._parent

    def isVisible(self):
        return True


class TestSettingsDialogMaintenanceHooks(unittest.TestCase):
    def test_clean_data_done_notifies_parent_refresh_hook(self):
        dialog = _DummySettingsDialog()

        with mock.patch("ui.settings_dialog.QMessageBox.information"):
            SettingsDialog._on_clean_data_done(dialog, 3)

        self.assertEqual(dialog._parent.calls, [("delete_old_news", 3)])

    def test_clean_all_done_notifies_parent_refresh_hook(self):
        dialog = _DummySettingsDialog()

        with mock.patch("ui.settings_dialog.QMessageBox.information"):
            SettingsDialog._on_clean_all_done(dialog, 7)

        self.assertEqual(dialog._parent.calls, [("delete_all_news", 7)])


if __name__ == "__main__":
    unittest.main()
