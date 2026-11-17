# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
)

from ui.styles import AppStyle

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
            if (
                app is not None
                and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
            ):
                return 1
        except Exception:
            pass
        return 0

    def _active_app_stylesheet(self) -> str:
        return AppStyle.for_theme(self._effective_theme_idx() == 1)

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
            app.styleHints().colorSchemeChanged.connect(
                lambda _scheme: self._refresh_system_theme()
            )
        except Exception:
            logger.debug("시스템 테마 변경 신호 연결을 건너뜁니다.", exc_info=True)
