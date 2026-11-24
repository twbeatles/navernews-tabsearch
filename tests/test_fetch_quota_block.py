import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from core.api_quota import DAILY_API_CALL_LIMIT, DailyApiQuotaTracker
from ui.main_window_fetch_support.worker_flow_support.completion import (
    _FetchWorkerCompletionMixin,
)
from ui.main_window_fetch_support.worker_flow_support.start import (
    _FetchWorkerStartMixin,
)


class _QuotaStub:
    def __init__(self, exhausted: bool = False):
        self.is_exhausted = exhausted
        self.recorded = 0

    def record_call(self, count: int = 1):
        self.recorded += count
        return self.recorded, 0


class _FetchQuotaDummy:
    _shutdown_in_progress = False
    client_id = "x" * 12
    client_secret = "y" * 12

    def __init__(self, quota: Any):
        self._api_quota = quota
        self.messages: list[str] = []
        self.toasts: list[str] = []

    def is_maintenance_mode_active(self) -> bool:
        return False

    def _status_bar(self):
        dummy = self

        class _Bar:
            def showMessage(self, msg: str, _ms: int = 0) -> None:
                dummy.messages.append(str(msg))

        return _Bar()

    def show_warning_toast(self, msg: str) -> None:
        self.toasts.append(str(msg))


class TestFetchQuotaBlock(unittest.TestCase):
    def test_fetch_news_is_blocked_when_quota_exhausted(self):
        dummy = _FetchQuotaDummy(_QuotaStub(exhausted=True))

        result = cast(Any, _FetchWorkerStartMixin).fetch_news(dummy, "삼성전자")

        self.assertIsNone(result)
        self.assertTrue(any("25,000" in msg for msg in dummy.messages))
        self.assertTrue(any("자정" in toast for toast in dummy.toasts))

    def test_fetch_news_passes_quota_check_when_available(self):
        dummy = _FetchQuotaDummy(_QuotaStub(exhausted=False))
        # Blocked later by the missing-worker stub, but must pass the quota gate.
        with self.assertRaises(AttributeError):
            cast(Any, _FetchWorkerStartMixin).fetch_news(dummy, "삼성전자")
        self.assertFalse(any("25,000" in msg for msg in dummy.messages))

    def test_quota_warning_surfaces_once_at_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = DailyApiQuotaTracker(str(Path(td) / "quota.json"))
            tracker.record_call(int(DAILY_API_CALL_LIMIT * 0.8))
            dummy = _FetchQuotaDummy(tracker)

            cast(Any, _FetchWorkerCompletionMixin)._maybe_warn_api_quota(dummy)

            self.assertTrue(any("잔여" in msg for msg in dummy.messages))
            self.assertTrue(any("잔여" in toast for toast in dummy.toasts))
            # Second check must stay silent.
            dummy2 = _FetchQuotaDummy(tracker)
            cast(Any, _FetchWorkerCompletionMixin)._maybe_warn_api_quota(dummy2)
            self.assertEqual(dummy2.messages, [])
            self.assertEqual(dummy2.toasts, [])


if __name__ == "__main__":
    unittest.main()
