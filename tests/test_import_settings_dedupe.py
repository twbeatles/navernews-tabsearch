import unittest
from pathlib import Path


class TestImportSettingsDedupe(unittest.TestCase):
    def test_import_uses_set_and_updates_seen_keywords(self):
        src = Path("ui/main_window.py").read_text(encoding="utf-8")
        start = src.index("def import_settings")
        end = src.index("def show_statistics")
        block = src[start:end]

        self.assertIn("existing_keywords = {", block)
        self.assertIn("existing_keywords.add(keyword)", block)
        self.assertIn("if keyword and keyword not in existing_keywords", block)

