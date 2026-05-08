import csv
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional, cast
from unittest import mock

from core.backup import AutoBackup, cleanup_applied_pending_restore_files
from core.database import DatabaseManager
from core.workers import (
    ApiWorker,
    MAX_FETCH_COOLDOWN_SECONDS,
    _normalized_http_url,
    _publisher_from_url,
    _publisher_source_url,
)
from ui._main_window_settings_io import import_bookmarks_notes_from_csv
from ui.main_window_support.ui_shell import _MainWindowUIShellMixin


class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict[str, Any]] = None, headers: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return dict(self._payload)


class _SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, *_args, **kwargs):
        self.calls.append(dict(kwargs))
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


class _FakeDB:
    def __init__(self):
        self.upsert_calls = 0

    def get_existing_links_for_query(self, links, keyword="", query_key=None):
        return set()

    def upsert_news(self, items, keyword, query_key=None):
        self.upsert_calls += 1
        return len(items), 0


class _Context:
    def __init__(self):
        self.reports = []

    def check_cancelled(self):
        return None

    def report(self, **payload):
        self.reports.append(payload)


class _AlertDummy:
    def __init__(self, keywords):
        self.alert_keywords = keywords

    def check_alert_keywords(self, items):
        return cast(Any, _MainWindowUIShellMixin).check_alert_keywords(cast(Any, self), items)


class TestFollowup20260508(unittest.TestCase):
    def _make_api_worker(self, session, max_retries: int = 1):
        db = _FakeDB()
        worker = ApiWorker(
            client_id="id",
            client_secret="secret",
            search_query="AI",
            db_keyword="AI",
            exclude_words=[],
            db_manager=db,
            start_idx=1,
            max_retries=max_retries,
            timeout=1,
            session=session,
        )
        return worker, db

    def test_api_requests_block_redirects_and_surface_3xx_as_error(self):
        session = _SequenceSession([_FakeResponse(302)])
        worker, db = self._make_api_worker(session)
        errors = []
        worker.error.connect(lambda msg: errors.append(msg))

        worker.run()

        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0]["allow_redirects"])
        self.assertEqual(worker.last_error_meta["kind"], "redirect_error")
        self.assertEqual(worker.last_error_meta["status_code"], 302)
        self.assertEqual(len(errors), 1)

    def test_private_and_local_api_item_urls_are_rejected_before_save(self):
        self.assertFalse(_normalized_http_url("http://127.0.0.1/news"))
        self.assertFalse(_normalized_http_url("http://localhost/news"))
        self.assertFalse(_normalized_http_url("http://192.168.1.10/news"))
        self.assertFalse(_normalized_http_url("http://printer.local/news"))
        self.assertEqual(_normalized_http_url("https://example.com/news"), "https://example.com/news")

    def test_naver_only_links_do_not_become_publisher_fallback(self):
        source = _publisher_source_url("", "https://news.naver.com/main/read.naver?oid=001")
        self.assertEqual(source, "")
        self.assertEqual(_publisher_from_url(source), "정보 없음")

    def test_fetch_cooldown_is_clamped_to_six_hours(self):
        session = _SequenceSession([])
        worker, _db = self._make_api_worker(session)

        worker._emit_error("limited", kind="rate_limit", cooldown_seconds=MAX_FETCH_COOLDOWN_SECONDS * 2)

        self.assertEqual(worker.last_error_meta["cooldown_seconds"], MAX_FETCH_COOLDOWN_SECONDS)

    def test_5xx_retry_uses_cancellable_exponential_backoff(self):
        payload = {
            "total": 1,
            "items": [
                {
                    "title": "AI",
                    "description": "desc",
                    "link": "https://news.naver.com/main/read.naver?oid=001&aid=1",
                    "originallink": "https://example.com/article",
                    "pubDate": "2026-05-08T10:00:00",
                }
            ],
        }
        session = _SequenceSession([_FakeResponse(503, {"errorMessage": "down"}), _FakeResponse(200, payload)])
        worker, db = self._make_api_worker(session, max_retries=2)

        with mock.patch("core.workers.time.sleep") as sleep_mock:
            worker.run()

        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleep_mock.call_count, 1)
        self.assertEqual(db.upsert_calls, 1)

    def test_mark_query_as_read_chunked_makes_progress_with_chunk_size_one(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.db"))
            try:
                db.upsert_news(
                    [
                        {"title": f"title {idx}", "link": f"https://example.com/{idx}", "pubDate": "", "description": ""}
                        for idx in range(3)
                    ],
                    "AI",
                    query_key="ai|",
                )
                progress = []
                updated = db.mark_query_as_read_chunked(
                    "AI",
                    query_key="ai|",
                    chunk_size=1,
                    progress_callback=lambda current, total: progress.append((current, total)),
                )

                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(updated, 3)
                self.assertEqual(progress[-1], (3, 3))
                self.assertTrue(all(int(row["is_read"]) == 1 for row in rows))
            finally:
                db.close()

    def test_csv_import_updates_existing_bookmark_and_note_without_creating_articles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = DatabaseManager(str(root / "news.db"))
            try:
                db.upsert_news(
                    [
                        {
                            "title": "existing",
                            "link": "https://example.com/existing",
                            "pubDate": "",
                            "description": "",
                        }
                    ],
                    "AI",
                    query_key="ai|",
                )
                csv_path = root / "state.csv"
                with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["링크", "북마크", "메모"])
                    writer.writerow(["https://example.com/existing", "북마크", "note"])
                    writer.writerow(["https://example.com/new", "북마크", "new note"])

                result = import_bookmarks_notes_from_csv(_Context(), db, str(csv_path), chunk_size=1)

                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(result["processed"], 2)
                self.assertEqual(result["updated"], 1)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["is_bookmarked"], 1)
                self.assertEqual(rows[0]["notes"], "note")
            finally:
                db.close()

    def test_optimize_database_runs_without_changing_public_facade(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.db"))
            try:
                self.assertTrue(db.optimize_database(vacuum=False))
            finally:
                db.close()

    def test_pending_applied_restore_cleanup_removes_stale_marker(self):
        with tempfile.TemporaryDirectory() as td:
            pending = Path(td) / "pending_restore.json"
            applied = Path(str(pending) + ".applied")
            applied.write_text("{}", encoding="utf-8")

            self.assertEqual(cleanup_applied_pending_restore_files(str(pending)), 1)
            self.assertFalse(applied.exists())

    def test_create_backup_writes_backup_info_through_atomic_helper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / "config.json"
            db_file = root / "news.db"
            config.write_text('{"app_settings": {}}', encoding="utf-8")
            DatabaseManager(str(db_file)).close()
            backup = AutoBackup(str(config), str(db_file), app_version="test")

            with mock.patch.object(backup, "_write_backup_info", wraps=backup._write_backup_info) as write_mock:
                result = backup.create_backup(include_db=False)

            self.assertIsNotNone(result)
            self.assertGreaterEqual(write_mock.call_count, 1)

    def test_regex_alert_keywords_match_and_invalid_regex_is_ignored(self):
        dummy = _AlertDummy(["regex:AI\\s+반도체", "regex:["])
        matches = dummy.check_alert_keywords(
            [{"title": "AI 반도체 투자", "description": ""}, {"title": "경제", "description": "일반"}]
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][1], "regex:AI\\s+반도체")


if __name__ == "__main__":
    unittest.main()
