import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.api_quota import (
    DAILY_API_CALL_LIMIT,
    DailyApiQuotaTracker,
)


class TestDailyApiQuotaTracker(unittest.TestCase):
    def test_records_and_reports_remaining(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = DailyApiQuotaTracker(str(Path(td) / "quota.json"))
            count, remaining = tracker.record_call()
            self.assertEqual(count, 1)
            self.assertEqual(remaining, DAILY_API_CALL_LIMIT - 1)
            self.assertFalse(tracker.is_exhausted)
            date, count2, remaining2 = tracker.usage()
            self.assertEqual(date, datetime.now().date().isoformat())
            self.assertEqual(count2, 1)
            self.assertEqual(remaining2, DAILY_API_CALL_LIMIT - 1)

    def test_state_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "quota.json")
            first = DailyApiQuotaTracker(path)
            first.record_call(3)
            second = DailyApiQuotaTracker(path)
            self.assertEqual(second.count, 3)
            self.assertIn("3", second.summary_text())
            self.assertIn("25,000", second.summary_text())

    def test_exhausted_at_daily_limit(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = DailyApiQuotaTracker(str(Path(td) / "quota.json"))
            tracker.record_call(DAILY_API_CALL_LIMIT - 1)
            self.assertFalse(tracker.is_exhausted)
            tracker.record_call()
            self.assertTrue(tracker.is_exhausted)
            self.assertEqual(tracker.remaining, 0)

    def test_warns_once_at_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "quota.json")
            tracker = DailyApiQuotaTracker(path)
            tracker.record_call(int(DAILY_API_CALL_LIMIT * 0.8) - 1)
            self.assertFalse(tracker.should_warn())
            tracker.record_call()
            self.assertTrue(tracker.should_warn())
            # Second call must not warn again, even across instances.
            self.assertFalse(tracker.should_warn())
            reloaded = DailyApiQuotaTracker(path)
            self.assertFalse(reloaded.should_warn())

    def test_rolls_over_on_new_day(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "quota.json"
            yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
            path.write_text(
                json.dumps({"date": yesterday, "count": 100, "warned": True}),
                encoding="utf-8",
            )
            tracker = DailyApiQuotaTracker(str(path))
            # Stale state is dropped on first read.
            self.assertEqual(tracker.count, 0)
            self.assertFalse(tracker.is_exhausted)
            date, count, _remaining = tracker.usage()
            self.assertEqual(date, datetime.now().date().isoformat())
            self.assertEqual(count, 0)

    def test_corrupt_state_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "quota.json"
            path.write_text("not json", encoding="utf-8")
            tracker = DailyApiQuotaTracker(str(path))
            self.assertEqual(tracker.count, 0)
            tracker.record_call()
            self.assertEqual(tracker.count, 1)


if __name__ == "__main__":
    unittest.main()
