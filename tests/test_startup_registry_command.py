import unittest
from unittest import mock
from pathlib import Path

import core.startup as startup


class TestStartupRegistryCommand(unittest.TestCase):
    def test_source_mode_targets_entrypoint_script(self):
        src = Path("core/startup.py").read_text(encoding="utf-8")
        self.assertIn('entrypoint_path = os.path.join(APP_DIR, "news_scraper_pro.py")', src)
        self.assertIn('command = f\'"{sys.executable}" "{entrypoint_path}"\'', src)
        self.assertNotIn("os.path.abspath(__file__)", src)

    def test_source_mode_command_supports_minimized_flag(self):
        with mock.patch.object(startup.sys, "frozen", False, create=True):
            with mock.patch.object(startup.sys, "executable", r"C:\Python311\python.exe"):
                cmd = startup.StartupManager.build_startup_command(start_minimized=True)
        self.assertTrue(cmd.startswith('"C:\\Python311\\python.exe" "'))
        self.assertIn('news_scraper_pro.py"', cmd)
        self.assertTrue(cmd.endswith(" --minimized"))

    def test_frozen_mode_command_is_quoted(self):
        exe_path = r"C:\Program Files\News Scraper Pro\NewsScraperPro.exe"
        with mock.patch.object(startup.sys, "frozen", True, create=True):
            with mock.patch.object(startup.sys, "executable", exe_path):
                cmd = startup.StartupManager.build_startup_command(start_minimized=True)
        self.assertEqual(cmd, f'"{exe_path}" --minimized')

