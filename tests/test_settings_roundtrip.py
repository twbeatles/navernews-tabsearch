import ast
import unittest
from pathlib import Path


class TestSettingsRoundtripContract(unittest.TestCase):
    def test_get_data_contains_sound_api_timeout_and_minimize(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        module = ast.parse(src)
        cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
        get_data = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "get_data")

        return_node = next(node for node in ast.walk(get_data) if isinstance(node, ast.Return))
        self.assertIsInstance(return_node.value, ast.Dict)
        keys = {
            key.value
            for key in return_node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertIn("sound_enabled", keys)
        self.assertIn("api_timeout", keys)
        self.assertIn("minimize_to_tray", keys)

    def test_api_timeout_spinbox_is_present(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn("QSpinBox", src)
        self.assertIn("setRange(5, 60)", src)

    def test_interval_options_use_two_hours(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn("2시간", src)
        self.assertNotIn("3시간", src)

    def test_worker_creation_uses_common_factory_and_parent_none(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn("def _create_worker", src)
        self.assertIn("AsyncJobWorker(job_func, parent=None)", src)
        self.assertIn("worker.finished.connect(worker.deleteLater)", src)

    def test_shutdown_worker_detaches_parent_when_wait_times_out(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        start = src.index("def _shutdown_worker")
        end = src.index("def _create_worker")
        block = src[start:end]
        self.assertIn("worker.wait(wait_ms)", block)
        self.assertIn("worker.setParent(None)", block)
        self.assertIn("worker.finished.connect(worker.deleteLater)", block)
