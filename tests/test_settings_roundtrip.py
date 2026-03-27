import ast
import inspect
import unittest
from pathlib import Path
from typing import Any, cast

from ui._settings_dialog_content import _SettingsDialogContentMixin
from ui.settings_dialog import SettingsDialog


class TestSettingsRoundtripContract(unittest.TestCase):
    def test_get_data_contains_sound_api_timeout_and_minimize(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        module = ast.parse(src)
        cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
        get_data = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "get_data")

        return_node = next(node for node in ast.walk(get_data) if isinstance(node, ast.Return))
        self.assertIsNotNone(return_node.value)
        self.assertIsInstance(return_node.value, ast.Dict)
        assert return_node.value is not None
        assert isinstance(return_node.value, ast.Dict)
        return_value = return_node.value
        keys = {
            key.value
            for key in return_value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertIn("sound_enabled", keys)
        self.assertIn("api_timeout", keys)
        self.assertIn("minimize_to_tray", keys)

    def test_api_timeout_spinbox_is_present(self):
        src = inspect.getsource(cast(Any, _SettingsDialogContentMixin)._build_general_group)
        self.assertIn("QSpinBox", src)
        self.assertIn("setRange(5, 60)", src)

    def test_interval_options_use_two_hours(self):
        src = inspect.getsource(cast(Any, _SettingsDialogContentMixin)._build_general_group)
        self.assertIn("2시간", src)
        self.assertNotIn("3시간", src)

    def test_worker_creation_uses_common_factory_and_parent_none(self):
        src = inspect.getsource(SettingsDialog._create_worker)
        self.assertIn("def _create_worker", src)
        self.assertIn("AsyncJobWorker(job_func, parent=None)", src)
        self.assertIn("worker.finished.connect(worker.deleteLater)", src)

    def test_shutdown_worker_detaches_parent_when_wait_times_out(self):
        block = inspect.getsource(SettingsDialog._shutdown_worker)
        self.assertIn("worker.wait(wait_ms)", block)
        self.assertIn("worker.setParent(None)", block)
        self.assertIn("worker.finished.connect(worker.deleteLater)", block)

    def test_settings_dialog_supports_help_mode(self):
        src = inspect.getsource(SettingsDialog.__init__)
        self.assertIn("help_mode: bool = False", src)
        self.assertIn('self.setWindowTitle("도움말" if self._help_mode else "설정 및 도움말")', src)
