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

    def _has_advanced_filters(self) -> bool:
        """접을 수 있는 고급 영역(선호 출처·태그·기간)에 조건이 걸려 있는지."""
        return bool(
            self._only_preferred_publishers_enabled()
            or self._current_tag_filter()
            or getattr(self, "_date_filter_active", False)
        )

    def _update_filter_indicator(self):
        """필터 활성 상태를 토글 라벨과 초기화 버튼에 반영한다."""
        btn_advanced = getattr(self, "btn_advanced", None)
        if btn_advanced is not None:
            btn_advanced.setText(self._advanced_button_text(btn_advanced.isChecked()))
        btn_reset = getattr(self, "btn_reset_filters", None)
        if btn_reset is not None:
            btn_reset.setVisible(self._has_active_filters())

    def _reset_filters(self):
        """이 탭의 모든 필터를 해제하고 한 번만 다시 조회한다."""
        if self._should_block_db_action("필터 초기화"):
            return
        self.filter_timer.stop()
        with QSignalBlocker(self.inp_filter):
            self.inp_filter.clear()
        for checkbox in (self.chk_unread, self.chk_hide_dup, self.chk_preferred_publishers):
            with QSignalBlocker(checkbox):
                checkbox.setChecked(False)
        with QSignalBlocker(self.combo_tag_filter):
            self.combo_tag_filter.setCurrentIndex(0)
        with QSignalBlocker(self.btn_date_toggle):
            self.btn_date_toggle.setChecked(False)
        self.date_container.setVisible(False)
        self._date_filter_active = False
        self._refresh_date_filter_controls()
        # apply_filter가 텍스트 필터 강조 해제와 재조회를 함께 처리한다.
        self.apply_filter()
