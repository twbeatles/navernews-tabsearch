# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from core.database import DatabaseConnectionError, DatabaseManager, DatabaseWriteError
from core.workers_support.api_worker import ApiWorker, _is_db_pool_exhausted_error
from core.workers_support.db_worker import DBWorker
from core.workers_support.query_scope import DBQueryScope


class _FakeResponse:
    status_code = 200

    @staticmethod
    def json():
        return {"items": [], "total": 0}


class _FakeSession:
    def get(self, *_args, **_kwargs):
        return _FakeResponse()

    def close(self):
        return None


class _RecordingDB:
    def upsert_news_detailed(self, *_args, **_kwargs):
        raise DatabaseWriteError(
            "upsert_news",
            "Database connection pool exhausted",
            cause=DatabaseConnectionError("Database connection pool exhausted", pool_exhausted=True),
        )


class TestDbPoolExhaustionUi(unittest.TestCase):
    def test_is_db_pool_exhausted_error_detects_wrapped_write_error(self):
        error = DatabaseWriteError(
            "upsert_news",
            "Database connection pool exhausted",
            cause=DatabaseConnectionError("Database connection pool exhausted", pool_exhausted=True),
        )
        self.assertTrue(_is_db_pool_exhausted_error(error))

    def test_api_worker_emits_pool_exhausted_kind(self):
        worker = ApiWorker(
            "id",
            "secret",
            "AI",
            "AI",
            [],
            _RecordingDB(),
            query_key="ai",
            session=cast(Any, _FakeSession()),
        )
        errors: list[tuple[str, dict[str, Any]]] = []

        def capture_error(message, **_kwargs):
            errors.append((message, dict(worker.last_error_meta)))

        worker.error.connect(capture_error)
        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][1]["kind"], "db_pool_exhausted")
        self.assertIn("포화", errors[0][0])

    def test_db_worker_surfaces_pool_exhaustion_message(self):
        emitted: list[str] = []

        class _ExhaustedDB:
            def open_read_connection(self, **_kwargs):
                raise DatabaseConnectionError(
                    "Database connection pool exhausted",
                    pool_exhausted=True,
                )

            def close_read_connection(self, _conn):
                return None

            def interrupt_connection(self, _conn):
                return None

        scope = DBQueryScope(keyword="AI")
        worker = DBWorker(cast(Any, _ExhaustedDB()), scope=scope, include_total=True)
        worker.error.connect(lambda message: emitted.append(str(message)))
        worker.run()

        self.assertEqual(len(emitted), 1)
        self.assertIn("pool exhausted", emitted[0].lower())


if __name__ == "__main__":
    unittest.main()