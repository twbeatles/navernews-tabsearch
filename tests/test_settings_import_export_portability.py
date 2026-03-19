import inspect
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from ui._main_window_settings_io import _MainWindowSettingsIOMixin
from ui.main_window import MainApp


class _DummyImportMain:
    def __init__(self):
        self.warning_toasts = []

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def _reconcile_startup_state_from_import(self, normalized_settings, warnings):
        return cast(Any, _MainWindowSettingsIOMixin)._reconcile_startup_state_from_import(
            cast(Any, self),
            normalized_settings,
            warnings,
        )


class TestSettingsImportExportPortability(unittest.TestCase):
    def test_export_settings_includes_auto_start_and_schema_1_2(self):
        src = Path("ui/_main_window_settings_io.py").read_text(encoding="utf-8")
        self.assertIn('"export_version": "1.2"', src)
        self.assertIn('"auto_start_enabled": self.auto_start_enabled', src)

    def test_import_settings_uses_startup_reconcile_helper(self):
        block = inspect.getsource(MainApp.import_settings)
        self.assertIn("self._reconcile_startup_state_from_import(normalized_settings, import_warnings)", block)

    def test_reconcile_startup_forces_false_when_platform_is_unavailable(self):
        dummy = _DummyImportMain()
        normalized_settings = {"auto_start_enabled": True, "start_minimized": False}
        warnings = []

        with mock.patch("ui._main_window_settings_io.StartupManager.is_available", return_value=False):
            dummy._reconcile_startup_state_from_import(normalized_settings, warnings)

        self.assertFalse(normalized_settings["auto_start_enabled"])
        self.assertTrue(any("auto_start_enabled" in warning for warning in warnings))
        self.assertEqual(len(dummy.warning_toasts), 1)

    def test_reconcile_startup_calls_enable_and_disable_helpers(self):
        dummy = _DummyImportMain()

        with mock.patch("ui._main_window_settings_io.StartupManager.is_available", return_value=True):
            with mock.patch("ui._main_window_settings_io.StartupManager.enable_startup", return_value=True) as enable_mock:
                normalized_settings = {"auto_start_enabled": True, "start_minimized": True}
                warnings = []
                dummy._reconcile_startup_state_from_import(normalized_settings, warnings)
                enable_mock.assert_called_once_with(True)
                self.assertEqual(warnings, [])

            with mock.patch("ui._main_window_settings_io.StartupManager.disable_startup", return_value=True) as disable_mock:
                normalized_settings = {"auto_start_enabled": False, "start_minimized": False}
                warnings = []
                dummy._reconcile_startup_state_from_import(normalized_settings, warnings)
                disable_mock.assert_called_once_with()
                self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
