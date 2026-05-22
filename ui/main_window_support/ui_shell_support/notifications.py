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


class _MainWindowNotificationShellMixin:
    def show_desktop_notification(self, title: str, message: str):
        """데스크톱 알림 표시"""
        if not self.notification_enabled:
            return
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            else:
                self.show_toast(f"{title}: {message}")
            if self.sound_enabled:
                NotificationSound.play("success")
        except Exception as exc:
            logger.warning("데스크톱 알림 오류: %s", exc)

    def check_alert_keywords(self, items: list) -> list:
        """알림 키워드 체크 - 해당 키워드 포함된 기사 반환"""
        if not self.alert_keywords:
            return []

        matched = []
        for item in items:
            title = str(item.get("title", "") or "")
            desc = str(item.get("description", "") or "")
            searchable = f"{title}\n{desc}"
            searchable_lower = searchable.lower()
            for kw in self.alert_keywords:
                keyword = str(kw or "").strip()
                if not keyword:
                    continue
                if keyword.lower().startswith("regex:"):
                    pattern = keyword[6:].strip()
                    if not pattern:
                        continue
                    try:
                        if re.search(pattern, searchable, re.IGNORECASE):
                            matched.append((item, kw))
                            break
                    except re.error as exc:
                        logger.warning("Invalid alert regex skipped: %s (%s)", pattern, exc)
                    continue
                if keyword.lower() in searchable_lower:
                    matched.append((item, kw))
                    break
        return matched

    def show_toast(self, message: str, toast_type: ToastType = ToastType.INFO):
        """토스트 메시지 표시 - 유형별 스타일 지원"""
        self._require_toast_queue().add(message, toast_type)

    def show_success_toast(self, message: str):
        """성공 토스트 메시지"""
        self.show_toast(message, ToastType.SUCCESS)

    def show_warning_toast(self, message: str):
        """경고 토스트 메시지"""
        self.show_toast(message, ToastType.WARNING)

    def show_error_toast(self, message: str):
        """오류 토스트 메시지"""
        self.show_toast(message, ToastType.ERROR)
