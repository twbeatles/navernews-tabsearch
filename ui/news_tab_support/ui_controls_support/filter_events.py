# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from PyQt6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.styles import Colors
from ui.widgets import NewsBrowser, NoScrollComboBox


class _NewsTabFilterEventControlsMixin:
    def _on_sort_changed(self):
        self._request_db_reload("정렬 변경")

    def _on_unread_filter_changed(self):
        self._request_db_reload("안 읽음 필터 변경")

    def _on_hide_duplicates_changed(self):
        self._request_db_reload("중복 숨김 변경")

    def _on_preferred_publishers_changed(self):
        self._request_db_reload("선호 출처 필터 변경")

    def _on_tag_filter_changed(self):
        if hasattr(self, "filter_timer"):
            self.filter_timer.start(self.FILTER_DEBOUNCE_MS)

    def _on_filter_changed(self):
        """필터 입력 변경 시 디바운싱 타이머 시작"""
        self.filter_timer.stop()
        self.filter_timer.start(self.FILTER_DEBOUNCE_MS)

    def _apply_filter_debounced(self):
        """디바운싱된 필터 적용"""
        self.apply_filter()
