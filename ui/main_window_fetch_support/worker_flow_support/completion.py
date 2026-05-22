# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import html
import logging
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


class _FetchWorkerCompletionMixin:
    def on_fetch_done(
        self: MainApp,
        result: Dict,
        keyword: str,
        is_more: bool,
        is_sequential: bool = False,
        request_id: Optional[int] = None,
    ):
        """Handle a successful fetch result."""
        try:
            if not self._is_active_worker_request(keyword, request_id):
                logger.info("stale on_fetch_done ignored: kw=%s, rid=%s", keyword, request_id)
                return

            search_keyword, exclude_words = parse_search_query(keyword)
            if not search_keyword:
                search_keyword = keyword
            fetch_key = build_fetch_key(search_keyword, exclude_words)

            new_items = list(result.get("new_items", []) or [])
            new_count = int(result.get("new_count", len(new_items)) or 0)
            added_count = int(result.get("added_count", 0) or 0)
            dup_count = int(result.get("dup_count", 0) or 0)
            total = int(result.get("total", 0) or 0)
            filtered_count = int(result.get("filtered", 0) or 0)
            notifiable_new_items = list(new_items)

            completed_start_idx = None
            if request_id is not None:
                completed_start_idx = self._request_start_index.get(request_id)
                if completed_start_idx is not None:
                    self._tab_fetch_state.setdefault(
                        keyword,
                        self._make_tab_fetch_state(),
                    ).last_api_start_index = completed_start_idx
                    if completed_start_idx > 0:
                        self._fetch_cursor_by_key[fetch_key] = int(completed_start_idx)

            self._fetch_total_by_key[fetch_key] = total
            if new_items:
                for item in new_items:
                    item.setdefault("keyword", keyword)
                    item.setdefault("db_keyword", parse_tab_query(keyword)[0] or search_keyword)
                apply_rules = getattr(self, "_apply_automation_rules_to_items", None)
                if callable(apply_rules):
                    try:
                        applied = apply_rules(new_items, dry_run=False)
                        if int(applied.get("matched", 0) or 0) > 0:
                            logger.info("Automation rules applied to new items: %s", applied)
                        suppressed_links = {
                            str(link)
                            for link in (applied.get("suppressed_links", []) or [])
                            if str(link or "").strip()
                        }
                        if suppressed_links:
                            notifiable_new_items = [
                                item
                                for item in notifiable_new_items
                                if str(item.get("link") or "") not in suppressed_links
                            ]
                    except Exception as exc:
                        logger.warning("Automation rule application failed: %s", exc)
                        applied = dict(getattr(self, "_last_automation_rule_result", {}) or {})
                        suppressed_links = {
                            str(link)
                            for link in (applied.get("suppressed_links", []) or [])
                            if str(link or "").strip()
                        }
                        if suppressed_links:
                            notifiable_new_items = [
                                item
                                for item in notifiable_new_items
                                if str(item.get("link") or "") not in suppressed_links
                            ]
                        failure_msg = "새 기사 저장은 완료, 자동화 적용 실패"
                        self._status_bar().showMessage(f"⚠️ {failure_msg}: {exc}", 5000)
                        if not is_sequential:
                            self.show_warning_toast(failure_msg)

            located_tab = self._find_news_tab(keyword)
            if located_tab is not None:
                _tab_index, tab_widget = located_tab
                tab_widget.total_api_count = total
                tab_widget.update_timestamp()

                last_api_start_index = completed_start_idx
                if last_api_start_index is None:
                    last_api_start_index = self._tab_fetch_state.setdefault(
                        keyword,
                        self._make_tab_fetch_state(),
                    ).last_api_start_index
                self._apply_load_more_button_state(tab_widget, total, last_api_start_index)
                tab_widget.load_data_from_db()

                if not is_more:
                    tab_widget.lbl_status.setText(
                        self._build_fetch_summary_message(
                            keyword,
                            new_count=new_count,
                            dup_count=dup_count,
                            filtered_count=filtered_count,
                        )
                    )

            notification_new_count = len(notifiable_new_items) if new_items else new_count

            if not is_sequential:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)

                if not is_more:
                    toast_msg = self._build_fetch_summary_message(
                        keyword,
                        new_count=new_count,
                        dup_count=dup_count,
                        filtered_count=filtered_count,
                    )
                    self.show_toast(toast_msg)
                    self._status_bar().showMessage(toast_msg, 3000)
                    self._notify_fetch_new_items(
                        keyword,
                        new_count=notification_new_count,
                        new_items=notifiable_new_items,
                    )
            else:
                self._notify_fetch_new_items(
                    keyword,
                    new_count=notification_new_count,
                    new_items=notifiable_new_items,
                )
                self._sequential_new_count += new_count
                self._sequential_added_count += added_count
                self._sequential_dup_count += dup_count
                self._on_sequential_fetch_done(keyword)

            if not is_more:
                last_by_keyword = dict(getattr(self, "_last_auto_refresh_by_keyword", {}) or {})
                last_by_keyword[keyword] = time.time()
                self._last_auto_refresh_by_keyword = last_by_keyword

            self._network_error_count = 0
            self._network_available = True
            self.update_tab_badge(keyword)
            self._schedule_tab_hydration(50)
        except Exception as e:
            logger.error("on_fetch_done failed: %s", e)
            traceback.print_exc()
            self._status_bar().showMessage(f"❌ 처리 중 오류: {e}")
            if not is_sequential:
                self.progress.setVisible(False)
                self.btn_refresh.setEnabled(True)
            else:
                self._on_sequential_fetch_done(keyword)
            self._schedule_tab_hydration(50)

    def on_fetch_error(
        self: MainApp,
        error_msg: str,
        keyword: str,
        is_sequential: bool = False,
        request_id: Optional[int] = None,
        error_meta: Optional[Dict[str, Any]] = None,
    ):
        """Handle a failed fetch."""
        if not self._is_active_worker_request(keyword, request_id):
            logger.info("stale on_fetch_error ignored: kw=%s, rid=%s", keyword, request_id)
            return

        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            search_keyword = keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)
        self._last_fetch_request_ts.pop(fetch_key, None)
        if request_id is not None:
            self._request_start_index.pop(request_id, None)

        normalized_error_meta: Dict[str, Any] = dict(error_meta or {})
        cooldown_seconds = max(0, int(normalized_error_meta.get("cooldown_seconds", 0) or 0))
        if cooldown_seconds > 0:
            self._set_fetch_cooldown(
                cooldown_seconds,
                reason=str(normalized_error_meta.get("kind", "") or "rate_limit"),
            )

        if self._find_news_tab(keyword) is not None:
            self.sync_tab_load_more_state(keyword)

        if not is_sequential:
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self.btn_refresh.setEnabled(True)

            error_kind = str(normalized_error_meta.get("kind", "") or "").strip()
            if error_kind in {"db_query_error", "db_write_error", "db_error"}:
                dialog_title = "데이터베이스 오류"
                detail_hint = "로컬 데이터베이스 처리 중 오류가 발생했습니다.\n\n프로그램을 다시 시도하거나 로그를 확인해주세요."
            elif error_kind in {"network_error", "timeout"}:
                dialog_title = "네트워크 오류"
                detail_hint = "네트워크 연결 상태를 확인한 뒤 다시 시도해주세요."
            else:
                dialog_title = "API 오류"
                detail_hint = "API 키와 네트워크 연결 상태를 확인해주세요."

            self._status_bar().showMessage(f"❌ '{keyword}' 오류: {error_msg}", 5000)
            QMessageBox.critical(
                self,
                dialog_title,
                f"'{keyword}' 처리 중 오류가 발생했습니다:\n\n{error_msg}\n\n{detail_hint}",
            )
        else:
            logger.warning("Sequential refresh failed for '%s': %s", keyword, error_msg)
            self._on_sequential_fetch_done(keyword)

        error_kind = str(normalized_error_meta.get("kind", "") or "").strip()
        if error_kind:
            is_network_error = error_kind in {"network_error", "timeout"}
        else:
            network_error_keywords = ["네트워크", "timeout", "연결", "connection", "Timeout", "Network"]
            is_network_error = any(token in error_msg for token in network_error_keywords)
        if is_network_error:
            self._network_error_count += 1
            logger.warning(
                "Network error count: %s/%s",
                self._network_error_count,
                self._max_network_errors,
            )
        else:
            self._network_error_count = 0
        self._schedule_tab_hydration(50)

    def cleanup_worker(
        self: MainApp,
        keyword: Optional[str] = None,
        request_id: Optional[int] = None,
        only_if_active: bool = False,
        wait_ms: int = 1000,
    ) -> bool:
        """Dispose a worker/thread pair by request id."""
        try:
            if request_id is None and keyword:
                request_id = self._worker_registry.get_active_request_id(keyword)
            if request_id is None:
                return True

            handle = self._worker_registry.get_by_request_id(request_id)
            if not handle:
                return True

            if only_if_active and keyword and not self._worker_registry.is_active(keyword, request_id):
                return True

            worker = handle.worker
            thread = handle.thread

            try:
                worker.finished.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.error.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.progress.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass

            try:
                worker.stop()
            except (AttributeError, RuntimeError):
                pass

            finished = True
            try:
                if thread.isRunning():
                    thread.quit()
                    if QThread.currentThread() is thread:
                        finished = False
                    else:
                        finished = thread.wait(max(0, int(wait_ms)))
            except (AttributeError, RuntimeError):
                pass

            if not finished:
                logger.warning("Worker cleanup timed out: %s (rid=%s)", handle.tab_keyword, request_id)
                retain_qthread_until_finished(thread, worker)
                return False

            self._worker_registry.pop_by_request_id(request_id)
            self.workers.pop(handle.tab_keyword, None)
            self._request_start_index.pop(request_id, None)
            try:
                worker.deleteLater()
            except (AttributeError, RuntimeError):
                pass
            try:
                thread.deleteLater()
            except (AttributeError, RuntimeError):
                pass
            logger.info("Worker cleaned up: %s (rid=%s)", handle.tab_keyword, request_id)
            self._schedule_tab_hydration(25)
            return finished
        except Exception as e:
            logger.error("cleanup_worker failed (keyword=%s, rid=%s): %s", keyword, request_id, e)
            return False
