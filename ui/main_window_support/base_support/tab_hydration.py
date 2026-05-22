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


class _MainWindowTabHydrationMixin:
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
        tags: Optional[str] = None,
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
                tags=tags,
                deleted=deleted,
            )
            if changed or deleted:
                continue
            if is_bookmarked is True and tab.is_bookmark_tab and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)
            if is_read is False and tab.chk_unread.isChecked() and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)
            current_tag_filter = getattr(tab, "_current_tag_filter", lambda: "")()
            if tags is not None and str(current_tag_filter or "").strip() and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)
            if tags is not None:
                refresh_tags = getattr(tab, "_refresh_tag_filter_options", None)
                if callable(refresh_tags):
                    refresh_tags()

        for tab in tabs_to_reload:
            try:
                tab.load_data_from_db()
            except Exception as exc:
                logger.warning("External tab sync reload failed (%s): %s", tab.keyword, exc)

        self._schedule_badge_refresh(delay_ms=0)
        self.update_tray_tooltip()
        QTimer.singleShot(300, self.update_tray_tooltip)
