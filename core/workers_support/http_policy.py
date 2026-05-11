import ipaddress
import re
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

RE_BOLD_TAGS = re.compile(r"</?b>")
MAX_INLINE_RETRY_AFTER_SECONDS = 30
MAX_FETCH_COOLDOWN_SECONDS = 6 * 60 * 60

def _parse_retry_after_seconds(
    header_value: Any,
    *,
    now: Optional[datetime] = None,
) -> int:
    raw_value = str(header_value or "").strip()
    if not raw_value:
        return 0
    if raw_value.isdigit():
        return min(MAX_FETCH_COOLDOWN_SECONDS, max(0, int(raw_value)))

    try:
        retry_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        return 0

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    reference_time = now or datetime.now(timezone.utc)
    return min(MAX_FETCH_COOLDOWN_SECONDS, max(0, int((retry_at - reference_time).total_seconds())))
def _retry_after_seconds_from_response(response: Any) -> int:
    headers = getattr(response, "headers", None)
    if headers is None:
        return 0

    header_value = None
    try:
        header_value = headers.get("Retry-After")
    except Exception:
        header_value = None
    if header_value is None:
        try:
            header_value = headers.get("retry-after")
        except Exception:
            header_value = None
    return _parse_retry_after_seconds(header_value)
def _normalized_http_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    if _is_disallowed_http_host(parsed.hostname or ""):
        return ""
    return urllib.parse.urlunparse(parsed)
def _is_disallowed_http_host(host: str) -> bool:
    normalized = str(host or "").strip().strip("[]").lower().rstrip(".")
    if not normalized:
        return True
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    if normalized.endswith(".local") or normalized.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_reserved,
            ip.is_multicast,
            ip.is_unspecified,
        )
    )
def _host_from_url(value: str) -> str:
    try:
        return str(urllib.parse.urlparse(str(value or "")).hostname or "").strip().lower()
    except Exception:
        return ""
def _is_naver_news_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    return normalized == "news.naver.com" or normalized.endswith(".news.naver.com")
def _is_naver_news_url(value: str) -> bool:
    return _is_naver_news_host(_host_from_url(value))
def _publisher_source_url(original_link: str, final_link: str) -> str:
    for candidate in (original_link, final_link):
        host = _host_from_url(candidate)
        if host and not _is_naver_news_host(host):
            return candidate
    return ""
def _publisher_from_naver_news_url(value: str) -> str:
    if not _is_naver_news_url(value):
        return ""
    try:
        parsed = urllib.parse.urlparse(str(value or ""))
    except Exception:
        return ""

    oid = ""
    query_values = urllib.parse.parse_qs(parsed.query).get("oid", [])
    if query_values:
        oid = str(query_values[0] or "").strip()

    if not oid:
        path_parts = [part for part in parsed.path.split("/") if part]
        for idx, part in enumerate(path_parts):
            if part == "article" and idx + 1 < len(path_parts):
                oid = str(path_parts[idx + 1] or "").strip()
                break

    if not oid or not re.fullmatch(r"[0-9A-Za-z_-]{1,20}", oid):
        return ""
    return f"naver:oid:{oid}"
def _publisher_from_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    host = parsed.netloc.strip().lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host and not host.startswith("["):
        host = host.split(":", 1)[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.startswith("www."):
        host = host[4:]
    return host or "정보 없음"
