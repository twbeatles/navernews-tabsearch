import unittest
from pathlib import Path


class TestStartupRegistryCommand(unittest.TestCase):
    def test_source_mode_targets_entrypoint_script(self):
        src = Path("core/startup.py").read_text(encoding="utf-8")
        self.assertIn('entrypoint_path = os.path.join(APP_DIR, "news_scraper_pro.py")', src)
        self.assertIn('exe_path = f\'"{sys.executable}" "{entrypoint_path}"\'', src)
        self.assertNotIn("os.path.abspath(__file__)", src)

