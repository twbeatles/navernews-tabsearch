import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Optional
from unittest import mock

import requests

from core.database import DatabaseWriteError
from core.workers import ApiWorker, _parse_retry_after_seconds


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeDB:
    def __init__(self):
        self.upsert_calls = 0

    def get_existing_links_for_query(self, links, keyword="", query_key=None):
        return set()

    def upsert_news(self, items, keyword, query_key=None):
        self.upsert_calls += 1
        return len(items), 0


class _CancelAfterGetSession:
    def __init__(self):
        self.worker: Optional[ApiWorker] = None

    def get(self, *_args, **_kwargs):
        assert self.worker is not None
        self.worker.stop()
        return _FakeResponse(
            200,
            {
                "total": 1,
                "items": [
                    {
                        "title": "AI update",
                        "description": "desc",
                        "link": "https://news.naver.com/test-1",
                        "originallink": "https://example.com/test-1",
                        "pubDate": "2026-02-27T10:00:00",
                    }
                ],
            },
        )


class _CancelThenErrorSession:
    def __init__(self):
        self.worker: Optional[ApiWorker] = None

    def get(self, *_args, **_kwargs):
        assert self.worker is not None
        self.worker.stop()
        raise requests.ConnectionError("cancelled")


class _ClosableSession:
    def __init__(self):
        self.close_called = False

    def close(self):
        self.close_called = True


class _ExistingLinkDB(_FakeDB):
    def __init__(self, existing_links):
        super().__init__()
        self.existing_links = set(existing_links)

    def get_existing_links_for_query(self, links, keyword="", query_key=None):
        return self.existing_links.intersection(set(links))


class _FailingWriteDB(_FakeDB):
    def upsert_news(self, items, keyword, query_key=None):
        raise DatabaseWriteError("upsert_news", "disk full")


class _StaticSession:
    def __init__(self, response):
        self.response = response

    def get(self, *_args, **_kwargs):
        return self.response


class _SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


class TestWorkerCancellation(unittest.TestCase):
    def _make_worker(self, session):
        db = _FakeDB()
        worker = ApiWorker(
            client_id="id",
            client_secret="secret",
            search_query="AI",
            db_keyword="AI",
            exclude_words=[],
            db_manager=db,
            start_idx=1,
            max_retries=1,
            timeout=1,
            session=session,
        )
        return worker, db

    def test_cancelled_worker_does_not_upsert_or_emit_error(self):
        session = _CancelAfterGetSession()
        worker, db = self._make_worker(session)
        session.worker = worker

        errors = []
        finished = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.finished.connect(lambda result: finished.append(result))

        worker.run()

        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(errors, [])
        self.assertEqual(finished, [])

    def test_cancelled_request_exception_does_not_emit_error(self):
        session = _CancelThenErrorSession()
        worker, db = self._make_worker(session)
        session.worker = worker

        errors = []
        worker.error.connect(lambda msg: errors.append(msg))

        worker.run()

        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(errors, [])

    def test_stop_closes_worker_owned_session(self):
        worker, _db = self._make_worker(session=None)
        closable = _ClosableSession()
        worker._request_session = closable
        worker._owns_request_session = True

        worker.stop()

        self.assertTrue(closable.close_called)

    def test_finished_result_only_exposes_new_items_for_alerts(self):
        payload = {
            "total": 2,
            "items": [
                {
                    "title": "Existing AI update",
                    "description": "desc",
                    "link": "https://news.naver.com/existing",
                    "originallink": "https://example.com/existing",
                    "pubDate": "2026-02-27T10:00:00",
                },
                {
                    "title": "Fresh AI update",
                    "description": "desc",
                    "link": "https://news.naver.com/new",
                    "originallink": "https://example.com/new",
                    "pubDate": "2026-02-27T11:00:00",
                },
            ],
        }
        session = _FakeResponse(200, payload)
        db = _ExistingLinkDB({"https://news.naver.com/existing"})
        worker = ApiWorker(
            client_id="id",
            client_secret="secret",
            search_query="AI",
            db_keyword="AI",
            exclude_words=[],
            db_manager=db,
            start_idx=1,
            max_retries=1,
            timeout=1,
            session=_StaticSession(session),
        )

        finished = []
        worker.finished.connect(lambda result: finished.append(result))

        worker.run()

        self.assertEqual(len(finished), 1)
        self.assertEqual(
            [item["link"] for item in finished[0]["new_items"]],
            ["https://news.naver.com/new"],
        )
        self.assertEqual(finished[0]["new_count"], 1)

    def test_db_write_failure_emits_error_instead_of_finished(self):
        payload = {
            "total": 1,
            "items": [
                {
                    "title": "AI update",
                    "description": "desc",
                    "link": "https://news.naver.com/test-1",
                    "originallink": "https://example.com/test-1",
                    "pubDate": "2026-02-27T10:00:00",
                }
            ],
        }
        worker = ApiWorker(
            client_id="id",
            client_secret="secret",
            search_query="AI",
            db_keyword="AI",
            exclude_words=[],
            db_manager=_FailingWriteDB(),
            start_idx=1,
            max_retries=1,
            timeout=1,
            session=_StaticSession(_FakeResponse(200, payload)),
        )

        errors = []
        finished = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.finished.connect(lambda result: finished.append(result))

        worker.run()

        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("데이터베이스 저장 실패", errors[0])
        self.assertEqual(worker.last_error_meta["kind"], "db_write_error")

    def test_http_500_retries_then_succeeds(self):
        payload = {
            "total": 1,
            "items": [
                {
                    "title": "AI retry success",
                    "description": "desc",
                    "link": "https://news.naver.com/retry-success",
                    "originallink": "https://example.com/retry-success",
                    "pubDate": "2026-02-27T10:00:00",
                }
            ],
        }
        session = _SequenceSession(
            [
                _FakeResponse(500, {"errorMessage": "temporary", "errorCode": "E500"}),
                _FakeResponse(200, payload),
            ]
        )
        worker, db = self._make_worker(session)
        worker.max_retries = 2

        errors = []
        finished = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.finished.connect(lambda result: finished.append(result))

        worker.run()

        self.assertEqual(session.calls, 2)
        self.assertEqual(db.upsert_calls, 1)
        self.assertEqual(errors, [])
        self.assertEqual(len(finished), 1)

    def test_http_503_final_failure_is_retryable_http_error(self):
        session = _SequenceSession(
            [
                _FakeResponse(503, {"errorMessage": "down", "errorCode": "E503"}),
                _FakeResponse(503, {"errorMessage": "down", "errorCode": "E503"}),
            ]
        )
        worker, db = self._make_worker(session)
        worker.max_retries = 2

        errors = []
        finished = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.finished.connect(lambda result: finished.append(result))

        worker.run()

        self.assertEqual(session.calls, 2)
        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(finished, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.last_error_meta["kind"], "http_error")
        self.assertEqual(worker.last_error_meta["status_code"], 503)
        self.assertTrue(worker.last_error_meta["retryable"])

    def test_parse_retry_after_supports_seconds_and_http_date(self):
        fixed_now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
        retry_at = format_datetime(fixed_now + timedelta(seconds=9), usegmt=True)

        self.assertEqual(_parse_retry_after_seconds("7", now=fixed_now), 7)
        self.assertEqual(_parse_retry_after_seconds(retry_at, now=fixed_now), 9)

    def test_http_429_retry_after_seconds_header_controls_retry_delay(self):
        payload = {
            "total": 1,
            "items": [
                {
                    "title": "AI retry success",
                    "description": "desc",
                    "link": "https://news.naver.com/retry-after-success",
                    "originallink": "https://example.com/retry-after-success",
                    "pubDate": "2026-02-27T10:00:00",
                }
            ],
        }
        session = _SequenceSession(
            [
                _FakeResponse(429, {"errorMessage": "limited", "errorCode": "E429"}, headers={"Retry-After": "7"}),
                _FakeResponse(200, payload),
            ]
        )
        worker, db = self._make_worker(session)
        worker.max_retries = 2

        with mock.patch("core.workers.time.sleep") as sleep_mock:
            worker.run()

        self.assertEqual(session.calls, 2)
        self.assertEqual(db.upsert_calls, 1)
        self.assertEqual(sleep_mock.call_count, 7)

    def test_http_429_final_failure_uses_retry_after_http_date_for_cooldown(self):
        retry_at = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=6), usegmt=True)
        session = _SequenceSession(
            [
                _FakeResponse(
                    429,
                    {"errorMessage": "limited", "errorCode": "E429"},
                    headers={"Retry-After": retry_at},
                )
            ]
        )
        worker, db = self._make_worker(session)
        worker.max_retries = 1

        errors = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.run()

        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.last_error_meta["kind"], "rate_limit")
        self.assertGreaterEqual(worker.last_error_meta["cooldown_seconds"], 1)
        self.assertLessEqual(worker.last_error_meta["cooldown_seconds"], 6)

    def test_http_429_invalid_retry_after_falls_back_to_default_cooldown(self):
        session = _SequenceSession(
            [
                _FakeResponse(
                    429,
                    {"errorMessage": "limited", "errorCode": "E429"},
                    headers={"Retry-After": "not-a-date"},
                )
            ]
        )
        worker, db = self._make_worker(session)
        worker.max_retries = 1

        errors = []
        worker.error.connect(lambda msg: errors.append(msg))
        worker.run()

        self.assertEqual(db.upsert_calls, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.last_error_meta["cooldown_seconds"], 5)
