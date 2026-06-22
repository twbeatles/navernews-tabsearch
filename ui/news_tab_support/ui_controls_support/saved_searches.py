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


class _NewsTabSavedSearchControlsMixin:
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
        target_tab = self
        target_keyword = str(payload.get("keyword", "") or "").strip()
        if target_keyword:
            open_target = getattr(parent, "open_saved_search_target_tab", None)
            if callable(open_target):
                opened_tab = open_target(target_keyword)
                if opened_tab is not None:
                    target_tab = opened_tab
        apply_payload = getattr(target_tab, "_apply_saved_search_payload", None)
        if callable(apply_payload):
            apply_payload(payload)

    def _apply_saved_search_payload(self, payload: dict):
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
            parsed_start = QDate.fromString(str(payload.get("start_date")), "yyyy-MM-dd")
            if parsed_start.isValid():
                self.date_start.setDate(parsed_start)
        if str(payload.get("end_date", "") or ""):
            parsed_end = QDate.fromString(str(payload.get("end_date")), "yyyy-MM-dd")
            if parsed_end.isValid():
                self.date_end.setDate(parsed_end)
        if self.date_start.date() > self.date_end.date():
            start_date = self.date_start.date()
            self.date_start.setDate(self.date_end.date())
            self.date_end.setDate(start_date)
        self._date_filter_active = date_active
        self._refresh_date_filter_controls()
        # 복원된 고급 필터가 활성화되면 접힌 영역을 펼쳐 가시성을 확보
        if (self.chk_preferred_publishers.isChecked() or bool(tag_filter) or date_active):
            btn_advanced = getattr(self, "btn_advanced", None)
            if btn_advanced is not None and not btn_advanced.isChecked():
                btn_advanced.setChecked(True)
        self._request_db_reload("저장 검색 적용")

    def _delete_saved_search(self):
        parent = self._main_window()
        if parent is None:
            return
        name = str(self.combo_saved_search.currentText() or "").strip()
        if not name or name == "저장된 검색 없음":
            return
        reply = QMessageBox.question(
            self,
            "저장 검색 삭제",
            f"'{name}' 저장 검색을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_saved_search = getattr(parent, "delete_saved_search", None)
        if callable(delete_saved_search):
            delete_saved_search(name)
