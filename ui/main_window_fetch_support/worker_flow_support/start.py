# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import html
import logging
import sys
import time
import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import QMutexLocker, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query, parse_tab_query
from core.text_utils import RE_HTML_TAGS
from core.validation import ValidationUtils
from core.worker_registry import WorkerHandle
from core.workers import ApiWorker, retain_qthread_until_finished

if TYPE_CHECKING:
    from ui.main_window import MainApp

logger = logging.getLogger(__name__)


def _facade_attr(name: str, default):
    facade = sys.modules.get("ui.main_window_fetch_support.worker_flow")
    return getattr(facade, name, default) if facade is not None else default


class _FetchWorkerStartMixin:
    def fetch_news(
        self: MainApp,
        keyword: str,
        is_more: bool = False,
        is_sequential: bool = False,
    ):
        """Fetch news for a tab."""
        if self.is_maintenance_mode_active():
            action = "더 불러오기" if is_more else "새로고침"
            msg = self._maintenance_block_message(action)
            logger.info("Fetch blocked during maintenance: kw=%s, action=%s", keyword, action)
            self._status_bar().showMessage(msg, 3000)
            if not is_sequential:
                self.show_warning_toast(msg)
            return

        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            if not is_sequential:
                self.show_warning_toast("탭 검색어에 일반 키워드가 없습니다. 탭 이름을 확인해주세요.")
            return

        db_keyword, _ = parse_tab_query(keyword)
        if not db_keyword:
            db_keyword = search_keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)
        query_key = fetch_key
        validate_credentials = getattr(self, "_validate_api_credentials", None)
        if callable(validate_credentials):
            valid, msg = validate_credentials()
        else:
            valid, msg = ValidationUtils.validate_api_credentials(
                str(getattr(self, "client_id", "") or ""),
                str(getattr(self, "client_secret", "") or ""),
            )
        if not valid:
            action = "더 불러오기" if is_more else "새로고침"
            block_msg = f"API 인증 정보가 준비되지 않아 {action}을(를) 실행할 수 없습니다. {msg}"
            logger.info("Fetch blocked by invalid API credentials: kw=%s, action=%s", keyword, action)
            self._status_bar().showMessage(block_msg, 3000)
            if is_sequential:
                self._on_sequential_fetch_done(keyword)
            else:
                self.show_warning_toast(block_msg)
            return

        cooldown_msg = self._fetch_cooldown_message("더 불러오기" if is_more else "새로고침")
        if cooldown_msg:
            logger.info("Fetch blocked by cooldown: kw=%s", keyword)
            self._status_bar().showMessage(cooldown_msg, 3000)
            if not is_sequential:
                self.show_warning_toast(cooldown_msg)
            return

        if not is_more and not is_sequential:
            now_ts = time.time()
            last_ts = self._last_fetch_request_ts.get(fetch_key, 0.0)
            if (now_ts - last_ts) < self._fetch_dedupe_window_sec:
                logger.info(
                    "PERF|net.fetch_deduped|0.00ms|kw=%s|window=%ss",
                    fetch_key,
                    self._fetch_dedupe_window_sec,
                )
                notified_keys = getattr(self, "_fetch_dedupe_notified_keys", set())
                if fetch_key not in notified_keys:
                    notified_keys.add(fetch_key)
                    self._fetch_dedupe_notified_keys = notified_keys
                    message = "같은 조건의 새로고침 요청이 너무 가까워 한 번 건너뛰었습니다."
                    self._status_bar().showMessage(message, 3000)
                    self.show_warning_toast(message)
                return
            self._last_fetch_request_ts[fetch_key] = now_ts

        fetch_state = self._tab_fetch_state.setdefault(keyword, self._make_tab_fetch_state())
        start_idx = 1
        if is_more:
            persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
            if persisted_cursor > fetch_state.last_api_start_index:
                fetch_state.last_api_start_index = persisted_cursor
            if fetch_state.last_api_start_index > 0:
                start_idx = fetch_state.last_api_start_index + 100
            else:
                start_idx = 101
            if start_idx > 1000:
                QMessageBox.information(
                    self,
                    "알림",
                    "네이버 검색 API는 최대 1,000건까지만 조회할 수 있습니다.",
                )
                if is_sequential:
                    self._on_sequential_fetch_done(keyword)
                return

        old_handle = self._worker_registry.get_active_handle(keyword)
        if old_handle:
            if not self.cleanup_worker(keyword=keyword, request_id=old_handle.request_id, only_if_active=True):
                logger.warning("Fetch skipped because previous worker is still stopping: %s", keyword)
                if located_tab := self._find_news_tab(keyword):
                    _tab_index, tab_widget = located_tab
                    btn_load = getattr(tab_widget, "btn_load", None)
                    if btn_load is not None:
                        btn_load.setEnabled(True)
                    self.sync_tab_load_more_state(keyword)
                if is_sequential:
                    self._on_sequential_fetch_done(keyword)
                else:
                    self.progress.setVisible(False)
                    self.btn_refresh.setEnabled(True)
                    self._status_bar().showMessage(
                        f"'{keyword}' 이전 새로고침이 아직 종료 중이라 이번 요청을 건너뛰었습니다.",
                        4000,
                    )
                return

        located_tab = self._find_news_tab(keyword)
        if located_tab is not None:
            _tab_index, tab_widget = located_tab
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("📄 로딩 중...")

        worker_cls = _facade_attr("ApiWorker", ApiWorker)
        worker = worker_cls(
            self.client_id,
            self.client_secret,
            search_keyword,
            db_keyword,
            exclude_words,
            self._require_db(),
            query_key=query_key,
            start_idx=start_idx,
            timeout=self.api_timeout,
            session_factory=self._require_http_client_config().create_session,
            display_keyword=keyword,
        )
        thread = QThread()
        worker.moveToThread(thread)

        request_id = self._next_worker_request_id()
        handle = WorkerHandle(
            request_id=request_id,
            tab_keyword=keyword,
            search_keyword=search_keyword,
            db_keyword=db_keyword,
            exclude_words=list(exclude_words),
            worker=worker,
            thread=thread,
        )
        self._request_start_index[request_id] = start_idx
        self._worker_registry.register(handle)
        self.workers[keyword] = (worker, thread)

        worker.finished.connect(
            lambda res, rid=request_id: self.on_fetch_done(res, keyword, is_more, is_sequential, rid)
        )
        worker.error.connect(
            lambda err, rid=request_id, worker_ref=worker: self.on_fetch_error(
                err,
                keyword,
                is_sequential,
                rid,
                getattr(worker_ref, "last_error_meta", None),
            )
        )
        if not is_sequential:
            worker.progress.connect(self._status_bar().showMessage)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id, kw=keyword: self.cleanup_worker(
                keyword=kw,
                request_id=rid,
                only_if_active=False,
            )
        )

        thread.started.connect(worker.run)
        thread.start()

    def _validate_api_credentials(self: MainApp):
        return ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
