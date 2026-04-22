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


@dataclass
class TabFetchState:
    last_api_start_index: int = 0


class _MainWindowBaseMixin:
    def _iterative_job_worker_cls(self):
        try:
            import ui.main_window as main_window_module

            return getattr(main_window_module, "IterativeJobWorker", IterativeJobWorker)
        except Exception:
            return IterativeJobWorker

    def _status_bar(self) -> QStatusBar:
        status_bar = self.statusBar()
        if status_bar is None:
            raise RuntimeError("Status bar is unavailable")
        return status_bar

    def _tab_bar(self) -> QTabBar:
        tab_bar = self.tabs.tabBar()
        if tab_bar is None:
            raise RuntimeError("Tab bar is unavailable")
        return tab_bar

    def _style(self) -> QStyle:
        style = self.style()
        if style is None:
            raise RuntimeError("Widget style is unavailable")
        return style

    def _app_instance(self) -> QApplication:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplication instance is unavailable")
        return app

    def _require_db(self) -> DatabaseManager:
        if self.db is None:
            raise RuntimeError("Database manager is unavailable")
        return self.db

    def _require_http_client_config(self) -> HttpClientConfig:
        if self.http_client_config is None:
            raise RuntimeError("HTTP client config is unavailable")
        return self.http_client_config

    def create_http_session(self):
        return self._require_http_client_config().create_session()

    def _start_fts_backfill(self) -> None:
        if self._shutdown_in_progress:
            return
        worker = getattr(self, "_fts_backfill_worker", None)
        if worker is not None and worker.isRunning():
            return
        if self._require_db().is_news_fts_backfill_complete():
            self._fts_backfill_retry_attempt = 0
            self._fts_backfill_pause_requested = False
            if self._fts_backfill_retry_timer.isActive():
                self._fts_backfill_retry_timer.stop()
            return
        if self._is_fts_backfill_paused():
            self._schedule_fts_backfill_retry(max(1000, int(self._fts_backfill_pause_delay_ms or 1000)))
            return
        if self._fts_backfill_retry_timer.isActive():
            self._fts_backfill_retry_timer.stop()

        def _job(context):
            total_processed = 0
            while True:
                context.check_cancelled()
                result = self._require_db().backfill_news_fts_chunk(limit=250)
                processed = int(result.get("processed", 0) or 0)
                total_processed += processed
                context.report(current=total_processed, total=0, message="FTS backfill running")
                if bool(result.get("done", False)) or processed <= 0:
                    return {"processed": total_processed, "done": True}

        worker_cls = _MainWindowBaseMixin._iterative_job_worker_cls(self)
        self._fts_backfill_worker = worker_cls(_job, parent=self)
        self._fts_backfill_worker.finished.connect(self._on_fts_backfill_finished)
        self._fts_backfill_worker.error.connect(self._on_fts_backfill_error)
        self._fts_backfill_worker.cancelled.connect(self._on_fts_backfill_cancelled)
        self._fts_backfill_worker.start()

    def _on_fts_backfill_finished(self, _result) -> None:
        self._fts_backfill_worker = None
        self._fts_backfill_retry_attempt = 0
        self._fts_backfill_pause_requested = False
        if self._fts_backfill_retry_timer.isActive():
            self._fts_backfill_retry_timer.stop()

    def _on_fts_backfill_error(self, error_msg: str) -> None:
        logger.warning("FTS backfill failed: %s", error_msg)
        self._fts_backfill_worker = None
        self._fts_backfill_pause_requested = False
        self._fts_backfill_retry_attempt += 1
        self._schedule_fts_backfill_retry(self._next_fts_backfill_retry_delay_ms(), force=True)

    def _on_fts_backfill_cancelled(self) -> None:
        self._fts_backfill_worker = None
        if self._shutdown_in_progress:
            self._fts_backfill_pause_requested = False
            return
        if self._fts_backfill_pause_requested:
            delay_ms = max(0, int(self._fts_backfill_pause_delay_ms or 0))
            self._fts_backfill_pause_requested = False
            self._request_fts_backfill_resume(delay_ms=max(250, delay_ms))

    def _is_fts_backfill_paused(self) -> bool:
        if self._shutdown_in_progress:
            return True
        if self.is_maintenance_mode_active():
            return True
        if self._refresh_in_progress or self._sequential_refresh_active:
            return True
        return False

    def _next_fts_backfill_retry_delay_ms(self) -> int:
        attempt = max(1, int(getattr(self, "_fts_backfill_retry_attempt", 0) or 0))
        if attempt <= 1:
            return 5000
        if attempt == 2:
            return 15000
        return 30000

    def _schedule_fts_backfill_retry(self, delay_ms: int, *, force: bool = False) -> None:
        if self._shutdown_in_progress:
            return
        if self._require_db().is_news_fts_backfill_complete():
            return
        timer = getattr(self, "_fts_backfill_retry_timer", None)
        if timer is None:
            return
        safe_delay = max(0, int(delay_ms))
        if timer.isActive():
            remaining = timer.remainingTime()
            if not force and 0 <= remaining <= safe_delay:
                return
            timer.stop()
        timer.start(safe_delay)

    def _request_fts_backfill_resume(self, *, delay_ms: int = 250) -> None:
        if self._shutdown_in_progress:
            return
        if self._require_db().is_news_fts_backfill_complete():
            return
        if self._is_fts_backfill_paused():
            self._schedule_fts_backfill_retry(max(1000, int(delay_ms)))
            return
        self._schedule_fts_backfill_retry(delay_ms)

    def _pause_fts_backfill(self, *, retry_delay_ms: int = 1000) -> None:
        if self._shutdown_in_progress:
            return
        self._fts_backfill_pause_delay_ms = max(250, int(retry_delay_ms))
        worker = getattr(self, "_fts_backfill_worker", None)
        if worker is None or not worker.isRunning():
            self._request_fts_backfill_resume(delay_ms=self._fts_backfill_pause_delay_ms)
            return
        self._fts_backfill_pause_requested = True
        try:
            worker.requestInterruption()
        except Exception:
            pass

    def _require_toast_queue(self) -> ToastQueue:
        if self.toast_queue is None:
            raise RuntimeError("Toast queue is unavailable")
        return self.toast_queue

    def _news_tab(self, widget: Optional[QWidget]) -> Optional[NewsTab]:
        return widget if isinstance(widget, NewsTab) else None

    def _news_tab_at(self, index: int) -> Optional[NewsTab]:
        return self._news_tab(self.tabs.widget(index))

    def _current_news_tab(self) -> Optional[NewsTab]:
        return self._news_tab(self.tabs.currentWidget())

    def _iter_news_tabs(self, start_index: int = 0) -> Iterator[tuple[int, NewsTab]]:
        for index in range(start_index, self.tabs.count()):
            tab = self._news_tab_at(index)
            if tab is not None:
                yield index, tab

    def _find_news_tab(self, keyword: str) -> Optional[tuple[int, NewsTab]]:
        for index, tab in self._iter_news_tabs(start_index=1):
            if tab.keyword == keyword:
                return index, tab
        return None

    def _connect_news_tab_hydration(self, tab: NewsTab) -> None:
        try:
            tab.hydration_finished.connect(self._on_tab_hydration_finished)
        except Exception:
            pass
        try:
            tab.hydration_failed.connect(self._on_tab_hydration_failed)
        except Exception:
            pass

    def _remove_tab_hydration(self, keyword: str) -> None:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return
        self._tab_hydration_queue = deque(
            queued_keyword
            for queued_keyword in self._tab_hydration_queue
            if queued_keyword != normalized_keyword
        )
        if self._hydration_inflight_keyword == normalized_keyword:
            self._hydration_inflight_keyword = ""

    def _enqueue_tab_hydration(self, keyword: str, *, prioritize: bool = False) -> None:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return
        located_tab = self._find_news_tab(normalized_keyword)
        if located_tab is None:
            return
        _index, tab = located_tab
        if not tab.needs_initial_hydration():
            self._remove_tab_hydration(normalized_keyword)
            return
        self._tab_hydration_queue = deque(
            queued_keyword
            for queued_keyword in self._tab_hydration_queue
            if queued_keyword != normalized_keyword
        )
        if self._hydration_inflight_keyword != normalized_keyword:
            if prioritize:
                self._tab_hydration_queue.appendleft(normalized_keyword)
            else:
                self._tab_hydration_queue.append(normalized_keyword)
        self._schedule_tab_hydration(0 if prioritize else 50)

    def _is_tab_hydration_paused(self) -> bool:
        if self._shutdown_in_progress:
            return True
        if self.is_maintenance_mode_active():
            return True
        if self._refresh_in_progress or self._sequential_refresh_active:
            return True
        try:
            if self._worker_registry.all_handles():
                return True
        except Exception:
            pass
        return False

    def _schedule_tab_hydration(self, delay_ms: int = 0) -> None:
        if self._hydration_inflight_keyword:
            return
        if self._is_tab_hydration_paused():
            return
        if self._hydration_timer.isActive():
            self._hydration_timer.stop()
        self._hydration_timer.start(max(0, int(delay_ms)))

    def _start_tab_hydration(self, tab: NewsTab) -> bool:
        if tab.is_bookmark_tab or not tab.needs_initial_hydration():
            return False
        if tab.is_initial_hydration_inflight():
            self._hydration_inflight_keyword = tab.keyword
            return True
        if tab.request_initial_hydration():
            self._hydration_inflight_keyword = tab.keyword
            return True
        return False

    def _cancel_active_tab_hydration(self, *, requeue: bool = True, wait_ms: int = 250) -> bool:
        active_keyword = str(getattr(self, "_hydration_inflight_keyword", "") or "").strip()
        if not active_keyword:
            return True
        located_tab = self._find_news_tab(active_keyword)
        if located_tab is None:
            self._hydration_inflight_keyword = ""
            return True
        _index, tab = located_tab
        finished = tab.cancel_initial_hydration(wait_ms=wait_ms)
        self._hydration_inflight_keyword = ""
        if requeue and tab.needs_initial_hydration():
            self._enqueue_tab_hydration(tab.keyword, prioritize=False)
        return finished

    def _process_tab_hydration(self) -> None:
        if self._hydration_inflight_keyword or self._is_tab_hydration_paused():
            return

        current_tab = self._current_news_tab()
        if current_tab is not None and not current_tab.is_bookmark_tab and current_tab.needs_initial_hydration():
            self._remove_tab_hydration(current_tab.keyword)
            if self._start_tab_hydration(current_tab):
                return

        while self._tab_hydration_queue:
            next_keyword = self._tab_hydration_queue.popleft()
            located_tab = self._find_news_tab(next_keyword)
            if located_tab is None:
                continue
            _index, tab = located_tab
            if not tab.needs_initial_hydration():
                continue
            if self._start_tab_hydration(tab):
                return

    def _bootstrap_tab_hydration(self) -> None:
        current_tab = self._current_news_tab()
        current_keyword = ""
        if current_tab is not None and not current_tab.is_bookmark_tab:
            current_keyword = current_tab.keyword
        for _index, tab in self._iter_news_tabs(start_index=1):
            if not tab.needs_initial_hydration():
                continue
            if current_keyword and tab.keyword == current_keyword:
                continue
            self._enqueue_tab_hydration(tab.keyword, prioritize=False)
        if current_keyword:
            self._enqueue_tab_hydration(current_keyword, prioritize=True)
        else:
            self._schedule_tab_hydration(0)

    def _on_tab_hydration_finished(self, keyword: str) -> None:
        self._remove_tab_hydration(keyword)
        self._schedule_tab_hydration(25)

    def _on_tab_hydration_failed(self, keyword: str, error_msg: str) -> None:
        logger.warning("Initial tab hydration failed (%s): %s", keyword, error_msg)
        self._remove_tab_hydration(keyword)
        self._schedule_tab_hydration(100)

    def _on_current_tab_changed(self, index: int) -> None:
        current_tab = self._news_tab_at(index)
        if current_tab is None or current_tab.is_bookmark_tab:
            self._schedule_tab_hydration(0)
            return
        if not current_tab.needs_initial_hydration():
            self._schedule_tab_hydration(0)
            return
        active_keyword = str(getattr(self, "_hydration_inflight_keyword", "") or "").strip()
        if active_keyword and active_keyword != current_tab.keyword:
            self._cancel_active_tab_hydration(requeue=True, wait_ms=200)
        self._enqueue_tab_hydration(current_tab.keyword, prioritize=True)

    def sync_link_state_across_tabs(
        self,
        source_tab: Optional[NewsTab],
        link: str,
        *,
        is_read: Optional[bool] = None,
        is_bookmarked: Optional[bool] = None,
        notes: Optional[str] = None,
        deleted: bool = False,
    ) -> None:
        normalized_link = str(link or "").strip()
        if not normalized_link:
            return

        tabs_to_reload: List[NewsTab] = []
        for _index, tab in self._iter_news_tabs():
            if source_tab is not None and tab is source_tab:
                continue
            changed = tab.apply_external_item_state(
                normalized_link,
                is_read=is_read,
                is_bookmarked=is_bookmarked,
                notes=notes,
                deleted=deleted,
            )
            if changed or deleted:
                continue
            if is_bookmarked is True and tab.is_bookmark_tab and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)
            if is_read is False and tab.chk_unread.isChecked() and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)

        for tab in tabs_to_reload:
            try:
                tab.load_data_from_db()
            except Exception as exc:
                logger.warning("External tab sync reload failed (%s): %s", tab.keyword, exc)

        self._schedule_badge_refresh(delay_ms=0)
        self.update_tray_tooltip()
        QTimer.singleShot(300, self.update_tray_tooltip)

    def _add_menu_action(self, menu: QMenu, text: str) -> QAction:
        action = menu.addAction(text)
        if action is None:
            raise RuntimeError(f"Failed to add menu action: {text}")
        return action

    def _make_tab_fetch_state(self) -> TabFetchState:
        return TabFetchState()

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
        }.get(str(operation or "").strip(), "데이터 정리")
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
        if self._sequential_refresh_active or self.is_maintenance_mode_active():
            self._set_countdown_status_text("")
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
            self._set_countdown_status_text("")
            self._countdown_timer.stop()
