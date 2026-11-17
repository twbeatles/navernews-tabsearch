"""NAVER API HUB 뉴스 검색 연동 상수/헬퍼.

Developers Center(openapi.naver.com) 대신 NAVER API HUB를 사용한다.
인증 헤더·엔드포인트·오류 파싱을 한곳에 모아 ApiWorker와 설정 검증이
동일 계약을 쓰도록 한다.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Tuple

# 뉴스 검색 API (GET)
NAVER_NEWS_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# API Gateway 인증 헤더 (Client ID / Client Secret)
NAVER_API_KEY_ID_HEADER = "X-NCP-APIGW-API-KEY-ID"
NAVER_API_KEY_HEADER = "X-NCP-APIGW-API-KEY"

# 사용자 안내 (설정 UI / 첫 실행)
NAVER_API_HUB_PRODUCT_URL = (
    "https://www.ncloud.com/product/applicationService/naverApiHub"
)
NAVER_API_HUB_GUIDE_URL = "https://guide.ncloud-docs.com/docs/apihub-use"
NAVER_API_HUB_MIGRATION_URL = "https://guide.ncloud-docs.com/docs/apihub-migration"


def naver_auth_headers(client_id: str, client_secret: str) -> dict[str, str]:
    """API HUB 호출용 인증 헤더를 만든다."""
    return {
        NAVER_API_KEY_ID_HEADER: str(client_id or "").strip(),
        NAVER_API_KEY_HEADER: str(client_secret or "").strip(),
    }


def parse_naver_api_error(payload: Any) -> Tuple[str, str]:
    """Search API 평면 오류와 API Gateway 중첩 오류를 모두 파싱한다.

    Returns:
        (error_code, error_message)
    """
    if not isinstance(payload, Mapping):
        return "", "알 수 없는 오류"

    # Search API: { "errorCode": "...", "errorMessage": "..." }
    flat_code = str(payload.get("errorCode", "") or "").strip()
    flat_msg = str(payload.get("errorMessage", "") or "").strip()
    if flat_code or flat_msg:
        return flat_code, flat_msg or "알 수 없는 오류"

    # API Gateway: { "error": { "errorCode", "message", "details" } }
    nested = payload.get("error")
    if isinstance(nested, Mapping):
        nested_code = str(nested.get("errorCode", "") or "").strip()
        nested_msg = str(nested.get("message", "") or "").strip()
        details = str(nested.get("details", "") or "").strip()
        if details and nested_msg and details not in nested_msg:
            message = f"{nested_msg} ({details})"
        else:
            message = nested_msg or details or "알 수 없는 오류"
        if nested_code or message != "알 수 없는 오류":
            return nested_code, message

    # Search Trend / Shopping Insight style (not used for news, but harmless)
    err_msg = str(payload.get("errMsg", "") or "").strip()
    err_id = str(payload.get("errId", "") or "").strip()
    if err_msg or err_id:
        return err_id, err_msg or "알 수 없는 오류"

    return "", "알 수 없는 오류"


def format_naver_http_error(
    status_code: int, error_code: str, error_message: str
) -> str:
    """사용자에게 보여줄 HTTP 오류 문구를 만든다."""
    code = str(error_code or "").strip()
    msg = str(error_message or "").strip() or "알 수 없는 오류"
    status = int(status_code or 0)

    if status in (401, 403):
        base = "인증 실패 — NAVER API HUB Client ID/Secret을 확인하세요."
        if code:
            return f"API 오류 {status} ({code}): {base} {msg}"
        return f"API 오류 {status}: {base} {msg}"

    if code:
        return f"API 오류 {status} ({code}): {msg}"
    return f"API 오류 {status}: {msg}"


def apply_naver_error_fields(
    target: MutableMapping[str, Any],
    payload: Any,
) -> Tuple[str, str]:
    """파싱 결과를 target dict에 error_code/error_message로 채운다."""
    code, message = parse_naver_api_error(payload)
    target["error_code"] = code
    target["error_message"] = message
    return code, message


__all__ = [
    "NAVER_NEWS_SEARCH_URL",
    "NAVER_API_KEY_ID_HEADER",
    "NAVER_API_KEY_HEADER",
    "NAVER_API_HUB_PRODUCT_URL",
    "NAVER_API_HUB_GUIDE_URL",
    "NAVER_API_HUB_MIGRATION_URL",
    "naver_auth_headers",
    "parse_naver_api_error",
    "format_naver_http_error",
    "apply_naver_error_fields",
]
