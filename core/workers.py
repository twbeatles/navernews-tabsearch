import html
import json
import logging
import re
import threading
import time
import traceback
import urllib.parse
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.query_parser import parse_tab_query


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

    def __init__(self, job_func, *args, **kwargs):
        super().__init__()
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.job_func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()


class ApiWorker(QObject):
    """API 호출 워커 (재시도 로직 및 백그라운드 DB 저장 포함)"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        keyword: str,
        exclude_words: List[str],
        db_manager,
        start_idx: int = 1,
        max_retries: int = 3,
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.keyword = keyword
        self.exclude_words = exclude_words
        self.db = db_manager
        self.start = start_idx
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session
        self._is_running = True
        self._lock = threading.Lock()
        self._destroyed = False

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
            logger.warning(f"시그널 발신 실패 (객체 삭제됨): {self.keyword}")
        except Exception as e:
            logger.error(f"시그널 발신 오류: {e}")

    def run(self):
        logger.info(f"ApiWorker 시작: {self.keyword}")

        if not self.is_running:
            return

        headers = {
            "X-Naver-Client-Id": self.cid.strip(),
            "X-Naver-Client-Secret": self.csec.strip(),
        }
        url = "https://openapi.naver.com/v1/search/news.json"
        session = self.session or requests.Session()
        owns_session = self.session is None

        try:
            with perf_timer("api.run", f"kw={self.keyword}|max_retries={self.max_retries}"):
                for attempt in range(self.max_retries):
                    if not self.is_running:
                        logger.info(f"ApiWorker 중단됨: {self.keyword}")
                        return

                    try:
                        self._safe_emit(
                            self.progress,
                            f"'{self.keyword}' 검색 중... (시도 {attempt + 1}/{self.max_retries})",
                        )

                        params = {
                            "query": self.keyword,
                            "display": 100,
                            "start": self.start,
                            "sort": "date",
                        }

                        with perf_timer("api.request", f"kw={self.keyword}|attempt={attempt + 1}"):
                            resp = session.get(url, headers=headers, params=params, timeout=self.timeout)

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

                        with perf_timer("api.parse", f"kw={self.keyword}"):
                            data = resp.json()
                            raw_items = data.get("items", [])
                            items: List[Dict[str, Any]] = []
                            filtered_count = 0

                            for item in raw_items:
                                if not self.is_running:
                                    break

                                title = html.unescape(RE_BOLD_TAGS.sub("", item.get("title", "")))
                                desc = html.unescape(RE_BOLD_TAGS.sub("", item.get("description", "")))

                                if self.exclude_words:
                                    should_exclude = False
                                    for ex in self.exclude_words:
                                        if ex and (ex in title or ex in desc):
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

                        self._safe_emit(self.progress, f"'{self.keyword}' 저장 중...")
                        search_keyword_only, _ = parse_tab_query(self.keyword)
                        if not search_keyword_only:
                            search_keyword_only = self.keyword

                        with perf_timer("api.upsert", f"kw={search_keyword_only}|items={len(items)}"):
                            added_count, dup_count = self.db.upsert_news(items, search_keyword_only)

                        result = {
                            "items": items,
                            "total": data.get("total", 0),
                            "filtered": filtered_count,
                            "added_count": added_count,
                            "dup_count": dup_count,
                        }

                        logger.info(
                            f"ApiWorker 완료: {self.keyword} ({len(items)}개, 추가 {added_count}, 중복 {dup_count})"
                        )
                        self._safe_emit(self.progress, f"'{self.keyword}' 완료 (추가: {added_count}개)")
                        self._safe_emit(self.finished, result)
                        return

                    except requests.Timeout:
                        logger.warning(f"API 타임아웃: {self.keyword} (시도 {attempt + 1})")
                        if attempt < self.max_retries - 1:
                            self._safe_emit(self.progress, "요청 시간 초과. 재시도 중...")
                            time.sleep(1)
                            continue
                        self._safe_emit(self.error, "요청 시간이 초과되었습니다. 네트워크 연결을 확인해주세요.")
                        return

                    except requests.RequestException as e:
                        logger.warning(f"네트워크 오류: {self.keyword} - {e}")
                        if attempt < self.max_retries - 1:
                            self._safe_emit(self.progress, "네트워크 오류. 재시도 중...")
                            time.sleep(1)
                            continue
                        self._safe_emit(self.error, f"네트워크 오류: {str(e)}")
                        return

                    except Exception as e:
                        logger.error(f"ApiWorker 예외: {self.keyword} - {e}")
                        traceback.print_exc()
                        self._safe_emit(self.error, f"오류 발생: {str(e)}")
                        return
        finally:
            if owns_session:
                try:
                    session.close()
                except Exception:
                    pass

    def stop(self):
        logger.info(f"ApiWorker 중지 요청: {self.keyword}")
        self._destroyed = True
        self.is_running = False


class DBWorker(QThread):
    """DB 조회 전용 워커 스레드(UI 블로킹 방지)"""

    finished = pyqtSignal(list, int)
    error = pyqtSignal(str)

    def __init__(
        self,
        db_manager,
        keyword: str,
        filter_txt: str = "",
        sort_mode: str = "최신순",
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        super().__init__()
        self.db = db_manager
        self.keyword = keyword
        self.filter_txt = filter_txt
        self.sort_mode = sort_mode
        self.only_bookmark = only_bookmark
        self.only_unread = only_unread
        self.hide_duplicates = hide_duplicates
        self.start_date = start_date
        self.end_date = end_date
        self._is_cancelled = False

    def stop(self):
        self._is_cancelled = True
        self.quit()
        self.wait(100)

    def run(self):
        try:
            with perf_timer("ui.dbworker.run", f"raw_kw={self.keyword}|bookmark={int(self.only_bookmark)}"):
                if self._is_cancelled:
                    return

                search_keyword, exclude_words = parse_tab_query(self.keyword)
                if self.only_bookmark:
                    search_keyword = ""

                if not search_keyword and not self.only_bookmark:
                    self.finished.emit([], 0)
                    return

                data = self.db.fetch_news(
                    keyword=search_keyword,
                    filter_txt=self.filter_txt,
                    sort_mode=self.sort_mode,
                    only_bookmark=self.only_bookmark,
                    only_unread=self.only_unread,
                    hide_duplicates=self.hide_duplicates,
                    exclude_words=exclude_words,
                    start_date=self.start_date,
                    end_date=self.end_date,
                )

                total_count = len(data)

                if self._is_cancelled:
                    return

                self.finished.emit(data, total_count)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()
