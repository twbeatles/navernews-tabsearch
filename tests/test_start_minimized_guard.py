import unittest

from ui.main_window import should_start_minimized


class TestStartMinimizedGuard(unittest.TestCase):
    def test_start_minimized_requires_tray_support(self):
        self.assertTrue(should_start_minimized(True, True))
        self.assertFalse(should_start_minimized(True, False))
        self.assertFalse(should_start_minimized(False, True))
        self.assertFalse(should_start_minimized(False, False))

