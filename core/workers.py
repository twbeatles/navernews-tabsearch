import html
import ipaddress
import json
import logging
import re
import sqlite3
import threading
import time
import traceback
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, TypedDict, cast

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.database import DatabaseQueryError, DatabaseWriteError
from core.protocols import ClosableProtocol, RequestGetProtocol
from core.query_parser import build_fetch_key


logger = logging.getLogger(__name__)

RE_BOLD_TAGS = re.compile(r"</?b>")
MAX_INLINE_RETRY_AFTER_SECONDS = 30
MAX_FETCH_COOLDOWN_SECONDS = 6 * 60 * 60
_DETACHED_WORKERS: Dict[int, Any] = {}


def _safe_delete_later(obj: Any) -> None:
    try:
        obj.deleteLater()
    except Exception:
        pass


def connect_qthread_finished(worker: Any, slot: Callable[..., Any]) -> bool:
    """Connect to QThread.finished even when subclasses define result signals named finished."""
    if not isinstance(worker, QThread):
        return False
    try:
        finished_signal = QThread.finished.__get__(worker, type(worker))
        finished_signal.connect(slot)
        return True
    except Exception:
        return False


def delete_qthread_when_finished(worker: Any) -> bool:
    """Delete a QThread subclass only after Qt reports the native thread has finished."""
    return connect_qthread_finished(worker, lambda *_args: _safe_delete_later(worker))


def retain_worker_until_finished(worker: Any) -> None:
    """Keep a detached QThread subclass alive until its run method settles."""
    if worker is None:
        return
    key = id(worker)
    _DETACHED_WORKERS[key] = worker

    def release(*_args: Any) -> None:
        retained = _DETACHED_WORKERS.pop(key, None)
        if retained is not None:
            _safe_delete_later(retained)

    connected = connect_qthread_finished(worker, release)
    settled = getattr(worker, "settled", None)
    if not connected and settled is not None:
        try:
            settled.connect(release)
            connected = True
        except Exception:
            connected = False

    if not connected:
        for signal_name in ("finished", "error", "cancelled"):
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(release)
                connected = True
            except Exception:
                pass

    try:
        if not worker.isRunning():
            release()
    except Exception:
        if not connected:
            release()


def retain_qthread_until_finished(thread: Any, *objects: Any) -> None:
    """Keep a QThread and moved worker alive after a cancellation timeout."""
    if thread is None:
        return
    retained_objects = tuple(obj for obj in (thread, *objects) if obj is not None)
    key = id(thread)
    _DETACHED_WORKERS[key] = retained_objects

    def release(*_args: Any) -> None:
        retained = _DETACHED_WORKERS.pop(key, ())
        for obj in retained:
            _safe_delete_later(obj)

    try:
        thread.finished.connect(release)
    except Exception:
        pass
    try:
        if not thread.isRunning():
            release()
    except Exception:
        pass


class ReadConnectionProtocol(Protocol):
    def execute(self, sql: str) -> Any:
        ...

    def close(self) -> None:
        ...


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


@contextmanager
def perf_timer(scope: str, meta: str = ""):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(f"PERF|{scope}|{elapsed_ms:.2f}ms|{meta}")


class AsyncJobWorker(QThread):
    """단발성 비동기 작업 수행 워커"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    settled = pyqtSignal()

    def __init__(self, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            result = self.job_func(*self.args, **self.kwargs)
            if self.isInterruptionRequested():
                return
            self.finished.emit(result)
        except Exception as e:
            if self.isInterruptionRequested():
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        self.quit()
        self.wait(100)


class JobCancelledError(Exception):
    """Raised when a long-running worker is cancelled cooperatively."""


class ApiErrorMeta(TypedDict):
    kind: str
    status_code: int
    cooldown_seconds: int
    retryable: bool


class LongTaskContext:
    """Cancellation/progress helper passed to repetitive background jobs."""

    def __init__(self, worker: "IterativeJobWorker"):
        self._worker = worker

    def is_cancelled(self) -> bool:
        return self._worker.isInterruptionRequested()

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelledError("cancelled")

    def report(
        self,
        *,
        current: int = 0,
        total: int = 0,
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        progress_payload: Dict[str, Any] = {
            "current": max(0, int(current)),
            "total": max(0, int(total)),
            "message": str(message or ""),
        }
        if payload:
            progress_payload.update(payload)
        self._worker.progress.emit(progress_payload)


class IterativeJobWorker(QThread):
    """Cancel-aware worker for repetitive or chunked background tasks."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(object)
    cancelled = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        context = LongTaskContext(self)
        try:
            context.check_cancelled()
            result = self.job_func(context, *self.args, **self.kwargs)
            context.check_cancelled()
            self.finished.emit(result)
        except JobCancelledError:
            self.cancelled.emit()
        except Exception as e:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        self.quit()
        self.wait(100)


class InterruptibleReadWorker(QThread):
    """Dedicated read worker backed by an interruptible SQLite connection."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, db_manager, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.db = db_manager
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
        self._conn: Optional[ReadConnectionProtocol] = None

    def run(self):
        try:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return

            open_read_connection = getattr(self.db, "open_read_connection", None)
            conn: Optional[ReadConnectionProtocol]
            if callable(open_read_connection):
                conn = cast(Optional[ReadConnectionProtocol], open_read_connection(timeout=1.5))
            else:
                conn = None
            self._conn = conn
            if conn is not None:
                conn.execute("BEGIN")

            result = self.job_func(conn, *self.args, **self.kwargs)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except JobCancelledError:
            self.cancelled.emit()
        except sqlite3.OperationalError as e:
            interrupted = "interrupted" in str(e).lower()
            if self.isInterruptionRequested() or interrupted:
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        except Exception as e:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            conn = self._conn
            self._conn = None
            if conn is not None:
                try:
                    close_read_connection = getattr(self.db, "close_read_connection", None)
                    if callable(close_read_connection):
                        close_read_connection(conn)
                    else:
                        conn.close()
                except Exception:
                    pass
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        if self._conn is not None:
            try:
                interrupt_connection = getattr(self.db, "interrupt_connection", None)
                if callable(interrupt_connection):
                    interrupt_connection(self._conn)
            except Exception:
                pass
        self.quit()
        self.wait(100)


@dataclass(frozen=True)
class DBQueryScope:
    keyword: str
    filter_txt: str = ""
    sort_mode: str = ""
    only_bookmark: bool = False
    only_unread: bool = False
    hide_duplicates: bool = False
    exclude_words: Tuple[str, ...] = field(default_factory=tuple)
    blocked_publishers: Tuple[str, ...] = field(default_factory=tuple)
    preferred_publishers: Tuple[str, ...] = field(default_factory=tuple)
    only_preferred_publishers: bool = False
    tag_filter: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    query_key: Optional[str] = None

    def count_kwargs(self) -> Dict[str, Any]:
        return {
            "keyword": self.keyword,
            "only_bookmark": self.only_bookmark,
            "only_unread": self.only_unread,
            "hide_duplicates": self.hide_duplicates,
            "filter_txt": self.filter_txt,
            "exclude_words": list(self.exclude_words),
            "blocked_publishers": list(self.blocked_publishers),
            "preferred_publishers": list(self.preferred_publishers),
            "only_preferred_publishers": self.only_preferred_publishers,
            "tag_filter": self.tag_filter,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "query_key": self.query_key,
        }

    def fetch_kwargs(self) -> Dict[str, Any]:
        kwargs = self.count_kwargs()
        kwargs["sort_mode"] = self.sort_mode
        return kwargs


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
                                f"kw={self.db_keyword}|query_key={self.query_key}|items={len(items)}",
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
                            self._emit_error(
                                f"데이터베이스 조회 실패: {e}",
                                kind="db_query_error",
                            )
                            return
                        except DatabaseWriteError as e:
                            logger.error("ApiWorker DB write failed: %s - %s", self.display_keyword, e)
                            if not self.is_running:
                                logger.info(f"ApiWorker cancelled on DB write error: {self.display_keyword}")
                                return
                            self._emit_error(
                                f"데이터베이스 저장 실패: {e}",
                                kind="db_write_error",
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


class DBWorker(QThread):
    """DB 조회 전용 워커 스레드(UI 블로킹 방지)"""

    finished = pyqtSignal(list, int)
    error = pyqtSignal(str)
    settled = pyqtSignal()

    def __init__(
        self,
        db_manager,
        scope: DBQueryScope,
        limit: Optional[int] = None,
        offset: int = 0,
        include_total: bool = True,
        known_total_count: Optional[int] = None,
    ):
        super().__init__()
        self.db = db_manager
        self.scope = scope
        self.limit = limit
        self.offset = offset
        self.include_total = include_total
        self.known_total_count = known_total_count
        self._is_cancelled = False
        self.last_unread_count = 0
        self._conn = None

    def stop(self):
        self._is_cancelled = True
        if self._conn is not None:
            try:
                interrupt_connection = getattr(self.db, "interrupt_connection", None)
                if callable(interrupt_connection):
                    interrupt_connection(self._conn)
            except Exception:
                pass
        self.quit()
        self.wait(100)

    def run(self):
        try:
            with perf_timer(
                "ui.dbworker.run",
                f"kw={self.scope.keyword}|bookmark={int(self.scope.only_bookmark)}|include_total={int(self.include_total)}",
            ):
                if self._is_cancelled:
                    return

                open_read_connection = getattr(self.db, "open_read_connection", None)
                conn: Any
                if callable(open_read_connection):
                    conn = open_read_connection(timeout=1.5)
                else:
                    conn = None
                self._conn = conn
                if conn is not None:
                    conn.execute("BEGIN")

                if not self.scope.only_bookmark and not str(self.scope.keyword or "").strip():
                    self.finished.emit([], 0)
                    return

                count_kwargs = self.scope.count_kwargs()
                total_count = int(self.known_total_count or 0)
                if self.include_total:
                    total_count = self.db.count_news(conn=conn, **self.scope.count_kwargs())

                if count_kwargs.get("only_unread", False):
                    unread_count = total_count
                else:
                    unread_count_kwargs = dict(count_kwargs)
                    unread_count_kwargs["only_unread"] = True
                    unread_count = self.db.count_news(conn=conn, **unread_count_kwargs)
                self.last_unread_count = int(unread_count or 0)

                if self._is_cancelled:
                    return

                data = self.db.fetch_news(
                    conn=conn,
                    limit=self.limit,
                    offset=self.offset,
                    **self.scope.fetch_kwargs(),
                )

                if self._is_cancelled:
                    return

                self.finished.emit(data, total_count)
        except Exception as e:
            if self._is_cancelled or "interrupted" in str(e).lower():
                logger.info("DBWorker cancelled during query: %s", self.scope.keyword)
                return
            logger.exception("DBWorker failed: %s", self.scope.keyword)
            self.error.emit(str(e))
        finally:
            if self._conn is not None:
                try:
                    close_read_connection = getattr(self.db, "close_read_connection", None)
                    if callable(close_read_connection):
                        close_read_connection(self._conn)
                except Exception:
                    pass
                self._conn = None
            self.settled.emit()
