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

        self.chk_preferred_publishers = QCheckBox("선호 출처만")
        self.chk_preferred_publishers.stateChanged.connect(self._on_preferred_publishers_changed)

        self.combo_tag_filter = NoScrollComboBox()
        self.combo_tag_filter.setEditable(True)
        self.combo_tag_filter.setMinimumWidth(130)
        self.combo_tag_filter.currentTextChanged.connect(lambda _text: self._on_tag_filter_changed())
        self._refresh_tag_filter_options()

        row2_layout.addWidget(self.chk_unread)
        row2_layout.addWidget(self.chk_hide_dup)
        row2_layout.addWidget(self.chk_preferred_publishers)
        row2_layout.addWidget(QLabel("태그:"))
        row2_layout.addWidget(self.combo_tag_filter)

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

        row3_layout = QHBoxLayout()
        row3_layout.setSpacing(6)
        self.combo_saved_search = NoScrollComboBox()
        self.combo_saved_search.setMinimumWidth(180)
        self.btn_apply_saved_search = QPushButton("적용")
        self.btn_apply_saved_search.clicked.connect(self._apply_saved_search)
        self.btn_save_search = QPushButton("검색 저장")
        self.btn_save_search.clicked.connect(self._save_current_search)
        row3_layout.addWidget(QLabel("저장 검색:"))
        row3_layout.addWidget(self.combo_saved_search)
        row3_layout.addWidget(self.btn_apply_saved_search)
        row3_layout.addWidget(self.btn_save_search)
        row3_layout.addStretch()
        filter_layout.addLayout(row3_layout)
        self._refresh_saved_search_combo()

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

    def _on_preferred_publishers_changed(self):
        self._request_db_reload("선호 출처 필터 변경")

    def _on_tag_filter_changed(self):
        if hasattr(self, "filter_timer"):
            self.filter_timer.start(self.FILTER_DEBOUNCE_MS)

    def _refresh_tag_filter_options(self):
        combo = getattr(self, "combo_tag_filter", None)
        if combo is None:
            return
        current = str(combo.currentText() or "").strip()
        known_tags = []
        try:
            get_known_tags = getattr(self.db, "get_known_tags", None)
            if callable(get_known_tags):
                known_tags = list(get_known_tags())
        except Exception:
            known_tags = []
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("모든 태그")
            for tag in known_tags:
                combo.addItem(str(tag))
            if current and current != "모든 태그":
                idx = combo.findText(current)
                if idx < 0:
                    combo.addItem(current)
                    idx = combo.findText(current)
                combo.setCurrentIndex(idx)
            else:
                combo.setCurrentIndex(0)

    def _refresh_saved_search_combo(self):
        combo = getattr(self, "combo_saved_search", None)
        if combo is None:
            return
        current = str(combo.currentText() or "").strip()
        parent = self._main_window()
        saved_searches = getattr(parent, "saved_searches", {}) if parent is not None else {}
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("저장된 검색 없음")
            if isinstance(saved_searches, dict):
                for name in sorted(saved_searches.keys(), key=str.casefold):
                    combo.addItem(str(name))
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _current_saved_search_payload(self):
        start_date, end_date = self._current_date_range()
        return {
            "keyword": self.keyword,
            "filter_txt": self._current_filter_text(),
            "sort_mode": self.combo_sort.currentText(),
            "only_unread": self.chk_unread.isChecked(),
            "hide_duplicates": self.chk_hide_dup.isChecked(),
            "date_active": bool(self._date_filter_active),
            "start_date": start_date or "",
            "end_date": end_date or "",
            "tag_filter": self._current_tag_filter(),
            "only_preferred_publishers": self._only_preferred_publishers_enabled(),
        }

    def _save_current_search(self):
        parent = self._main_window()
        if parent is None:
            return
        default_name = self.keyword
        text, ok = QInputDialog.getText(self, "검색 저장", "저장 이름:", text=default_name)
        if not ok:
            return
        name = str(text or "").strip()
        if not name:
            return
        save_saved_search = getattr(parent, "save_saved_search", None)
        if callable(save_saved_search):
            save_saved_search(name, self._current_saved_search_payload())
            self._refresh_saved_search_combo()

    def _apply_saved_search(self):
        parent = self._main_window()
        if parent is None:
            return
        name = str(self.combo_saved_search.currentText() or "").strip()
        if not name or name == "저장된 검색 없음":
            return
        payload = getattr(parent, "saved_searches", {}).get(name, {})
        if not isinstance(payload, dict):
            return
        with QSignalBlocker(self.inp_filter):
            self.inp_filter.setText(str(payload.get("filter_txt", "") or ""))
        sort_idx = self.combo_sort.findText(str(payload.get("sort_mode", "최신순") or "최신순"))
        if sort_idx >= 0:
            with QSignalBlocker(self.combo_sort):
                self.combo_sort.setCurrentIndex(sort_idx)
        with QSignalBlocker(self.chk_unread):
            self.chk_unread.setChecked(bool(payload.get("only_unread", False)))
        with QSignalBlocker(self.chk_hide_dup):
            self.chk_hide_dup.setChecked(bool(payload.get("hide_duplicates", False)))
        with QSignalBlocker(self.chk_preferred_publishers):
            self.chk_preferred_publishers.setChecked(bool(payload.get("only_preferred_publishers", False)))
        tag_filter = str(payload.get("tag_filter", "") or "").strip()
        with QSignalBlocker(self.combo_tag_filter):
            idx = self.combo_tag_filter.findText(tag_filter) if tag_filter else 0
            if tag_filter and idx < 0:
                self.combo_tag_filter.addItem(tag_filter)
                idx = self.combo_tag_filter.findText(tag_filter)
            self.combo_tag_filter.setCurrentIndex(idx if idx >= 0 else 0)
            if tag_filter and self.combo_tag_filter.isEditable():
                self.combo_tag_filter.setEditText(tag_filter)
        date_active = bool(payload.get("date_active", False))
        with QSignalBlocker(self.btn_date_toggle):
            self.btn_date_toggle.setChecked(date_active)
        self.date_container.setVisible(date_active)
        if str(payload.get("start_date", "") or ""):
            self.date_start.setDate(QDate.fromString(str(payload.get("start_date")), "yyyy-MM-dd"))
        if str(payload.get("end_date", "") or ""):
            self.date_end.setDate(QDate.fromString(str(payload.get("end_date")), "yyyy-MM-dd"))
        self._date_filter_active = date_active
        self._refresh_date_filter_controls()
        self._request_db_reload("저장 검색 적용")

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
