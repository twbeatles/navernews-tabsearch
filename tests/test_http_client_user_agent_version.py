"""HttpClientConfig.user_agent 가 core.constants.VERSION 과 일치하는지 검증.

PROJECT_AUDIT.md 3.1: user_agent 기본값이 구버전으로 하드코딩되어
VERSION 과 어긋나던 문제를 방지하는 회귀 테스트.
"""

from __future__ import annotations

from core.constants import VERSION
from core.http_client import HttpClientConfig


def test_user_agent_reflects_current_version():
    expected = f"NewsScraperPro/{VERSION}"
    assert HttpClientConfig().user_agent == expected


def test_user_agent_version_segment_matches_constant():
    version_segment = HttpClientConfig().user_agent.rsplit("/", 1)[-1]
    assert version_segment == VERSION


def test_create_session_propagates_user_agent():
    config = HttpClientConfig()
    session = config.create_session()
    try:
        assert session.headers.get("User-Agent") == config.user_agent
    finally:
        session.close()
