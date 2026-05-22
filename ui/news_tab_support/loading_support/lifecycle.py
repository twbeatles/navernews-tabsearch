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


class _NewsTabLoadingLifecycleMixin:
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
        else:
            self._request_scope_signatures.pop(request_id, None)
            self._pending_append_request_ids.discard(request_id)
            self._pending_scroll_restore = 0
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
            "btn_delete_search",
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
            worker = self.worker
            self._detach_worker_signals(self.worker, ("finished", "error"))
            try:
                if worker.isRunning():
                    worker.stop()
                    if not worker.wait(1000):
                        logger.warning("DBWorker cleanup wait timeout: %s", self.keyword)
                        retain_worker_until_finished(worker)
            except Exception as exc:
                logger.warning("DBWorker cleanup failed (%s): %s", self.keyword, exc)
            finally:
                self.worker = None

        if hasattr(self, "job_worker") and self.job_worker:
            job_worker = self.job_worker
            self._detach_worker_signals(job_worker, ("finished", "error", "cancelled", "progress"))
            try:
                if job_worker.isRunning():
                    try:
                        job_worker.stop()
                    except Exception:
                        job_worker.requestInterruption()
                        job_worker.quit()
                        job_worker.wait(100)
                    if not job_worker.wait(300):
                        try:
                            job_worker.setParent(None)
                        except Exception:
                            pass
                        retain_worker_until_finished(job_worker)
                        logger.warning("Job worker cleanup wait timeout: %s", self.keyword)
                else:
                    try:
                        job_worker.deleteLater()
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
