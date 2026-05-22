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


class _NewsTabDateFilterControlsMixin:
    def _toggle_date_filter(self, checked: bool):
        """날짜 필터 표시/숨김 토글"""
        self.date_container.setVisible(checked)
        if checked:
            self.date_container.adjustSize()
            self.date_container.updateGeometry()
            self.date_container.repaint()
            self._refresh_date_filter_controls()
            return

        was_active = self._date_filter_active
        self._date_filter_active = False
        self._refresh_date_filter_controls()
        if was_active:
            if self._should_block_db_action("date filter clear"):
                return
            self.load_data_from_db()
        else:
            self.update_status_label()

    def _update_date_toggle_style(self, checked: bool):
        """날짜 토글 버튼 스타일 업데이트"""
        is_dark = self.theme == 1

        if is_dark:
            btn_active_bg = Colors.DARK_PRIMARY_LIGHT
            btn_active_border = Colors.DARK_PRIMARY
            btn_active_text = Colors.DARK_TEXT
            btn_inactive_border = Colors.DARK_BORDER
            btn_inactive_text = Colors.DARK_TEXT_MUTED
            date_bg = "#334155" if checked else "#1E293B"
            date_text = Colors.DARK_TEXT
            date_border = Colors.DARK_PRIMARY if checked else Colors.DARK_BORDER
            tilde_text = Colors.DARK_TEXT_MUTED
        else:
            btn_active_bg = Colors.LIGHT_PRIMARY_LIGHT
            btn_active_border = Colors.LIGHT_PRIMARY
            btn_active_text = "#4338ca"
            btn_inactive_border = Colors.LIGHT_BORDER
            btn_inactive_text = Colors.LIGHT_TEXT_MUTED
            date_bg = "#EEF2FF" if checked else "#FFFFFF"
            date_text = Colors.LIGHT_TEXT
            date_border = Colors.LIGHT_PRIMARY if checked else Colors.LIGHT_BORDER
            tilde_text = Colors.LIGHT_TEXT_MUTED

        if checked:
            btn_style = (
                f"background: {btn_active_bg}; border: 1px solid {btn_active_border}; "
                f"border-radius: 4px; padding: 4px; color: {btn_active_text};"
            )
        else:
            btn_style = (
                f"background: transparent; border: 1px solid {btn_inactive_border}; "
                f"border-radius: 4px; padding: 4px; color: {btn_inactive_text};"
            )
        self.btn_date_toggle.setStyleSheet(btn_style)

        date_edit_style = (
            "QDateEdit {"
            f"background-color: {date_bg};"
            f"color: {date_text};"
            f"border: 1px solid {date_border};"
            "border-radius: 4px;"
            "padding: 2px 6px;"
            "}"
            "QDateEdit:focus {"
            f"border: 1px solid {date_border};"
            "}"
        )
        if hasattr(self, "date_start") and hasattr(self, "date_end") and hasattr(self, "lbl_tilde"):
            self.date_start.setStyleSheet(date_edit_style)
            self.date_end.setStyleSheet(date_edit_style)
            self.lbl_tilde.setStyleSheet(f"color: {tilde_text};")

    def _refresh_date_filter_controls(self):
        active = bool(self._date_filter_active)
        self.btn_date_toggle.setText("📅 기간 적용 중" if active else "📅 기간")
        interactive = self.btn_date_toggle.isChecked() and not self._maintenance_mode_active
        self.btn_apply_date.setEnabled(interactive)
        self.btn_clear_date.setEnabled(active and not self._maintenance_mode_active)
        self.date_start.setEnabled(interactive)
        self.date_end.setEnabled(interactive)
        self._update_date_toggle_style(active)

    def _set_date_edit_value(self, widget: QDateEdit, date_value: QDate):
        widget.blockSignals(True)
        try:
            widget.setDate(date_value)
        finally:
            widget.blockSignals(False)

    def _normalize_date_inputs(self):
        start_date = self.date_start.date()
        end_date = self.date_end.date()
        if start_date > end_date:
            self._set_date_edit_value(self.date_end, start_date)
        return self.date_start.date(), self.date_end.date()

    def _on_date_start_changed(self, selected_date: QDate):
        if selected_date > self.date_end.date():
            self._set_date_edit_value(self.date_end, selected_date)
        if self._date_filter_active:
            self._request_db_reload("날짜 필터 변경")

    def _on_date_end_changed(self, selected_date: QDate):
        if selected_date < self.date_start.date():
            self._set_date_edit_value(self.date_start, selected_date)
        if self._date_filter_active:
            self._request_db_reload("날짜 필터 변경")

    def _apply_date_filter(self):
        self._normalize_date_inputs()
        self._date_filter_active = True
        self._refresh_date_filter_controls()
        self._request_db_reload("날짜 필터 적용")

    def _clear_date_filter(self):
        if not self._date_filter_active:
            self.update_status_label()
            return
        self._date_filter_active = False
        self._refresh_date_filter_controls()
        self._request_db_reload("날짜 필터 해제")
