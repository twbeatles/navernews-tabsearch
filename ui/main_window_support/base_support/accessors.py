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


class _MainWindowBaseAccessorsMixin:
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

    def _add_menu_action(self, menu: QMenu, text: str) -> QAction:
        action = menu.addAction(text)
        if action is None:
            raise RuntimeError(f"Failed to add menu action: {text}")
        return action

    def _make_tab_fetch_state(self) -> TabFetchState:
        return TabFetchState()
