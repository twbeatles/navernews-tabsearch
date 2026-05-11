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

class _MainWindowRefreshFlowMixin:
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
    def _global_refresh_interval_minutes(self: MainApp) -> Optional[int]:
        minutes = [10, 30, 60, 120, 360]
        idx = int(getattr(self, "interval_idx", 5) or 0)
        if 0 <= idx < len(minutes):
            return minutes[idx]
        return None
    def _tab_refresh_interval_minutes(self: MainApp, keyword: str) -> Optional[int]:
        policies = getattr(self, "tab_refresh_policies", {})
        canonical_key = ""
        canonical_for_keyword = getattr(self, "_canonical_fetch_key_for_keyword", None)
        if callable(canonical_for_keyword):
            canonical_key = str(canonical_for_keyword(keyword) or "")
        policy = str(
            policies.get(canonical_key, policies.get(keyword, "inherit"))
            if isinstance(policies, dict)
            else "inherit"
        ).lower()
        if policy == "off":
            return None
        if policy == "inherit":
            return self._global_refresh_interval_minutes()
        try:
            minutes = int(policy)
        except ValueError:
            return self._global_refresh_interval_minutes()
        if minutes in {10, 30, 60, 120, 360}:
            return minutes
        return self._global_refresh_interval_minutes()
    def _auto_refresh_keywords_due(self: MainApp, keywords: List[str]) -> List[str]:
        now_ts = time.time()
        due_keywords: List[str] = []
        last_by_keyword = getattr(self, "_last_auto_refresh_by_keyword", {})
        for keyword in self._prepare_refresh_keywords(keywords):
            interval_minutes = self._tab_refresh_interval_minutes(keyword)
            if interval_minutes is None:
                continue
            last_ts = float(last_by_keyword.get(keyword, 0.0) or 0.0)
            if last_ts <= 0 or now_ts - last_ts >= interval_minutes * 60:
                due_keywords.append(keyword)
        self._last_auto_refresh_by_keyword = last_by_keyword
        return due_keywords
    def _refresh_block_reason(
        self: MainApp,
        action_label: str = "새로고침",
    ) -> str:
        if self.is_maintenance_mode_active():
            return self._maintenance_block_message(action_label)
        if self._sequential_refresh_active:
            return "다른 새로고침이 이미 진행 중입니다. 완료 후 다시 시도해 주세요."
        cooldown_msg = self._fetch_cooldown_message(action_label)
        if cooldown_msg:
            return cooldown_msg
        valid, msg = self._validate_api_credentials()
        if not valid:
            return f"API 인증 정보가 준비되지 않아 {action_label}을(를) 실행할 수 없습니다. {msg}"
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
        *,
        auto_refresh: bool = False,
    ) -> bool:
        prepared_keywords = self._prepare_refresh_keywords(keywords)
        if not prepared_keywords:
            self._status_bar().showMessage("새로고침할 탭이 없습니다.")
            return False

        self._pending_refresh_keywords = prepared_keywords
        self._sequential_refresh_active = True
        self._current_refresh_idx = 0
        self._total_refresh_count = len(prepared_keywords)
        self._sequential_new_count = 0
        self._sequential_added_count = 0
        self._sequential_dup_count = 0
        self._sequential_refresh_is_auto = bool(auto_refresh)
        pause_fts_backfill = getattr(self, "_pause_fts_backfill", None)
        if callable(pause_fts_backfill):
            pause_fts_backfill(retry_delay_ms=1000)

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
                self._set_countdown_status_text("네트워크 오류로 일시 중지")
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
            self._auto_refresh_tick = True
            started = self.refresh_all()
        except Exception as e:
            logger.error("Automatic refresh failed: %s", e)
        finally:
            self._auto_refresh_tick = False
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

            if bool(getattr(self, "_auto_refresh_tick", False)):
                refresh_keywords = self._auto_refresh_keywords_due(refresh_keywords)
                if not refresh_keywords:
                    logger.info("Automatic refresh skipped because no tab is due")
                    return False

            if self._begin_sequential_refresh(
                refresh_keywords,
                auto_refresh=bool(getattr(self, "_auto_refresh_tick", False)),
            ):
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

        if self._begin_sequential_refresh(keywords, auto_refresh=False):
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
    def _build_fetch_summary_message(
        self: MainApp,
        keyword: str,
        *,
        new_count: int,
        dup_count: int,
        filtered_count: int = 0,
    ) -> str:
        msg = f"✅ '{keyword}' 업데이트 완료 ({new_count}건 새 링크"
        if dup_count > 0:
            msg += f", {dup_count}건 중복"
        if filtered_count > 0:
            msg += f", {filtered_count}건 제외"
        msg += ")"
        return msg
    def _notify_fetch_new_items(
        self: MainApp,
        keyword: str,
        *,
        new_count: int,
        new_items: List[Dict[str, Any]],
    ) -> None:
        if new_count <= 0:
            return

        self.show_desktop_notification(
            f"📰 {keyword}",
            f"{new_count}건의 새 뉴스가 있습니다.",
        )
        if not self.isVisible():
            self.show_tray_notification(
                f"📰 {keyword}",
                f"{new_count}건의 새 뉴스가 도착했습니다.",
            )
        self.update_tray_tooltip()

        matched = self.check_alert_keywords(new_items)
        if matched:
            for item, alert_keyword in matched[:3]:
                title = html.unescape(RE_HTML_TAGS.sub("", item.get("title", "")))
                self.show_desktop_notification(
                    f"🔔 알림 키워드: {alert_keyword}",
                    title[:50],
                )
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
        self._sequential_refresh_is_auto = False
        self._last_refresh_time = datetime.now()

        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False

        self.progress.setValue(self._total_refresh_count)
        self.progress.setVisible(False)
        self.btn_refresh.setEnabled(True)

        new_count = self._sequential_new_count
        dup = self._sequential_dup_count

        toast_msg = f"총 {self._total_refresh_count}개 탭 새로고침 완료 ({new_count}건 새 링크"
        if dup > 0:
            toast_msg += f", {dup}건 중복"
        toast_msg += ")"

        logger.info("Sequential refresh finished: %s", toast_msg)
        self._status_bar().showMessage(toast_msg, 5000)
        self.show_toast(toast_msg)

        if self.notify_on_refresh and new_count > 0:
            self.show_desktop_notification(
                "뉴스 자동 새로고침 완료",
                f"{new_count}건의 새 기사가 업데이트되었습니다.",
            )

        self.apply_refresh_interval()
        request_fts_backfill_resume = getattr(self, "_request_fts_backfill_resume", None)
        if callable(request_fts_backfill_resume):
            request_fts_backfill_resume(delay_ms=250)
        self._schedule_tab_hydration(50)
