import os

import pytest
import requests

from core.naver_api import NAVER_NEWS_SEARCH_URL, naver_auth_headers


def test_live_naver_api_hub_search_contract():
    """Opt-in credentialed smoke; never uses the application DB or config."""
    if os.environ.get("NAVER_API_LIVE_TEST") != "1":
        pytest.skip("set NAVER_API_LIVE_TEST=1 to run the credentialed API HUB smoke")
    client_id = os.environ.get("NAVER_API_HUB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_API_HUB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        pytest.fail(
            "NAVER_API_HUB_CLIENT_ID and NAVER_API_HUB_CLIENT_SECRET are required"
        )
    response = requests.get(
        NAVER_NEWS_SEARCH_URL,
        headers=naver_auth_headers(client_id, client_secret),
        params={"query": "OpenAI", "display": 1, "start": 1, "sort": "date"},
        timeout=(5, 15),
        allow_redirects=False,
    )
    assert response.status_code == 200, response.text[:500]
    payload = response.json()
    assert isinstance(payload.get("items"), list)
    for item in payload["items"]:
        assert {"title", "link", "description", "pubDate"}.issubset(item)
