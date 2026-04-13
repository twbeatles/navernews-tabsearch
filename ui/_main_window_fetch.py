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
from core.worker_registry import WorkerHandle
from core.workers import ApiWorker

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)


class _MainWindowFetchMixin:
    def _current_fetch_cooldown_seconds(self: MainApp) -> int:
        remaining = int(max(0.0, float(getattr(self, "_fetch_cooldown_until", 0.0) or 0.0) - time.time()))
        if remaining <= 0:
            self._fetch_cooldown_until = 0.0
            self._fetch_cooldown_reason = ""
        return remaining

    def _set_fetch_cooldown(
        self: MainApp,
        seconds: int,
        *,
        reason: str,
    ) -> None:
        safe_seconds = max(0, int(seconds))
        if safe_seconds <= 0:
            return
        until = time.time() + safe_seconds
        current_until = float(getattr(self, "_fetch_cooldown_until", 0.0) or 0.0)
        if until > current_until:
            self._fetch_cooldown_until = until
            self._fetch_cooldown_reason = str(reason or "").strip()

    def _fetch_cooldown_message(self: MainApp, action_label: str) -> str:
        remaining = self._current_fetch_cooldown_seconds()
        if remaining <= 0:
            return ""
        reason = str(getattr(self, "_fetch_cooldown_reason", "") or "").strip()
        suffix = f" ({reason})" if reason else ""
        return f"{action_label}은(는) 잠시 후 다시 시도해주세요. API 대기 시간 {remaining}초 남음{suffix}"

    def _prepare_refresh_keywords(
        self: MainApp,
        keywords: List[str],
    ) -> List[str]:
        prepared: List[str] = []
        for keyword in keywords:
            try:
                normalized_keyword = str(keyword or "").strip()
                if not normalized_keyword or not has_positive_keyword(normalized_keyword):
                    continue
                if normalized_keyword not in prepared:
                    prepared.append(normalized_keyword)
            except Exception as e:
                logger.error("Failed to normalize refresh keyword '%s': %s", keyword, e)
        return prepared

    def _refresh_block_reason(
        self: MainApp,
        action_label: str = "새로고침",
    ) -> str:
        if self.is_maintenance_mode_active():
            return self._maintenance_block_message(action_label)
        if self._sequential_refresh_active:
            return "Another refresh is already running. Please try again after it finishes."
        cooldown_msg = self._fetch_cooldown_message(action_label)
        if cooldown_msg:
            return cooldown_msg
        valid, msg = self._validate_api_credentials()
        if not valid:
            return f"API credentials are not ready, so {action_label} cannot run. {msg}"
        return ""

    def _notify_refresh_blocked(
        self: MainApp,
        message: str,
    ) -> None:
        if not message:
            return
        self._status_bar().showMessage(message, 4000)
        self.show_warning_toast(message)

    def _begin_sequential_refresh(
        self: MainApp,
        keywords: List[str],
    ) -> bool:
        prepared_keywords = self._prepare_refresh_keywords(keywords)
        if not prepared_keywords:
            self._status_bar().showMessage("새로고침할 탭이 없습니다.")
            return False

        self._pending_refresh_keywords = prepared_keywords
        self._sequential_refresh_active = True
        self._current_refresh_idx = 0
        self._total_refresh_count = len(prepared_keywords)
        self._sequential_added_count = 0
        self._sequential_dup_count = 0

        self.progress.setVisible(True)
        self.progress.setRange(0, self._total_refresh_count)
        self.progress.setValue(0)
        self._status_bar().showMessage(
            f"새로고침 중... (0/{self._total_refresh_count})"
        )
        self.btn_refresh.setEnabled(False)
        self._process_next_refresh()
        return True

    def _safe_refresh_all(self: MainApp):
        """Timer-safe refresh wrapper."""
        if self.is_maintenance_mode_active():
            logger.info("Automatic refresh skipped during maintenance mode")
            self._status_bar().showMessage(
                self._maintenance_block_message("자동 새로고침"),
                3000,
            )
            return

        if self._network_error_count >= self._max_network_errors:
            if self._network_available:
                logger.warning(
                    "Automatic refresh paused after %s consecutive network errors",
                    self._network_error_count,
                )
                self._network_available = False
                self._status_bar().showMessage(
                    "네트워크 오류로 자동 새로고침을 잠시 중지했습니다. 수동 새로고침으로 다시 확인해주세요."
                )
            return

        with QMutexLocker(self._refresh_mutex):
            if self._refresh_in_progress or self._sequential_refresh_active:
                logger.warning("Refresh skipped because another refresh is already running")
                return
            self._refresh_in_progress = True

        started = False
        try:
            started = self.refresh_all()
        except Exception as e:
            logger.error("Automatic refresh failed: %s", e)
        finally:
            if not started:
                with QMutexLocker(self._refresh_mutex):
                    self._refresh_in_progress = False

    def refresh_all(self: MainApp) -> bool:
        """Refresh all tabs sequentially."""
        logger.info("Starting refresh_all")
        block_reason = self._refresh_block_reason("새로고침")
        if block_reason:
            self._notify_refresh_blocked(block_reason)
            return False

        if self.is_maintenance_mode_active():
            msg = self._maintenance_block_message("새로고침")
            self._status_bar().showMessage(msg, 3000)
            self.show_warning_toast(msg)
            return False

        if self._sequential_refresh_active:
            logger.warning("Sequential refresh is already running")
            return False

        try:
            valid, msg = self._validate_api_credentials()
            if not valid:
                self._status_bar().showMessage(f"⚠ {msg}")
                logger.warning("API credentials invalid: %s", msg)
                return False

            self._network_error_count = 0
            self._network_available = True

            try:
                self.bm_tab.load_data_from_db()
            except Exception as e:
                logger.error("Bookmark tab reload failed: %s", e)

            refresh_keywords: List[str] = []
            for _index, widget in self._iter_news_tabs(start_index=1):
                try:
                    if has_positive_keyword(widget.keyword):
                        refresh_keywords.append(widget.keyword)
                except Exception as e:
                    logger.error("Failed to inspect tab keyword: %s", e)

            if self._begin_sequential_refresh(refresh_keywords):
                return True
            return False
        except Exception as e:
            logger.error("refresh_all failed: %s", e)
            traceback.print_exc()
            self._status_bar().showMessage(f"❌ 새로고침 오류: {e}")
            self._finish_sequential_refresh()
            return False

    def refresh_selected_tabs(self: MainApp, keywords: List[str]) -> bool:
        """Refresh a selected subset of tabs sequentially."""
        logger.info("Starting refresh_selected_tabs: %s", keywords)
        block_reason = self._refresh_block_reason("새로고침")
        if block_reason:
            self._notify_refresh_blocked(block_reason)
            return False

        if self.is_maintenance_mode_active():
            msg = self._maintenance_block_message("새로고침")
            self._status_bar().showMessage(msg, 3000)
            self.show_warning_toast(msg)
            return False

        if self._sequential_refresh_active:
            logger.warning("Sequential refresh is already running")
            return False

        valid, msg = self._validate_api_credentials()
        if not valid:
            self._status_bar().showMessage(f"⚠ {msg}")
            logger.warning("API credentials invalid: %s", msg)
            return False

        self._network_error_count = 0
        self._network_available = True

        if self._begin_sequential_refresh(keywords):
            return True
        return False

    def _process_next_refresh(self: MainApp):
        """Run the next queued tab refresh."""
        if not self._sequential_refresh_active:
            return

        if self._current_refresh_idx >= len(self._pending_refresh_keywords):
            self._finish_sequential_refresh()
            return

        cooldown_seconds = self._current_fetch_cooldown_seconds()
        if cooldown_seconds > 0:
            self._status_bar().showMessage(
                f"API 대기 시간으로 순차 새로고침을 {cooldown_seconds}초 후 재개합니다."
            )
            QTimer.singleShot(cooldown_seconds * 1000, self._process_next_refresh)
            return

        keyword = self._pending_refresh_keywords[self._current_refresh_idx]
        logger.info(
            "Sequential refresh: [%s/%s] %s",
            self._current_refresh_idx + 1,
            self._total_refresh_count,
            keyword,
        )

        self.progress.setValue(self._current_refresh_idx)
        self._status_bar().showMessage(
            f"'{keyword}' 새로고침 중... ({self._current_refresh_idx + 1}/{self._total_refresh_count})"
        )

        try:
            self.fetch_news(keyword, is_sequential=True)
        except Exception as e:
            logger.error("Refresh failed for '%s': %s", keyword, e)
            self._current_refresh_idx += 1
            QTimer.singleShot(500, self._process_next_refresh)

    def _on_sequential_fetch_done(self: MainApp, keyword: str):
        """Advance the sequential refresh chain."""
        if not self._sequential_refresh_active:
            return

        self._current_refresh_idx += 1
        QTimer.singleShot(300, self._process_next_refresh)

    def _finish_sequential_refresh(self: MainApp):
        """Reset sequential refresh state and surface the result."""
        self._sequential_refresh_active = False
        self._pending_refresh_keywords = []
        self._last_refresh_time = datetime.now()

        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False

        self.progress.setValue(self._total_refresh_count)
        self.progress.setVisible(False)
        self.btn_refresh.setEnabled(True)

        added = self._sequential_added_count
        dup = self._sequential_dup_count

        toast_msg = f"총 {self._total_refresh_count}개 탭 새로고침 완료 ({added}건 추가"
        if dup > 0:
            toast_msg += f", {dup}건 중복"
        toast_msg += ")"

        logger.info("Sequential refresh finished: %s", toast_msg)
        self._status_bar().showMessage(toast_msg, 5000)
        self.show_toast(toast_msg)

        if self.notify_on_refresh and added > 0:
            self.show_desktop_notification(
                "뉴스 자동 새로고침 완료",
                f"{added}건의 새 기사가 업데이트되었습니다.",
            )

        self.apply_refresh_interval()

    def _next_worker_request_id(self: MainApp) -> int:
        self._worker_request_seq += 1
        return self._worker_request_seq

    def _is_active_worker_request(
        self: MainApp,
        keyword: str,
        request_id: Optional[int],
    ) -> bool:
        if request_id is None:
            return True
        return self._worker_registry.is_active(keyword, request_id)

    def _compute_load_more_state(
        self: MainApp,
        total: Optional[int],
        last_api_start_index: int,
    ) -> bool:
        last_api_start_index = max(0, int(last_api_start_index or 0))
        next_start = last_api_start_index + 100
        if next_start > 1000:
            return False
        if total is None:
            return True
        return next_start <= min(1000, max(0, int(total or 0)))

    def _apply_load_more_button_state(
        self: MainApp,
        tab_widget,
        total: Optional[int],
        last_api_start_index: int,
    ) -> bool:
        is_maintenance_active = getattr(self, "is_maintenance_mode_active", lambda: False)
        if is_maintenance_active():
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("🔒 유지보수 중")
            return False

        has_more = self._compute_load_more_state(total, last_api_start_index)
        if has_more:
            tab_widget.btn_load.setEnabled(True)
            tab_widget.btn_load.setText("📄 더 불러오기")
        else:
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("📄 마지막 페이지")
        return has_more

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
            self.cleanup_worker(keyword=keyword, request_id=old_handle.request_id, only_if_active=True)

        located_tab = self._find_news_tab(keyword)
        if located_tab is not None:
            _tab_index, tab_widget = located_tab
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("📄 로딩 중...")

        worker = ApiWorker(
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

            added_count = int(result.get("added_count", 0) or 0)
            dup_count = int(result.get("dup_count", 0) or 0)
            total = int(result.get("total", 0) or 0)

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

                if not is_more and not is_sequential:
                    msg = f"✅ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        msg += f", {dup_count}건 중복"
                    filtered_count = int(result.get("filtered", 0) or 0)
                    if filtered_count > 0:
                        msg += f", {filtered_count}건 제외"
                    msg += ")"
                    tab_widget.lbl_status.setText(msg)

            if not is_sequential:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)

                if not is_more:
                    toast_msg = f"✅ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        toast_msg += f", {dup_count}건 유사"
                    toast_msg += ")"
                    self.show_toast(toast_msg)
                    self._status_bar().showMessage(toast_msg, 3000)

                    if added_count > 0:
                        self.show_desktop_notification(
                            f"📰 {keyword}",
                            f"{added_count}건의 새 뉴스가 있습니다.",
                        )
                        if not self.isVisible():
                            self.show_tray_notification(
                                f"📰 {keyword}",
                                f"{added_count}건의 새 뉴스가 도착했습니다.",
                            )
                        self.update_tray_tooltip()

                    matched = self.check_alert_keywords(result.get("new_items", [])) if added_count > 0 else []
                    if matched:
                        for item, alert_keyword in matched[:3]:
                            title = html.unescape(RE_HTML_TAGS.sub("", item.get("title", "")))
                            self.show_desktop_notification(
                                f"🔔 알림 키워드: {alert_keyword}",
                                title[:50],
                            )
            else:
                self._sequential_added_count += added_count
                self._sequential_dup_count += dup_count
                self._on_sequential_fetch_done(keyword)

            self._network_error_count = 0
            self._network_available = True
            self.update_tab_badge(keyword)
        except Exception as e:
            logger.error("on_fetch_done failed: %s", e)
            traceback.print_exc()
            self._status_bar().showMessage(f"❌ 처리 중 오류: {e}")
            if not is_sequential:
                self.progress.setVisible(False)
                self.btn_refresh.setEnabled(True)
            else:
                self._on_sequential_fetch_done(keyword)

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
                thread.quit()
                finished = thread.wait(max(0, int(wait_ms)))
            except (AttributeError, RuntimeError):
                pass

            if not finished:
                logger.warning("Worker cleanup timed out: %s (rid=%s)", handle.tab_keyword, request_id)
                return False

            self._worker_registry.pop_by_request_id(request_id)
            self.workers.pop(handle.tab_keyword, None)
            self._request_start_index.pop(request_id, None)
            logger.info("Worker cleaned up: %s (rid=%s)", handle.tab_keyword, request_id)
            return finished
        except Exception as e:
            logger.error("cleanup_worker failed (keyword=%s, rid=%s): %s", keyword, request_id, e)
            return False

    def _validate_api_credentials(self: MainApp):
        from core.validation import ValidationUtils

        return ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
