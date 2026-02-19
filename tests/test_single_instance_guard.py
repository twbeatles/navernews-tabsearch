import unittest
from pathlib import Path


class TestSingleInstanceGuard(unittest.TestCase):
    def test_bootstrap_has_single_instance_lock_guard(self):
        src = Path("core/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("QLockFile", src)
        self.assertIn("INSTANCE_LOCK_FILE", src)
        self.assertIn("tryLock(0)", src)
        self.assertIn("이미 실행 중", src)
        self.assertIn("sys.exit(0)", src)

