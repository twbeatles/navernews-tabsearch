import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.database import DatabaseManager
from core.query_parser import build_fetch_key
from ui.main_window import MainApp


class _FakeRetryTimer:
    def __init__(self):
        self.active = False
        self.last_delay = -1
        self.start_calls = []

    def isActive(self):
        return self.active

    def start(self, delay_ms):
        self.active = True
        self.last_delay = int(delay_ms)
        self.start_calls.append(self.last_delay)

    def stop(self):
        self.active = False

    def remainingTime(self):
        return self.last_delay if self.active else -1


class _FakeSignal:
    def connect(self, _callback):
        return None


class _FakeIterativeWorker:
    def __init__(self, _job_func, parent=None):
        self.parent = parent
        self.running = False
        self.interruption_requested = False
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.cancelled = _FakeSignal()

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def requestInterruption(self):
        self.interruption_requested = True
        self.running = False


class _FakeFtsDb:
    def __init__(self, *, complete=False):
        self.complete = complete

    def is_news_fts_backfill_complete(self):
        return self.complete

    def backfill_news_fts_chunk(self, limit=250):
        return {"processed": int(limit), "done": True}


class _DummyFtsMain:
    _is_fts_backfill_paused = MainApp._is_fts_backfill_paused
    _next_fts_backfill_retry_delay_ms = MainApp._next_fts_backfill_retry_delay_ms
    _schedule_fts_backfill_retry = MainApp._schedule_fts_backfill_retry
    _request_fts_backfill_resume = MainApp._request_fts_backfill_resume
    _pause_fts_backfill = MainApp._pause_fts_backfill
    _start_fts_backfill = MainApp._start_fts_backfill
    _on_fts_backfill_error = MainApp._on_fts_backfill_error
    _on_fts_backfill_finished = MainApp._on_fts_backfill_finished
    _on_fts_backfill_cancelled = MainApp._on_fts_backfill_cancelled

    def __init__(self):
        self._shutdown_in_progress = False
        self._maintenance_mode = False
        self._refresh_in_progress = False
        self._sequential_refresh_active = False
        self._fts_backfill_worker = None
        self._fts_backfill_retry_attempt = 0
        self._fts_backfill_pause_requested = False
        self._fts_backfill_pause_delay_ms = 1000
        self._fts_backfill_retry_timer = _FakeRetryTimer()
        self.db = _FakeFtsDb()

    def _require_db(self):
        return self.db

    def is_maintenance_mode_active(self):
        return self._maintenance_mode


class TestFtsSearchAcceleration(unittest.TestCase):
    def _make_manager(self):
        td = tempfile.TemporaryDirectory()
        db_path = Path(td.name) / "news.sqlite"
        mgr = DatabaseManager(str(db_path))
        self.addCleanup(td.cleanup)
        self.addCleanup(mgr.close)
        return mgr

    def _seed_rows(self, mgr: DatabaseManager) -> str:
        query_key = build_fetch_key("AI launch", [])
        mgr.upsert_news(
            [
                {
                    "title": "AI launch roadmap",
                    "description": "platform release plan",
                    "link": "https://example.com/1",
                    "pubDate": "2026-04-09T10:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "AI launchpad beta",
                    "description": "single token substring fallback",
                    "link": "https://example.com/2",
                    "pubDate": "2026-04-09T11:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "Other update",
                    "description": "unrelated",
                    "link": "https://example.com/3",
                    "pubDate": "2026-04-09T12:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
            query_key=query_key,
        )
        return query_key

    def test_backfill_completes_and_multi_token_filter_matches_existing_semantics(self):
        mgr = self._make_manager()
        query_key = self._seed_rows(mgr)

        while True:
            result = mgr.backfill_news_fts_chunk(limit=1)
            if result["done"]:
                break

        self.assertTrue(mgr.is_news_fts_backfill_complete())
        self.assertEqual(
            mgr.count_news(keyword="AI", query_key=query_key, filter_txt="AI launch"),
            1,
        )
        rows = mgr.fetch_news(keyword="AI", query_key=query_key, filter_txt="AI launch")
        self.assertEqual([row["link"] for row in rows], ["https://example.com/1"])

    def test_single_token_filter_falls_back_to_like_semantics(self):
        mgr = self._make_manager()
        query_key = self._seed_rows(mgr)

        while True:
            result = mgr.backfill_news_fts_chunk(limit=10)
            if result["done"]:
                break

        rows = mgr.fetch_news(keyword="AI", query_key=query_key, filter_txt="launch")
        self.assertEqual(
            {row["link"] for row in rows},
            {"https://example.com/1", "https://example.com/2"},
        )

    def test_start_backfill_defers_when_paused_and_resume_nudges_retry_timer(self):
        dummy = _DummyFtsMain()
        dummy._maintenance_mode = True

        dummy._start_fts_backfill()

        self.assertIsNone(dummy._fts_backfill_worker)
        self.assertEqual(dummy._fts_backfill_retry_timer.start_calls, [1000])

        dummy._maintenance_mode = False
        dummy._request_fts_backfill_resume(delay_ms=250)
        self.assertEqual(dummy._fts_backfill_retry_timer.start_calls[-1], 250)

    def test_backfill_error_uses_capped_retry_backoff_and_finish_resets_state(self):
        dummy = _DummyFtsMain()

        dummy._on_fts_backfill_error("boom")
        self.assertEqual(dummy._fts_backfill_retry_attempt, 1)
        self.assertEqual(dummy._fts_backfill_retry_timer.start_calls[-1], 5000)

        dummy._on_fts_backfill_error("boom-again")
        self.assertEqual(dummy._fts_backfill_retry_attempt, 2)
        self.assertEqual(dummy._fts_backfill_retry_timer.start_calls[-1], 15000)

        dummy._on_fts_backfill_finished({"done": True})
        self.assertEqual(dummy._fts_backfill_retry_attempt, 0)
        self.assertFalse(dummy._fts_backfill_retry_timer.active)

    def test_pause_and_cancelled_resume_restarts_backfill_retry(self):
        dummy = _DummyFtsMain()
        worker = _FakeIterativeWorker(lambda context: None)
        worker.running = True
        dummy._fts_backfill_worker = worker

        dummy._pause_fts_backfill(retry_delay_ms=1200)

        self.assertTrue(dummy._fts_backfill_pause_requested)
        self.assertTrue(worker.interruption_requested)

        dummy._on_fts_backfill_cancelled()

        self.assertFalse(dummy._fts_backfill_pause_requested)
        self.assertEqual(dummy._fts_backfill_retry_timer.start_calls[-1], 1200)

    def test_start_backfill_creates_worker_when_not_paused(self):
        dummy = _DummyFtsMain()

        with mock.patch("ui.main_window.IterativeJobWorker", _FakeIterativeWorker):
            dummy._start_fts_backfill()

        self.assertIsNotNone(dummy._fts_backfill_worker)
        self.assertTrue(dummy._fts_backfill_worker.running)


if __name__ == "__main__":
    unittest.main()
