# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Optional, Tuple

from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import QApplication, QScrollBar

from core.text_utils import perf_timer
from core.workers import DBWorker

logger = logging.getLogger(__name__)


class _NewsTabLoadingMixin:
    def needs_initial_hydration(self) -> bool:
        return not self._initial_load_completed

    def is_initial_hydration_inflight(self) -> bool:
        return bool(self._initial_load_inflight)

    def request_initial_hydration(self) -> bool:
        if self._is_closing or self._initial_load_completed or self._initial_load_inflight:
            return False
        self._initial_load_deferred = False
        self.load_data_from_db()
        return True

    def cancel_initial_hydration(self, wait_ms: int = 300) -> bool:
        request_id = self._initial_request_id
        if not self._initial_load_inflight or request_id is None:
            return True
        self._cancelled_initial_request_ids.add(request_id)
        self._initial_load_inflight = False
        self._initial_request_id = None
        if self.worker is None or not self.worker.isRunning():
            self._finalize_cancelled_initial_request(request_id)
            return True
        self.worker.stop()
        finished = self.worker.wait(max(50, int(wait_ms)))
        if finished:
            self._finalize_cancelled_initial_request(request_id)
        return finished

    def set_maintenance_mode(self, active: bool) -> None:
        self._maintenance_mode_active = bool(active)
        if self._maintenance_mode_active and hasattr(self, "filter_timer"):
            self.filter_timer.stop()

        controls = (
            "inp_filter",
            "combo_sort",
            "chk_unread",
            "chk_hide_dup",
            "chk_preferred_publishers",
            "combo_tag_filter",
            "combo_saved_search",
            "btn_apply_saved_search",
            "btn_save_search",
            "btn_date_toggle",
            "btn_load",
            "btn_read_all",
        )
        for attr_name in controls:
            control = getattr(self, attr_name, None)
            if control is not None:
                control.setEnabled(not self._maintenance_mode_active)

        self._refresh_date_filter_controls()

    def cancel_background_tasks_for_maintenance(self, wait_ms: int = 500) -> bool:
        deadline = time.monotonic() + (max(0, int(wait_ms)) / 1000.0)
        finished = True

        if self.worker is not None and self.worker.isRunning():
            if self._initial_load_inflight and self._initial_request_id is not None:
                remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
                if not self.cancel_initial_hydration(wait_ms=remaining_ms):
                    logger.warning("DBWorker maintenance wait timeout: %s", self.keyword)
                    finished = False
            else:
                self._detach_worker_signals(self.worker, ("finished", "error"))
                self.worker.stop()
                remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
                if not self.worker.wait(remaining_ms):
                    logger.warning("DBWorker maintenance wait timeout: %s", self.keyword)
                    finished = False
                else:
                    self._initial_load_inflight = False

        if self.job_worker is not None and self.job_worker.isRunning():
            self._detach_worker_signals(self.job_worker, ("finished", "error", "cancelled", "progress"))
            try:
                self.job_worker.stop()
            except Exception:
                self.job_worker.requestInterruption()
                self.job_worker.quit()
            remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
            if not self.job_worker.wait(remaining_ms):
                logger.warning("Job worker maintenance wait timeout: %s", self.keyword)
                finished = False

        self._is_loading_more = False
        self._pending_append_request_ids.clear()
        self._pending_scroll_restore = 0
        return finished

    def _browser_scroll_bar(self) -> QScrollBar:
        scroll_bar = self.browser.verticalScrollBar()
        if scroll_bar is None:
            raise RuntimeError("News browser scrollbar is unavailable")
        return scroll_bar

    def _detach_worker_signals(self, worker: Any, signal_names: Tuple[str, ...]) -> None:
        for signal_name in signal_names:
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect()
            except Exception:
                pass

    def _finalize_cancelled_initial_request(self, request_id: Optional[int]) -> bool:
        if request_id is None or request_id not in self._cancelled_initial_request_ids:
            return False
        self._cancelled_initial_request_ids.discard(request_id)
        self._request_scope_signatures.pop(request_id, None)
        self._pending_append_request_ids.discard(request_id)
        if self._initial_request_id == request_id:
            self._initial_request_id = None
        self._initial_load_inflight = False
        self._pending_scroll_restore = 0
        self._is_loading_more = False
        self.btn_load.setEnabled(True)
        if not self._initial_load_completed:
            self.lbl_status.setText("⏳ 로딩 대기 중...")
        return True

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
                previous_request_id = self._load_request_id
                self._detach_worker_signals(self.worker, ("finished", "error"))
                self.worker.stop()
                if not self.worker.wait(150):
                    logger.warning("DBWorker wait timeout: %s", self.keyword)
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
                lambda data, total_count, rid=current_request_id, worker_ref=self.worker: self.on_data_loaded(
                    data,
                    total_count,
                    request_id=rid,
                    unread_count=getattr(worker_ref, "last_unread_count", None),
                )
            )
            self.worker.error.connect(lambda err_msg, rid=current_request_id: self.on_data_error(err_msg, rid))
            self.worker.start()

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

            filter_txt_lc = filter_txt.lower()
            if filter_txt_lc == self._last_filter_text and self._loaded_offset <= self.PAGE_SIZE:
                self.update_status_label()
                return

            self._last_filter_text = filter_txt_lc
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

    def cleanup(self):
        """탭 종료 시 리소스 정리"""
        if getattr(self, "_cleanup_started", False):
            return
        self._cleanup_started = True
        self._is_closing = True

        if hasattr(self, "filter_timer") and self.filter_timer:
            self.filter_timer.stop()
        if hasattr(self, "_render_timer") and self._render_timer:
            self._render_timer.stop()
        self._request_scope_signatures.clear()
        self._pending_append_request_ids.clear()
        self._cancelled_initial_request_ids.clear()
        self._pending_scroll_restore = 0
        self._render_scheduled = False
        self._initial_request_id = None

        if hasattr(self, "worker") and self.worker:
            self._detach_worker_signals(self.worker, ("finished", "error"))
            try:
                if self.worker.isRunning():
                    self.worker.stop()
                    if not self.worker.wait(1000):
                        logger.warning("DBWorker cleanup wait timeout: %s", self.keyword)
            except Exception as exc:
                logger.warning("DBWorker cleanup failed (%s): %s", self.keyword, exc)
            finally:
                self.worker = None

        if hasattr(self, "job_worker") and self.job_worker:
            self._detach_worker_signals(self.job_worker, ("finished", "error", "cancelled", "progress"))
            try:
                if self.job_worker.isRunning():
                    try:
                        self.job_worker.stop()
                    except Exception:
                        self.job_worker.requestInterruption()
                        self.job_worker.quit()
                        self.job_worker.wait(100)
                    if not self.job_worker.wait(300):
                        try:
                            self.job_worker.setParent(None)
                        except Exception:
                            pass
                        try:
                            self.job_worker.finished.connect(self.job_worker.deleteLater)
                        except Exception:
                            pass
                        logger.warning("Job worker cleanup wait timeout: %s", self.keyword)
                else:
                    try:
                        self.job_worker.deleteLater()
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Job worker cleanup failed (%s): %s", self.keyword, exc)
            finally:
                self.job_worker = None
                self._end_mark_all_read_maintenance()
        elif getattr(self, "_mark_all_maintenance_active", False):
            self._end_mark_all_read_maintenance()

        logger.debug("NewsTab 정리 완료: %s", self.keyword)
