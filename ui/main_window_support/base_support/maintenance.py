# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterator, List, Optional

from PyQt6.QtCore import QMutexLocker, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QStatusBar, QStyle, QTabBar, QWidget

from core.database import DatabaseManager
from core.http_client import HttpClientConfig
from core.workers import IterativeJobWorker
from ui.news_tab import NewsTab
from ui.toast import ToastQueue

logger = logging.getLogger(__name__)

from ui.main_window_support.base_support.state import TabFetchState


class _MainWindowMaintenanceMixin:
    def is_maintenance_mode_active(self) -> bool:
        return bool(getattr(self, "_maintenance_mode", False))

    def _maintenance_block_message(self, action: str) -> str:
        reason = str(getattr(self, "_maintenance_reason", "") or "데이터 정리")
        return f"유지보수 중이라 {action}을(를) 실행할 수 없습니다. ({reason})"

    def should_block_db_action(self, action: str, *, notify: bool = True) -> bool:
        if not self.is_maintenance_mode_active():
            return False
        message = self._maintenance_block_message(action)
        self._status_bar().showMessage(message, 3000)
        if notify:
            self.show_warning_toast(message)
        return True

    def _set_countdown_status_text(self, text: str) -> None:
        label = getattr(self, "countdown_status_label", None)
        if label is None:
            return
        label.setText(str(text or ""))

    def _set_fetch_controls_enabled(self, enabled: bool) -> None:
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(enabled)
        if hasattr(self, "btn_add"):
            self.btn_add.setEnabled(enabled)
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(enabled)
        if hasattr(self, "btn_stats"):
            self.btn_stats.setEnabled(enabled)
        if hasattr(self, "action_stats"):
            self.action_stats.setEnabled(enabled)

        for _index, tab in self._iter_news_tabs():
            set_maintenance_mode = getattr(tab, "set_maintenance_mode", None)
            if callable(set_maintenance_mode):
                set_maintenance_mode(not enabled)
            if tab.is_bookmark_tab:
                continue
            if enabled:
                self.sync_tab_load_more_state(tab.keyword)
            else:
                tab.btn_load.setEnabled(False)
                tab.btn_load.setText("🔒 유지보수 중")

    def _apply_maintenance_ui_state(self) -> None:
        active = self.is_maintenance_mode_active()
        self._set_fetch_controls_enabled(not active)
        if active:
            self._status_bar().showMessage(
                f"🔧 유지보수 중: {self._maintenance_reason or '데이터 정리'}",
            )
        else:
            update_tray_tooltip = getattr(self, "update_tray_tooltip", None)
            if callable(update_tray_tooltip):
                update_tray_tooltip()
                QTimer.singleShot(300, update_tray_tooltip)

    def _cancel_active_fetch_workers(self, wait_ms: int = 1500) -> tuple[bool, List[str]]:
        deadline = time.monotonic() + (max(0, int(wait_ms)) / 1000.0)
        unfinished_keywords: List[str] = []

        if self._sequential_refresh_active:
            self._sequential_refresh_active = False
            self._pending_refresh_keywords = []
            self._current_refresh_idx = 0
            self._total_refresh_count = 0
            self.progress.setVisible(False)

        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False

        handles = self._worker_registry.all_handles()
        for handle in handles:
            remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
            finished = self.cleanup_worker(
                keyword=handle.tab_keyword,
                request_id=handle.request_id,
                only_if_active=False,
                wait_ms=remaining_ms,
            )
            if not finished:
                finished = self.cleanup_worker(
                    keyword=handle.tab_keyword,
                    request_id=handle.request_id,
                    only_if_active=False,
                    wait_ms=0,
                    force=True,
                )
            if not finished:
                unfinished_keywords.append(handle.tab_keyword)

        export_worker = getattr(self, "_export_worker", None)
        if export_worker is not None and export_worker.isRunning():
            try:
                self._export_cancel_requested = True
                export_worker.requestInterruption()
                remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
                if not export_worker.wait(remaining_ms):
                    unfinished_keywords.append("CSV export")
                else:
                    self._reset_export_ui()
            except Exception as exc:
                logger.warning("Failed to stop export worker before maintenance: %s", exc)
                unfinished_keywords.append("CSV export")

        for _index, tab in self._iter_news_tabs():
            cancel_background_tasks = getattr(tab, "cancel_background_tasks_for_maintenance", None)
            if not callable(cancel_background_tasks):
                continue
            try:
                remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
                if not cancel_background_tasks(remaining_ms):
                    unfinished_keywords.append(tab.keyword)
            except Exception as exc:
                logger.warning("Failed to stop tab background tasks before maintenance (%s): %s", tab.keyword, exc)
                unfinished_keywords.append(tab.keyword)

        self._hydration_inflight_keyword = ""
        return len(unfinished_keywords) == 0, unfinished_keywords

    def begin_database_maintenance(self, operation: str) -> tuple[bool, str]:
        if self.is_maintenance_mode_active():
            return False, "이미 다른 유지보수 작업이 진행 중입니다."

        ok, unfinished_keywords = self._cancel_active_fetch_workers(wait_ms=1500)
        if not ok:
            keywords_txt = ", ".join(unfinished_keywords)
            logger.warning("Database maintenance blocked by active fetch workers: %s", keywords_txt)
            return (
                False,
                f"활성 새로고침을 1.5초 안에 정리하지 못했습니다: {keywords_txt}",
            )

        operation_label = {
            "delete_old_news": "오래된 기사 정리",
            "delete_all_news": "전체 기사 정리",
            "mark_all_read": "읽음 상태 일괄 반영",
            "optimize_database": "DB 최적화",
            "csv_import": "CSV 가져오기",
            "tag_scope_update": "현재 탭 전체 태그 적용",
            "automation_rules": "자동화 규칙 적용",
        }.get(str(operation or "").strip(), "데이터 정리")
        if str(operation or "").strip() == "cloud_sync":
            operation_label = "클라우드 동기화"
        self._maintenance_mode = True
        self._maintenance_reason = operation_label
        self._pause_fts_backfill(retry_delay_ms=1000)
        self._apply_maintenance_ui_state()
        update_tray_tooltip = getattr(self, "update_tray_tooltip", None)
        if callable(update_tray_tooltip):
            update_tray_tooltip()
        self.show_warning_toast(f"{operation_label}를 위해 유지보수 모드로 전환했습니다.")
        return True, ""

    def end_database_maintenance(self) -> None:
        if not self.is_maintenance_mode_active():
            return
        self._maintenance_mode = False
        self._maintenance_reason = ""
        self._apply_maintenance_ui_state()
        self._status_bar().showMessage("✅ 유지보수 모드가 해제되었습니다.", 3000)
        self.show_toast("유지보수 모드가 해제되었습니다.")
        self._request_fts_backfill_resume(delay_ms=250)
        self._schedule_tab_hydration(50)

    def _update_countdown(self):
        """상태바 카운트다운 업데이트"""
        if self.is_maintenance_mode_active():
            self._set_countdown_status_text("DB 유지보수 중")
            return
        if self._sequential_refresh_active:
            self._set_countdown_status_text("새로고침 진행 중")
            return
        if not bool(getattr(self, "_network_available", True)):
            self._set_countdown_status_text("네트워크 오류로 일시 중지")
            return

        if self._next_refresh_seconds > 0:
            self._next_refresh_seconds -= 1
            minutes = self._next_refresh_seconds // 60
            seconds = self._next_refresh_seconds % 60

            if minutes > 0:
                countdown_text = f"⏰ 다음 새로고침: {minutes}분 {seconds}초 후"
            else:
                countdown_text = f"⏰ 다음 새로고침: {seconds}초 후"
            self._set_countdown_status_text(countdown_text)
        else:
            self._set_countdown_status_text("자동 새로고침 끔")
            self._countdown_timer.stop()
