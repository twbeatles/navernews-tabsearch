import html
import json
import logging
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, TypedDict, cast

import requests
from PyQt6.QtCore import QObject, pyqtSignal

from core.database import DatabaseConnectionError, DatabaseQueryError, DatabaseWriteError
from core.protocols import ClosableProtocol, RequestGetProtocol
from core.query_parser import build_fetch_key
from core.workers_support.http_policy import (
    MAX_FETCH_COOLDOWN_SECONDS,
    MAX_INLINE_RETRY_AFTER_SECONDS,
    RE_BOLD_TAGS,
    _is_naver_news_url,
    _normalized_http_url,
    _publisher_from_naver_news_url,
    _publisher_from_url,
    _publisher_source_url,
    _retry_after_seconds_from_response,
)
from core.workers_support.jobs import perf_timer

logger = logging.getLogger(__name__)


def _is_db_pool_exhausted_error(error: BaseException) -> bool:
    cause = getattr(error, "cause", None)
    if isinstance(cause, DatabaseConnectionError) and cause.pool_exhausted:
        return True
    message = str(error).lower()
    return "connection pool exhausted" in message or "pool exhausted" in message


def _db_pool_exhausted_message() -> str:
    return "데이터베이스 연결이 포화 상태입니다. 잠시 후 다시 시도해주세요."


class ApiErrorMeta(TypedDict):
    kind: str
    status_code: int
    cooldown_seconds: int
    retryable: bool
class ApiWorker(QObject):
    """API 호출 워커 (재시도 로직 및 백그라운드 DB 저장 포함)"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        search_query: str,
        db_keyword: str,
        exclude_words: List[str],
        db_manager,
        query_key: Optional[str] = None,
        start_idx: int = 1,
        max_retries: int = 3,
        timeout: int = 15,
        session: Optional[RequestGetProtocol] = None,
        session_factory: Optional[Callable[[], RequestGetProtocol]] = None,
        display_keyword: Optional[str] = None,
    ):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.search_query = str(search_query or "").strip()
        self.db_keyword = str(db_keyword or "").strip()
        self.display_keyword = str(display_keyword or self.search_query or self.db_keyword)
        self.exclude_words = exclude_words
        self.db = db_manager
        self.query_key = str(query_key or "").strip() or build_fetch_key(
            self.search_query,
            self.exclude_words,
        )
        self.start = start_idx
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session
        self.session_factory = session_factory
        self._is_running = True
        self._lock = threading.Lock()
        self._destroyed = False
        self._request_session: Optional[ClosableProtocol] = None
        self._owns_request_session = False
        self.last_error_meta: ApiErrorMeta = {
            "kind": "unknown",
            "status_code": 0,
            "cooldown_seconds": 0,
            "retryable": False,
        }

    @property
    def is_running(self):
        with self._lock:
            return self._is_running and not self._destroyed

    @is_running.setter
    def is_running(self, value):
        with self._lock:
            self._is_running = value

    def _safe_emit(self, signal, value):
        try:
            if not self._destroyed and self.is_running:
                signal.emit(value)
        except RuntimeError:
            logger.warning(f"시그널 발신 실패 (객체 삭제됨): {self.display_keyword}")
        except Exception as e:
            logger.error(f"시그널 발신 오류: {e}")

    def _emit_error(
        self,
        message: str,
        *,
        kind: str = "unknown",
        status_code: int = 0,
        cooldown_seconds: int = 0,
        retryable: bool = False,
    ) -> None:
        safe_cooldown_seconds = min(
            MAX_FETCH_COOLDOWN_SECONDS,
            max(0, int(cooldown_seconds or 0)),
        )
        if cooldown_seconds and int(cooldown_seconds or 0) > MAX_FETCH_COOLDOWN_SECONDS:
            logger.warning(
                "API cooldown capped: kw=%s raw=%s cap=%s",
                self.display_keyword,
                cooldown_seconds,
                MAX_FETCH_COOLDOWN_SECONDS,
            )
        self.last_error_meta = {
            "kind": str(kind or "unknown"),
            "status_code": max(0, int(status_code or 0)),
            "cooldown_seconds": safe_cooldown_seconds,
            "retryable": bool(retryable),
        }
        self._safe_emit(self.error, message)

    def _rate_limit_wait_seconds(self, response: Any, attempt: int) -> int:
        retry_after_seconds = _retry_after_seconds_from_response(response)
        if retry_after_seconds > 0:
            return retry_after_seconds
        return max(5, (int(attempt) + 1) * 5)

    def _retry_backoff_seconds(self, attempt: int) -> int:
        return min(8, max(1, 2 ** max(0, int(attempt))))

    def _sleep_with_cancel(self, seconds: int) -> bool:
        safe_seconds = max(0, int(seconds or 0))
        for _ in range(safe_seconds):
            if not self.is_running:
                return False
            time.sleep(1)
        return self.is_running

    def run(self):
        logger.info(f"ApiWorker 시작: {self.display_keyword}")

        if not self.is_running:
            return
        if not self.search_query:
            self._safe_emit(self.error, "검색어가 비어 있습니다.")
            return
        if not self.db_keyword:
            self.db_keyword = self.search_query

        headers = {
            "X-Naver-Client-Id": self.cid.strip(),
            "X-Naver-Client-Secret": self.csec.strip(),
        }
        url = "https://openapi.naver.com/v1/search/news.json"
        self.last_error_meta = {
            "kind": "unknown",
            "status_code": 0,
            "cooldown_seconds": 0,
            "retryable": False,
        }
        session: RequestGetProtocol
        if self.session is not None:
            session = self.session
        elif self.session_factory is not None:
            session = self.session_factory()
        else:
            session = requests.Session()
        owns_session = self.session is None
        self._request_session = cast(ClosableProtocol, session) if hasattr(session, "close") else None
        self._owns_request_session = owns_session

        try:
            with perf_timer("api.run", f"kw={self.display_keyword}|max_retries={self.max_retries}"):
                for attempt in range(self.max_retries):
                    if not self.is_running:
                        logger.info(f"ApiWorker 중단됨: {self.display_keyword}")
                        return

                    try:
                        self._safe_emit(
                            self.progress,
                            f"'{self.display_keyword}' 검색 중... (시도 {attempt + 1}/{self.max_retries})",
                        )

                        params = {
                            "query": self.search_query,
                            "display": 100,
                            "start": self.start,
                            "sort": "date",
                        }

                        with perf_timer("api.request", f"kw={self.display_keyword}|attempt={attempt + 1}"):
                            resp = session.get(
                                url,
                                headers=headers,
                                params=params,
                                timeout=self.timeout,
                                allow_redirects=False,
                            )
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled after response: {self.display_keyword}")
                            return

                        if 300 <= int(resp.status_code) < 400:
                            logger.warning(
                                "API redirect blocked: kw=%s status=%s",
                                self.display_keyword,
                                resp.status_code,
                            )
                            self._emit_error(
                                "API 응답이 리다이렉트를 반환해 요청을 중단했습니다.",
                                kind="redirect_error",
                                status_code=int(resp.status_code),
                                retryable=False,
                            )
                            return

                        if resp.status_code == 429:
                            cooldown_seconds = self._rate_limit_wait_seconds(resp, attempt)
                            if cooldown_seconds > MAX_INLINE_RETRY_AFTER_SECONDS:
                                self._emit_error(
                                    "API 요청 제한 초과. 잠시 후 다시 시도해주세요.",
                                    kind="rate_limit",
                                    status_code=429,
                                    cooldown_seconds=cooldown_seconds,
                                    retryable=True,
                                )
                                return
                            if attempt < self.max_retries - 1:
                                self._safe_emit(self.progress, f"요청 제한 초과. {cooldown_seconds}초 후 재시도...")
                                for _ in range(cooldown_seconds):
                                    if not self.is_running:
                                        return
                                    time.sleep(1)
                                continue
                            self._emit_error(
                                "API 요청 제한 초과. 잠시 후 다시 시도해주세요.",
                                kind="rate_limit",
                                status_code=429,
                                cooldown_seconds=cooldown_seconds,
                                retryable=True,
                            )
                            return

                        if resp.status_code != 200:
                            try:
                                error_data = resp.json()
                                error_msg = error_data.get("errorMessage", "알 수 없는 오류")
                                error_code = error_data.get("errorCode", "")
                            except (json.JSONDecodeError, KeyError, ValueError):
                                error_msg = f"HTTP {resp.status_code}"
                                error_code = ""
                            if 500 <= int(resp.status_code) < 600 and attempt < self.max_retries - 1:
                                backoff_seconds = self._retry_backoff_seconds(attempt)
                                self._safe_emit(self.progress, f"서버 오류. {backoff_seconds}초 후 재시도...")
                                if not self._sleep_with_cancel(backoff_seconds):
                                    return
                                continue
                            self._emit_error(
                                f"API 오류 {resp.status_code} ({error_code}): {error_msg}",
                                kind="http_error",
                                status_code=resp.status_code,
                                retryable=500 <= int(resp.status_code) < 600,
                            )
                            return

                        with perf_timer("api.parse", f"kw={self.display_keyword}"):
                            data = resp.json()
                            raw_items = data.get("items", [])
                            items: List[Dict[str, Any]] = []
                            new_items: List[Dict[str, Any]] = []
                            filtered_count = 0
                            exclude_words_lc = [ex.lower() for ex in self.exclude_words if ex]

                            for item in raw_items:
                                if not self.is_running:
                                    break

                                title = html.unescape(RE_BOLD_TAGS.sub("", item.get("title", "")))
                                desc = html.unescape(RE_BOLD_TAGS.sub("", item.get("description", "")))

                                if exclude_words_lc:
                                    should_exclude = False
                                    title_lc = title.lower()
                                    desc_lc = desc.lower()
                                    for ex in exclude_words_lc:
                                        if ex in title_lc or ex in desc_lc:
                                            should_exclude = True
                                            filtered_count += 1
                                            break
                                    if should_exclude:
                                        continue

                                naver_link = _normalized_http_url(item.get("link", ""))
                                org_link = _normalized_http_url(item.get("originallink", ""))
                                if _is_naver_news_url(naver_link):
                                    final_link = naver_link
                                elif _is_naver_news_url(org_link):
                                    final_link = org_link
                                else:
                                    final_link = naver_link or org_link
                                if not final_link:
                                    filtered_count += 1
                                    continue

                                publisher_source = _publisher_source_url(org_link, final_link)
                                publisher = _publisher_from_url(publisher_source)
                                if not publisher_source and _is_naver_news_url(final_link):
                                    publisher = _publisher_from_naver_news_url(final_link) or publisher
                                    if publisher == _publisher_from_url(""):
                                        logger.info(
                                            "Naver publisher oid fallback unavailable: %s",
                                            final_link,
                                        )

                                items.append(
                                    {
                                        "title": title,
                                        "description": desc,
                                        "link": final_link,
                                        "pubDate": item.get("pubDate", ""),
                                        "publisher": publisher,
                                    }
                                )

                        self._safe_emit(self.progress, f"'{self.display_keyword}' 저장 중...")
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled before upsert: {self.display_keyword}")
                            return

                        try:
                            upsert_detailed = getattr(self.db, "upsert_news_detailed", None)
                            if callable(upsert_detailed):
                                with perf_timer(
                                    "api.upsert",
                                    f"kw={self.db_keyword}|query_key={self.query_key}|items={len(items)}|mode=detailed",
                                ):
                                    upsert_result = upsert_detailed(
                                        items,
                                        self.db_keyword,
                                        query_key=self.query_key,
                                    )
                                added_count = int(getattr(upsert_result, "added_count", 0) or 0)
                                dup_count = int(getattr(upsert_result, "duplicate_count", 0) or 0)
                                new_link_order = [
                                    str(link).strip()
                                    for link in (getattr(upsert_result, "new_links", ()) or ())
                                    if str(link or "").strip()
                                ]
                                new_link_set = set(new_link_order)
                                seen_new_links = set()
                                for item in items:
                                    link = str(item.get("link", "") or "").strip()
                                    if not link or link not in new_link_set or link in seen_new_links:
                                        continue
                                    seen_new_links.add(link)
                                    new_items.append(item)
                            else:
                                existing_links = self.db.get_existing_links_for_query(
                                    [str(item.get("link", "") or "") for item in items],
                                    keyword=self.db_keyword,
                                    query_key=self.query_key,
                                )
                                seen_new_links = set()
                                for item in items:
                                    link = str(item.get("link", "") or "").strip()
                                    if not link or link in existing_links or link in seen_new_links:
                                        continue
                                    seen_new_links.add(link)
                                    new_items.append(item)

                                with perf_timer(
                                    "api.upsert",
                                    f"kw={self.db_keyword}|query_key={self.query_key}|items={len(items)}|mode=legacy",
                                ):
                                    added_count, dup_count = self.db.upsert_news(
                                        items,
                                        self.db_keyword,
                                        query_key=self.query_key,
                                    )
                        except DatabaseQueryError as e:
                            logger.error("ApiWorker DB read failed: %s - %s", self.display_keyword, e)
                            if not self.is_running:
                                logger.info(f"ApiWorker cancelled on DB read error: {self.display_keyword}")
                                return
                            error_kind = (
                                "db_pool_exhausted"
                                if _is_db_pool_exhausted_error(e)
                                else "db_query_error"
                            )
                            self._emit_error(
                                _db_pool_exhausted_message()
                                if error_kind == "db_pool_exhausted"
                                else f"데이터베이스 조회 실패: {e}",
                                kind=error_kind,
                            )
                            return
                        except DatabaseWriteError as e:
                            logger.error("ApiWorker DB write failed: %s - %s", self.display_keyword, e)
                            if not self.is_running:
                                logger.info(f"ApiWorker cancelled on DB write error: {self.display_keyword}")
                                return
                            error_kind = (
                                "db_pool_exhausted"
                                if _is_db_pool_exhausted_error(e)
                                else "db_write_error"
                            )
                            self._emit_error(
                                _db_pool_exhausted_message()
                                if error_kind == "db_pool_exhausted"
                                else f"데이터베이스 저장 실패: {e}",
                                kind=error_kind,
                            )
                            return
                        except DatabaseConnectionError as e:
                            logger.error("ApiWorker DB connection failed: %s - %s", self.display_keyword, e)
                            if not self.is_running:
                                logger.info(f"ApiWorker cancelled on DB connection error: {self.display_keyword}")
                                return
                            error_kind = "db_pool_exhausted" if e.pool_exhausted else "db_query_error"
                            self._emit_error(
                                _db_pool_exhausted_message()
                                if error_kind == "db_pool_exhausted"
                                else f"데이터베이스 연결 실패: {e}",
                                kind=error_kind,
                            )
                            return

                        new_count = len(new_items)
                        result = {
                            "items": items,
                            "new_items": new_items,
                            "new_count": new_count,
                            "total": data.get("total", 0),
                            "filtered": filtered_count,
                            "added_count": added_count,
                            "dup_count": dup_count,
                        }

                        logger.info(
                            f"ApiWorker 완료: {self.display_keyword} ({len(items)}개, 새 링크 {new_count}, 추가 {added_count}, 중복 {dup_count})"
                        )
                        self._safe_emit(self.progress, f"'{self.display_keyword}' 완료 (새 링크: {new_count}개)")
                        self._safe_emit(self.finished, result)
                        return

                    except requests.Timeout:
                        logger.warning(f"API 타임아웃: {self.display_keyword} (시도 {attempt + 1})")
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on timeout: {self.display_keyword}")
                            return
                        if attempt < self.max_retries - 1:
                            backoff_seconds = self._retry_backoff_seconds(attempt)
                            self._safe_emit(self.progress, f"요청 시간 초과. {backoff_seconds}초 후 재시도...")
                            if not self._sleep_with_cancel(backoff_seconds):
                                return
                            continue
                        self._emit_error(
                            "요청 시간이 초과되었습니다. 네트워크 연결을 확인해주세요.",
                            kind="timeout",
                            retryable=True,
                        )
                        return

                    except requests.RequestException as e:
                        logger.warning(f"네트워크 오류: {self.display_keyword} - {e}")
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on request error: {self.display_keyword}")
                            return
                        if attempt < self.max_retries - 1:
                            backoff_seconds = self._retry_backoff_seconds(attempt)
                            self._safe_emit(self.progress, f"네트워크 오류. {backoff_seconds}초 후 재시도...")
                            if not self._sleep_with_cancel(backoff_seconds):
                                return
                            continue
                        self._emit_error(
                            f"네트워크 오류: {str(e)}",
                            kind="network_error",
                            retryable=True,
                        )
                        return

                    except Exception as e:
                        logger.error(f"ApiWorker 예외: {self.display_keyword} - {e}")
                        traceback.print_exc()
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on exception: {self.display_keyword}")
                            return
                        self._emit_error(f"오류 발생: {str(e)}", kind="internal_error")
                        return
        finally:
            if owns_session and self._request_session is not None:
                try:
                    self._request_session.close()
                except Exception:
                    pass
            self._request_session = None
            self._owns_request_session = False

    def stop(self):
        logger.info(f"ApiWorker 중지 요청: {self.display_keyword}")
        self._destroyed = True
        self.is_running = False
