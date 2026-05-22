# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false
from __future__ import annotations

import logging
import re
import traceback
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QApplication,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.constants import APP_NAME, VERSION
from core.content_filters import normalize_publisher_filter_lists
from core.notifications import NotificationSound
from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query, parse_tab_query
from core.text_utils import perf_timer
from ui.dialogs import BackupDialog, KeywordGroupDialog, LogViewerDialog
from ui.news_tab import NewsTab
from ui.styles import AppStyle, ToastType

logger = logging.getLogger(__name__)


class _MainWindowThemeShellMixin:
    def _effective_theme_idx(self) -> int:
        try:
            configured = int(getattr(self, "theme_idx", 0) or 0)
        except Exception:
            configured = 0
        if configured != 2:
            return 1 if configured == 1 else 0
        try:
            app = QApplication.instance()
            if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
                return 1
        except Exception:
            pass
        return 0

    def _active_app_stylesheet(self) -> str:
        return AppStyle.DARK if self._effective_theme_idx() == 1 else AppStyle.LIGHT

    def _refresh_system_theme(self) -> None:
        if int(getattr(self, "theme_idx", 0) or 0) != 2:
            return
        self.setStyleSheet(self._active_app_stylesheet())
        effective_theme = self._effective_theme_idx()
        for _index, widget in self._iter_news_tabs():
            widget.theme = effective_theme
            widget.render_html()

    def _connect_system_theme_change(self) -> None:
        try:
            app = QApplication.instance()
            if app is None:
                return
            app.styleHints().colorSchemeChanged.connect(lambda _scheme: self._refresh_system_theme())
        except Exception:
            logger.debug("시스템 테마 변경 신호 연결을 건너뜁니다.", exc_info=True)
