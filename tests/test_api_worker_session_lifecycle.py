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
        self.last_kwargs: dict | None = None

    def get(self, *args, **kwargs):
        self.get_calls += 1
        self.last_kwargs = dict(kwargs)
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


class _QuotaDouble:
    def __init__(self):
        self.calls = 0

    def record_call(self, count: int = 1):
        self.calls += count
        return self.calls, 0


def _run_worker(session, db_mock, **kwargs):
    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session_factory=lambda: session,
        **kwargs,
    )
    worker.run()
    return worker


def test_api_worker_sends_default_sort_date(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )

    _run_worker(mock_session, db_mock)

    assert mock_session.last_kwargs is not None
    assert mock_session.last_kwargs.get("params", {}).get("sort") == "date"


def test_api_worker_sends_configured_sort(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )

    _run_worker(mock_session, db_mock, sort="sim")

    assert mock_session.last_kwargs is not None
    assert mock_session.last_kwargs.get("params", {}).get("sort") == "sim"


def test_api_worker_normalizes_invalid_sort(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )

    worker = _run_worker(mock_session, db_mock, sort="bogus")

    assert worker.sort == "date"
    assert mock_session.last_kwargs is not None
    assert mock_session.last_kwargs.get("params", {}).get("sort") == "date"


def test_api_worker_records_quota_per_request(tmp_path):
    mock_session = ClosableMockSession(200, {"items": [], "total": 0})
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )
    quota = _QuotaDouble()

    _run_worker(mock_session, db_mock, quota_tracker=quota)

    assert quota.calls == 1


def test_api_worker_result_carries_last_build_date(tmp_path):
    payload = {
        "items": [],
        "total": 0,
        "lastBuildDate": "Mon, 24 Nov 2026 09:00:00 +0900",
    }
    mock_session = ClosableMockSession(200, payload)
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )
    seen = {}

    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session_factory=lambda: mock_session,
    )
    worker.finished.connect(lambda result: seen.update(result))
    worker.run()

    assert seen.get("lastBuildDate") == "Mon, 24 Nov 2026 09:00:00 +0900"


def test_api_worker_items_carry_originallink(tmp_path):
    payload = {
        "items": [
            {
                "title": "t",
                "originallink": "https://example.com/original/1",
                "link": "https://n.news.naver.com/article/1",
                "description": "d",
                "pubDate": "Mon, 24 Nov 2026 09:00:00 +0900",
            }
        ],
        "total": 1,
    }
    mock_session = ClosableMockSession(200, payload)
    db_mock = MagicMock()
    db_mock.upsert_news_detailed.return_value = MagicMock(
        added_count=0, duplicate_count=0, new_links=()
    )
    seen = {}

    worker = ApiWorker(
        client_id="test_client_id_12345",
        client_secret="test_client_secret_12345",
        search_query="python",
        db_keyword="python",
        exclude_words=[],
        db_manager=db_mock,
        session_factory=lambda: mock_session,
    )
    worker.finished.connect(lambda result: seen.update(result))
    worker.run()

    assert seen["items"][0]["originallink"] == "https://example.com/original/1"


def test_api_worker_requests_json_format(tmp_path):
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

    assert mock_session.last_kwargs is not None
    assert mock_session.last_kwargs.get("params", {}).get("format") == "json"
