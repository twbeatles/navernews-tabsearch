# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from PyQt6.QtCore import QDate, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.styles import Colors
from ui.widgets import NewsBrowser, NoScrollComboBox


class _NewsTabUIControlsMixin:
    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        filter_card = QFrame()
        filter_card.setObjectName("FilterCard")
        is_dark = self.theme == 1
        filter_card.setStyleSheet(
            f"""
            QFrame#FilterCard {{
                background-color: {Colors.DARK_CARD_BG if is_dark else Colors.LIGHT_CARD_BG};
                border: 1px solid {Colors.DARK_BORDER if is_dark else Colors.LIGHT_BORDER};
                border-radius: 10px;
                padding: 8px;
            }}
        """
        )

        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(8)

        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)

        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self._apply_filter_debounced)
        self.inp_filter.textChanged.connect(self._on_filter_changed)

        self.combo_sort = NoScrollComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)

        row1_layout.addWidget(self.inp_filter, 4)
        row1_layout.addWidget(self.combo_sort, 1)
        filter_layout.addLayout(row1_layout)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(12)

        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self._on_unread_filter_changed)

        self.chk_hide_dup = QCheckBox("중복 숨김")
        self.chk_hide_dup.stateChanged.connect(self._on_hide_duplicates_changed)

        row2_layout.addWidget(self.chk_unread)
        row2_layout.addWidget(self.chk_hide_dup)

        self.btn_date_toggle = QToolButton()
        self.btn_date_toggle.setText("📅 기간")
        self.btn_date_toggle.setCheckable(True)
        self.btn_date_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_date_toggle.toggled.connect(self._toggle_date_filter)

        self.date_container = QWidget()
        date_inner_layout = QHBoxLayout(self.date_container)
        date_inner_layout.setContentsMargins(0, 0, 0, 0)
        date_inner_layout.setSpacing(4)

        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setMinimumWidth(120)
        self.date_start.setDate(QDate.currentDate().addDays(-7))
        self.date_start.dateChanged.connect(self._on_date_start_changed)

        self.lbl_tilde = QLabel("~")

        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setMinimumWidth(120)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.dateChanged.connect(self._on_date_end_changed)

        self.btn_apply_date = QPushButton("적용")
        self.btn_apply_date.clicked.connect(self._apply_date_filter)

        self.btn_clear_date = QPushButton("해제")
        self.btn_clear_date.clicked.connect(self._clear_date_filter)

        date_inner_layout.addWidget(self.date_start)
        date_inner_layout.addWidget(self.lbl_tilde)
        date_inner_layout.addWidget(self.date_end)
        date_inner_layout.addWidget(self.btn_apply_date)
        date_inner_layout.addWidget(self.btn_clear_date)

        row2_layout.addWidget(self.btn_date_toggle)
        row2_layout.addWidget(self.date_container)
        row2_layout.addStretch()
        filter_layout.addLayout(row2_layout)

        self.date_container.setVisible(False)
        self._update_date_toggle_style(False)
        self._refresh_date_filter_controls()

        layout.addWidget(filter_card)

        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_link_clicked)
        self.browser.action_triggered.connect(self.on_browser_action)
        layout.addWidget(self.browser)

        btm_layout = QHBoxLayout()

        self.btn_load = QPushButton("📥 더 불러오기")
        self.btn_read_all = QPushButton("✓ 모두 읽음")
        self.btn_top = QPushButton("⬆ 맨 위로")
        self.lbl_status = QLabel("대기 중")

        if self.is_bookmark_tab:
            self.btn_load.hide()

        btm_layout.addWidget(self.btn_load)
        btm_layout.addWidget(self.btn_read_all)
        btm_layout.addWidget(self.btn_top)
        btm_layout.addStretch()
        btm_layout.addWidget(self.lbl_status)
        layout.addLayout(btm_layout)

        self.btn_top.clicked.connect(lambda: self._browser_scroll_bar().setValue(0))
        self.btn_read_all.clicked.connect(self.mark_all_read)

    def _on_sort_changed(self):
        self._request_db_reload("정렬 변경")

    def _on_unread_filter_changed(self):
        self._request_db_reload("안 읽음 필터 변경")

    def _on_hide_duplicates_changed(self):
        self._request_db_reload("중복 숨김 변경")

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

    def _on_filter_changed(self):
        """필터 입력 변경 시 디바운싱 타이머 시작"""
        self.filter_timer.stop()
        self.filter_timer.start(self.FILTER_DEBOUNCE_MS)

    def _apply_filter_debounced(self):
        """디바운싱된 필터 적용"""
        self.apply_filter()
