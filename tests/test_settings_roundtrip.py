import ast
import unittest
from pathlib import Path


class TestSettingsRoundtripContract(unittest.TestCase):
    def test_get_data_contains_sound_and_api_timeout(self):
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

    def test_api_timeout_spinbox_is_present(self):
        src = Path("ui/settings_dialog.py").read_text(encoding="utf-8")
        self.assertIn("QSpinBox", src)
        self.assertIn("setRange(5, 60)", src)

