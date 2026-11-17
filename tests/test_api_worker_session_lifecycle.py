from __future__ import annotations

from unittest.mock import MagicMock

from core.workers_support.api_worker import ApiWorker


class DummyResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {"items": [], "total": 0}

    def json(self):
        return self._payload


class ClosableMockSession:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self.payload = payload or {"items": [], "total": 0}
        self.closed = False
        self.get_calls = 0

    def get(self, *args, **kwargs):
        self.get_calls += 1
        return DummyResponse(self.status_code, self.payload)

    def close(self):
        self.closed = True


def test_api_worker_closes_owned_session_on_successful_run(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )

    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session_factory=lambda: mock_session,
    )

    worker.run()

    assert mock_session.get_calls >= 1
    assert mock_session.closed is True
    assert worker._request_session is None


def test_api_worker_closes_owned_session_on_http_error(tmp_path):
    mock_session = ClosableMockSession(
        401, {"errorCode": "024", "errorMessage": "Authentication failed"}
    )
    db_mock = MagicMock()

    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session_factory=lambda: mock_session,
    )

    worker.run()

    assert mock_session.closed is True
    assert worker._request_session is None


def test_api_worker_does_not_close_unowned_session(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )

    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session=mock_session,
    )

    worker.run()

    # Shared unowned session should remain open
    assert mock_session.closed is False
