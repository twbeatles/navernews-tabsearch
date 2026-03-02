import unittest
from pathlib import Path


class TestEncodingSmoke(unittest.TestCase):
    def test_known_broken_token_removed_from_news_tab(self):
        src = Path("ui/news_tab.py").read_text(encoding="utf-8")
        self.assertNotIn("?ㅻ쪟", src)

    def test_no_replacement_char_in_core_and_ui_python_sources(self):
        bad_files = []
        for base_dir in ("core", "ui"):
            for path in Path(base_dir).glob("*.py"):
                src = path.read_text(encoding="utf-8")
                if "\ufffd" in src:
                    bad_files.append(str(path))
        self.assertEqual(
            bad_files,
            [],
            msg=f"UTF-8 replacement character found in: {', '.join(bad_files)}",
        )

