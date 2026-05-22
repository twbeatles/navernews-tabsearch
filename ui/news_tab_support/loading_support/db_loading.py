# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Optional, Tuple

from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import QApplication, QScrollBar

from core.text_utils import perf_timer
from core.workers import DBWorker, retain_worker_until_finished

logger = logging.getLogger(__name__)


class _NewsTabDbLoadingMixin:
    def _browser_scroll_bar(self) -> QScrollBar:
        scroll_bar = self.browser.verticalScrollBar()
        if scroll_bar is None:
            raise RuntimeError("News browser scrollbar is unavailable")
        return scroll_bar

    def _clipboard(self) -> QClipboard:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Clipboard is unavailable")
        return clipboard

    def load_data_from_db(self, append: bool = False):
        """DB에서 현재 필터 범위의 페이지를 로드한다."""
        if getattr(self, "_is_closing", False):
            return
        if self._should_block_db_action("tab DB reload", notify=False):
            return
        with perf_timer("ui.load_data_from_db", f"kw={self.keyword}|append={int(append)}"):
            if self.worker and self.worker.isRunning():
                old_worker = self.worker
                previous_request_id = self._load_request_id
                self._detach_worker_signals(old_worker, ("finished", "error"))
                old_worker.stop()
                if not old_worker.wait(150):
                    logger.warning("DBWorker wait timeout: %s", self.keyword)
                    retain_worker_until_finished(old_worker)
                else:
                    self._initial_load_inflight = False
                self._cancelled_initial_request_ids.discard(previous_request_id)
                if self._initial_request_id == previous_request_id:
                    self._initial_request_id = None

            if not append:
                self._loaded_offset = 0
                self._is_loading_more = False
                if not self._initial_load_completed:
                    self._initial_load_inflight = True
                    self._initial_load_deferred = False
            elif self._is_loading_more:
                return

            self._load_request_id += 1
            current_request_id = self._load_request_id
            if append:
                self._pending_append_request_ids.add(current_request_id)
                self._pending_scroll_restore = self._browser_scroll_bar().value()
                self._is_loading_more = True
            else:
                self._pending_append_request_ids.clear()
                self._pending_scroll_restore = 0
                if not self._initial_load_completed:
                    self._initial_request_id = current_request_id
                    self._cancelled_initial_request_ids.discard(current_request_id)

            self.lbl_status.setText("⏳ 데이터 로딩 중...")
            self.btn_load.setEnabled(False)

            scope = self._build_query_scope()
            self._request_scope_signatures[current_request_id] = self._scope_signature(scope)
            offset = self._loaded_offset if append else 0
            self.worker = DBWorker(
                self.db,
                scope=scope,
                limit=self.PAGE_SIZE,
                offset=offset,
                include_total=not append,
                known_total_count=self._total_filtered_count if append else None,
            )
            self.worker.finished.connect(
                lambda data, total_count, rid=current_request_id, worker_ref=self.worker: self._handle_db_worker_loaded(
                    data,
                    total_count,
                    request_id=rid,
                    unread_count=getattr(worker_ref, "last_unread_count", None),
                )
            )
            self.worker.error.connect(lambda err_msg, rid=current_request_id: self._handle_db_worker_error(err_msg, rid))
            self.worker.start()

    def _handle_db_worker_callback_failure(
        self,
        phase: str,
        exc: BaseException,
        request_id: Optional[int],
    ) -> None:
        logger.exception(
            "NewsTab DB worker %s callback failed (%s, rid=%s): %s",
            phase,
            self.keyword,
            request_id,
            exc,
        )
        if request_id is not None:
            self._request_scope_signatures.pop(request_id, None)
            self._pending_append_request_ids.discard(request_id)
        if request_id is None or request_id == self._load_request_id:
            self._is_loading_more = False
            self._pending_scroll_restore = 0
            self._initial_request_id = None
            self._initial_load_inflight = False
            try:
                self.btn_load.setEnabled(True)
            except Exception:
                pass
            try:
                self.lbl_status.setText(f"⚠️ 데이터 표시 중 오류: {exc}")
            except Exception:
                pass

    def _handle_db_worker_loaded(
        self,
        data,
        total_count,
        request_id: Optional[int] = None,
        unread_count: Optional[int] = None,
    ) -> None:
        try:
            self.on_data_loaded(
                data,
                total_count,
                request_id=request_id,
                unread_count=unread_count,
            )
        except Exception as exc:
            self._handle_db_worker_callback_failure("loaded", exc, request_id)

    def _handle_db_worker_error(self, err_msg, request_id: Optional[int] = None) -> None:
        try:
            self.on_data_error(err_msg, request_id)
        except Exception as exc:
            self._handle_db_worker_callback_failure("error", exc, request_id)

    def on_data_loaded(
        self,
        data,
        total_count,
        request_id: Optional[int] = None,
        unread_count: Optional[int] = None,
    ):
        """데이터 로드 완료 시 호출"""
        if request_id is not None and self._finalize_cancelled_initial_request(request_id):
            logger.info("PERF|ui.on_data_loaded.cancelled|0.00ms|kw=%s|rid=%s", self.keyword, request_id)
            return
        if getattr(self, "_is_closing", False):
            if request_id is not None:
                self._request_scope_signatures.pop(request_id, None)
                self._pending_append_request_ids.discard(request_id)
            return
        if request_id is not None and request_id != self._load_request_id:
            self._request_scope_signatures.pop(request_id, None)
            logger.info("PERF|ui.on_data_loaded.stale|0.00ms|kw=%s|rid=%s", self.keyword, request_id)
            return

        with perf_timer("ui.on_data_loaded", f"kw={self.keyword}|rows={len(data)}"):
            was_initial_hydration = not self._initial_load_completed
            scope_signature = None
            if request_id is not None:
                scope_signature = self._request_scope_signatures.pop(request_id, None)
            is_append = bool(request_id in self._pending_append_request_ids)
            if request_id is not None:
                self._pending_append_request_ids.discard(request_id)
            if scope_signature is None:
                scope_signature = self._scope_signature(self._build_query_scope())

            append_from_index: Optional[int] = None
            prepared_rows = [dict(item) for item in data]
            if is_append and scope_signature == self._last_loaded_scope_signature:
                append_from_index = len(self.news_data_cache)
                prepared_rows = self._index_items(prepared_rows)
                self.news_data_cache.extend(prepared_rows)
                if hasattr(self.browser, "set_preview_data"):
                    self.browser.set_preview_data(dict(self._preview_data_cache))
            else:
                prepared_rows = [self._prepare_item(item) for item in prepared_rows]
                self.news_data_cache = prepared_rows
                self._loaded_offset = 0
                self._rebuild_item_indexes()

            self.filtered_data_cache = list(self.news_data_cache)
            self._loaded_offset = len(self.news_data_cache)
            self._rendered_count = len(self.filtered_data_cache)
            self._total_filtered_count = int(total_count or 0)
            self._last_loaded_scope_signature = scope_signature
            self._last_filter_text = self._current_filter_text().lower()
            if unread_count is None:
                self._recount_unread_cache()
            else:
                self._unread_count_cache = max(0, int(unread_count or 0))
            self._data_version += 1
            self._last_render_signature = None
            self._is_loading_more = False
            self.btn_load.setEnabled(True)
            if not is_append:
                self._initial_request_id = None
                self._initial_load_completed = True
                self._initial_load_inflight = False

            if self.total_api_count <= 0 and self._total_filtered_count > self.total_api_count:
                self.total_api_count = self._total_filtered_count

            restore_scroll = None
            if is_append and self._pending_scroll_restore > 0:
                restore_scroll = self._pending_scroll_restore
            self._pending_scroll_restore = 0
            self._schedule_render(
                append_from_index=append_from_index,
                restore_scroll=restore_scroll,
            )

            parent = self._main_window()
            if parent is not None:
                parent.sync_tab_load_more_state(self.keyword)
                if not self.news_data_cache and not self.is_bookmark_tab:
                    parent.maybe_show_query_refresh_hint(self.keyword)
            if was_initial_hydration and not is_append:
                self.hydration_finished.emit(self.keyword)

    def on_data_error(self, err_msg, request_id: Optional[int] = None):
        """데이터 로드 오류 시 호출"""
        if request_id is not None and self._finalize_cancelled_initial_request(request_id):
            logger.info("PERF|ui.on_data_error.cancelled|0.00ms|kw=%s|rid=%s", self.keyword, request_id)
            return
        if getattr(self, "_is_closing", False):
            if request_id is not None:
                self._request_scope_signatures.pop(request_id, None)
                self._pending_append_request_ids.discard(request_id)
            return
        if request_id is not None and request_id != self._load_request_id:
            self._request_scope_signatures.pop(request_id, None)
            return
        if request_id is not None:
            self._pending_append_request_ids.discard(request_id)
            self._request_scope_signatures.pop(request_id, None)
        was_initial_hydration = not self._initial_load_completed
        self._is_loading_more = False
        self._pending_scroll_restore = 0
        self._initial_request_id = None
        self._initial_load_inflight = False
        self.lbl_status.setText(f"⚠️ 오류: {err_msg}")
        self.btn_load.setEnabled(True)
        parent = self._main_window()
        if parent is not None:
            parent.sync_tab_load_more_state(self.keyword)
            parent.show_warning_toast(f"'{self.keyword}' DB 조회에 실패했습니다.")
        if was_initial_hydration:
            self.hydration_failed.emit(self.keyword, str(err_msg))

    def apply_filter(self):
        """필터 변경 시 DB 기반으로 첫 페이지부터 다시 조회한다."""
        with perf_timer("ui.apply_filter", f"kw={self.keyword}|rows={len(self.news_data_cache)}"):
            filter_txt = self._current_filter_text()
            if filter_txt:
                self.inp_filter.setObjectName("FilterActive")
            else:
                self.inp_filter.setObjectName("")
            self.inp_filter.setStyle(self.inp_filter.style())

            current_scope_signature = self._scope_signature(self._build_query_scope())
            if current_scope_signature == self._last_loaded_scope_signature and self._loaded_offset <= self.PAGE_SIZE:
                self.update_status_label()
                return

            self._last_filter_text = filter_txt.lower()
            self._request_db_reload("필터 변경", append=False)

    def append_items(self):
        """다음 DB 페이지를 로드한다."""
        if self._is_loading_more:
            return
        if len(self.filtered_data_cache) >= self._total_filtered_count:
            return
        self._request_db_reload("더 보기", append=True)

    def update_timestamp(self):
        """업데이트 시간 갱신"""
        self.last_update = datetime.now().strftime("%H:%M:%S")
