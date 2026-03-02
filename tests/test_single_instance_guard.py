import unittest
from pathlib import Path

from core.bootstrap import _resolve_single_instance_conflict


class _FakeLock:
    def __init__(self, try_lock_result: bool, remove_raises: bool = False):
        self.try_lock_result = try_lock_result
        self.remove_raises = remove_raises
        self.remove_called = 0
        self.try_lock_calls = []

    def removeStaleLockFile(self):
        self.remove_called += 1
        if self.remove_raises:
            raise RuntimeError("remove failed")

    def tryLock(self, timeout: int):
        self.try_lock_calls.append(timeout)
        return self.try_lock_result


class TestSingleInstanceGuard(unittest.TestCase):
    def test_bootstrap_has_single_instance_lock_guard(self):
        src = Path("core/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("QLockFile", src)
        self.assertIn("QLocalServer", src)
        self.assertIn("QLocalSocket", src)
        self.assertIn("INSTANCE_LOCK_FILE", src)
        self.assertIn("INSTANCE_SERVER_NAME", src)
        self.assertIn("instance_lock.setStaleLockTime(10000)", src)
        self.assertIn("_resolve_single_instance_conflict(", src)
        self.assertIn("_setup_instance_server(", src)
        self.assertIn("window.show_window()", src)
        self.assertIn("QMessageBox.StandardButton.Retry", src)
        self.assertIn("single_instance|status=%s", src)
        self.assertNotIn("waitForReadyRead(", src)

    def test_resolve_conflict_notify_success(self):
        lock = _FakeLock(try_lock_result=False)
        state = _resolve_single_instance_conflict(lock, notifier=lambda: True)
        self.assertEqual(state, "notify_success")
        self.assertEqual(lock.remove_called, 0)
        self.assertEqual(lock.try_lock_calls, [])

    def test_resolve_conflict_stale_recovered_after_notify_fail(self):
        lock = _FakeLock(try_lock_result=True)
        state = _resolve_single_instance_conflict(lock, notifier=lambda: False)
        self.assertEqual(state, "stale_recovered")
        self.assertEqual(lock.remove_called, 1)
        self.assertEqual(lock.try_lock_calls, [0])

    def test_resolve_conflict_blocked_when_relock_fails(self):
        lock = _FakeLock(try_lock_result=False)
        state = _resolve_single_instance_conflict(lock, notifier=lambda: False)
        self.assertEqual(state, "blocked")
        self.assertEqual(lock.remove_called, 1)
        self.assertEqual(lock.try_lock_calls, [0])

    def test_resolve_conflict_ignores_remove_error_and_retries_lock_once(self):
        lock = _FakeLock(try_lock_result=True, remove_raises=True)
        state = _resolve_single_instance_conflict(lock, notifier=lambda: False)
        self.assertEqual(state, "stale_recovered")
        self.assertEqual(lock.remove_called, 1)
        self.assertEqual(lock.try_lock_calls, [0])
