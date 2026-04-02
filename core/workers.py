import html
import json
import logging
import re
import threading
import time
import traceback
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, cast

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.protocols import ClosableProtocol, RequestGetProtocol
from core.query_parser import build_fetch_key


logger = logging.getLogger(__name__)

RE_BOLD_TAGS = re.compile(r"</?b>")


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

    def stop(self):
        self.requestInterruption()
        self.quit()
        self.wait(100)


class JobCancelledError(Exception):
    """Raised when a long-running worker is cancelled cooperatively."""


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

    def stop(self):
        self.requestInterruption()
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
        self._is_running = True
        self._lock = threading.Lock()
        self._destroyed = False
        self._request_session: Optional[ClosableProtocol] = None
        self._owns_request_session = False

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
        session: RequestGetProtocol = self.session or requests.Session()
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
                            resp = session.get(url, headers=headers, params=params, timeout=self.timeout)
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled after response: {self.display_keyword}")
                            return

                        if resp.status_code == 429:
                            if attempt < self.max_retries - 1:
                                wait_time = (attempt + 1) * 2
                                self._safe_emit(self.progress, f"요청 제한 초과. {wait_time}초 후 재시도...")
                                for _ in range(wait_time):
                                    if not self.is_running:
                                        return
                                    time.sleep(1)
                                continue
                            self._safe_emit(self.error, "API 요청 제한 초과. 잠시 후 다시 시도해주세요.")
                            return

                        if resp.status_code != 200:
                            try:
                                error_data = resp.json()
                                error_msg = error_data.get("errorMessage", "알 수 없는 오류")
                                error_code = error_data.get("errorCode", "")
                            except (json.JSONDecodeError, KeyError, ValueError):
                                error_msg = f"HTTP {resp.status_code}"
                                error_code = ""
                            self._safe_emit(self.error, f"API 오류 {resp.status_code} ({error_code}): {error_msg}")
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

                                naver_link = item.get("link", "")
                                org_link = item.get("originallink", "")
                                if "news.naver.com" in naver_link:
                                    final_link = naver_link
                                elif "news.naver.com" in org_link:
                                    final_link = org_link
                                else:
                                    final_link = naver_link if naver_link else org_link

                                publisher = "정보 없음"
                                if org_link:
                                    publisher = urllib.parse.urlparse(org_link).netloc.replace("www.", "")
                                elif final_link:
                                    if "news.naver.com" in final_link:
                                        publisher = "네이버뉴스"
                                    else:
                                        publisher = urllib.parse.urlparse(final_link).netloc.replace("www.", "")

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

                        with perf_timer("api.upsert", f"kw={self.db_keyword}|query_key={self.query_key}|items={len(items)}"):
                            added_count, dup_count = self.db.upsert_news(
                                items,
                                self.db_keyword,
                                query_key=self.query_key,
                            )

                        result = {
                            "items": items,
                            "new_items": new_items,
                            "total": data.get("total", 0),
                            "filtered": filtered_count,
                            "added_count": added_count,
                            "dup_count": dup_count,
                        }

                        logger.info(
                            f"ApiWorker 완료: {self.display_keyword} ({len(items)}개, 추가 {added_count}, 중복 {dup_count})"
                        )
                        self._safe_emit(self.progress, f"'{self.display_keyword}' 완료 (추가: {added_count}개)")
                        self._safe_emit(self.finished, result)
                        return

                    except requests.Timeout:
                        logger.warning(f"API 타임아웃: {self.display_keyword} (시도 {attempt + 1})")
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on timeout: {self.display_keyword}")
                            return
                        if attempt < self.max_retries - 1:
                            self._safe_emit(self.progress, "요청 시간 초과. 재시도 중...")
                            time.sleep(1)
                            continue
                        self._safe_emit(self.error, "요청 시간이 초과되었습니다. 네트워크 연결을 확인해주세요.")
                        return

                    except requests.RequestException as e:
                        logger.warning(f"네트워크 오류: {self.display_keyword} - {e}")
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on request error: {self.display_keyword}")
                            return
                        if attempt < self.max_retries - 1:
                            self._safe_emit(self.progress, "네트워크 오류. 재시도 중...")
                            time.sleep(1)
                            continue
                        self._safe_emit(self.error, f"네트워크 오류: {str(e)}")
                        return

                    except Exception as e:
                        logger.error(f"ApiWorker 예외: {self.display_keyword} - {e}")
                        traceback.print_exc()
                        if not self.is_running:
                            logger.info(f"ApiWorker cancelled on exception: {self.display_keyword}")
                            return
                        self._safe_emit(self.error, f"오류 발생: {str(e)}")
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
        session = self._request_session
        if session is not None and self._owns_request_session:
            try:
                session.close()
            except Exception:
                pass


class DBWorker(QThread):
    """DB 조회 전용 워커 스레드(UI 블로킹 방지)"""

    finished = pyqtSignal(list, int)
    error = pyqtSignal(str)

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

    def stop(self):
        self._is_cancelled = True
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

                if not self.scope.only_bookmark and not str(self.scope.keyword or "").strip():
                    self.finished.emit([], 0)
                    return

                count_kwargs = self.scope.count_kwargs()
                total_count = int(self.known_total_count or 0)
                if self.include_total:
                    total_count = self.db.count_news(**self.scope.count_kwargs())

                if count_kwargs.get("only_unread", False):
                    unread_count = total_count
                else:
                    unread_count_kwargs = dict(count_kwargs)
                    unread_count_kwargs["only_unread"] = True
                    unread_count = self.db.count_news(**unread_count_kwargs)
                self.last_unread_count = int(unread_count or 0)

                if self._is_cancelled:
                    return

                data = self.db.fetch_news(
                    limit=self.limit,
                    offset=self.offset,
                    **self.scope.fetch_kwargs(),
                )

                if self._is_cancelled:
                    return

                self.finished.emit(data, total_count)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()
