import unittest

import requests

from core.workers import ApiWorker


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeDB:
    def __init__(self):
        self.upsert_calls = 0

    def upsert_news(self, items, keyword):
        self.upsert_calls += 1
        return len(items), 0


class _CancelAfterGetSession:
    def __init__(self):
        self.worker = None

    def get(self, *_args, **_kwargs):
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
        self.worker = None

    def get(self, *_args, **_kwargs):
        self.worker.stop()
        raise requests.ConnectionError("cancelled")


class _ClosableSession:
    def __init__(self):
        self.close_called = False

    def close(self):
        self.close_called = True


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
