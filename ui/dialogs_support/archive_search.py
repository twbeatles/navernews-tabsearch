import html
import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from core.backup import AutoBackup
from core.automation_rules import normalize_automation_rules
from core.content_filters import normalize_tags, tags_to_csv, truncate_note
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.constants import LOG_FILE
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases
from core.workers import (
    IterativeJobWorker,
    _normalized_http_url,
    delete_qthread_when_finished,
    retain_worker_until_finished,
)
from ui.dialog_adapters import get_dialog_adapter

configure_logging()
logger = logging.getLogger(__name__)

class ArchiveSearchDialog(QDialog):
    def __init__(self, db, publisher_aliases=None, refresh_callback=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.publisher_aliases = normalize_publisher_aliases(publisher_aliases or {})
        self.refresh_callback = refresh_callback
        self.offset = 0
        self.limit = 50
        self.total = 0
        self.setWindowTitle("전체 아카이브 검색")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("제목/요약 검색")
        self.txt_notes = QLineEdit()
        self.txt_notes.setPlaceholderText("메모 검색")
        self.txt_publisher = QLineEdit()
        self.txt_publisher.setPlaceholderText("출처 또는 alias")
        self.txt_tag = QLineEdit()
        self.txt_tag.setPlaceholderText("태그")
        self.txt_start = QLineEdit()
        self.txt_start.setPlaceholderText("시작일 YYYY-MM-DD")
        self.txt_end = QLineEdit()
        self.txt_end.setPlaceholderText("종료일 YYYY-MM-DD")
        for widget in (self.txt_search, self.txt_notes, self.txt_publisher, self.txt_tag, self.txt_start, self.txt_end):
            layout.addWidget(widget)
        row = QHBoxLayout()
        self.chk_bookmark = QCheckBox("북마크만")
        self.chk_unread = QCheckBox("미읽음만")
        self.chk_include_deleted = QCheckBox("삭제 기사 포함")
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["최신순", "오래된순"])
        self.btn_search = QPushButton("검색")
        row.addWidget(self.chk_bookmark)
        row.addWidget(self.chk_unread)
        row.addWidget(self.chk_include_deleted)
        row.addWidget(self.sort_combo)
        row.addWidget(self.btn_search)
        layout.addLayout(row)
        self.result_label = QLabel("")
        layout.addWidget(self.result_label)
        self.result_list = QListWidget()
        self.result_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.result_list)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("이전")
        self.btn_next = QPushButton("다음")
        btn_close = QPushButton("닫기")
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addStretch()
        nav.addWidget(btn_close)
        layout.addLayout(nav)
        self.btn_search.clicked.connect(self.search_first)
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_next.clicked.connect(self.next_page)
        self.result_list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.result_list.customContextMenuRequested.connect(self.show_context_menu)
        btn_close.clicked.connect(self.accept)
        self.search_first()

    def _criteria(self) -> Dict[str, Any]:
        return {
            "filter_txt": self.txt_search.text().strip(),
            "notes_txt": self.txt_notes.text().strip(),
            "publisher_filter": self.txt_publisher.text().strip(),
            "publisher_aliases": self.publisher_aliases,
            "tag_filter": self.txt_tag.text().strip(),
            "only_bookmark": self.chk_bookmark.isChecked(),
            "only_unread": self.chk_unread.isChecked(),
            "include_deleted": self.chk_include_deleted.isChecked(),
            "start_date": self.txt_start.text().strip() or None,
            "end_date": self.txt_end.text().strip() or None,
            "sort_mode": self.sort_combo.currentText(),
        }

    def search_first(self) -> None:
        self.offset = 0
        self.load_page()

    def prev_page(self) -> None:
        self.offset = max(0, self.offset - self.limit)
        self.load_page()

    def next_page(self) -> None:
        if self.offset + self.limit < self.total:
            self.offset += self.limit
        self.load_page()

    def load_page(self) -> None:
        try:
            criteria = self._criteria()
            self.total = self.db.count_archive(**{k: v for k, v in criteria.items() if k != "sort_mode"})
            rows = self.db.search_archive(**criteria, limit=self.limit, offset=self.offset)
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"검색에 실패했습니다.\n\n{exc}")
            return
        self.result_list.clear()
        for row in rows:
            publisher = canonical_publisher(row.get("publisher", ""), self.publisher_aliases)
            state = "읽음" if row.get("is_read") else "안읽음"
            bookmark = " ★" if row.get("is_bookmarked") else ""
            deleted = " [삭제됨]" if int(row.get("is_deleted", 0) or 0) else ""
            item = QListWidgetItem(
                f"{row.get('pubDate', '')} | {publisher} | {state}{bookmark}{deleted} | {row.get('title', '')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            self.result_list.addItem(item)
        start = 0 if self.total == 0 else self.offset + 1
        end = min(self.offset + len(rows), self.total)
        self.result_label.setText(f"{start}-{end} / {self.total}개")
        self.btn_prev.setEnabled(self.offset > 0)
        self.btn_next.setEnabled(self.offset + self.limit < self.total)

    def _selected_row(self) -> Optional[Dict[str, Any]]:
        item = self.result_list.currentItem()
        if item is None:
            return None
        row = item.data(Qt.ItemDataRole.UserRole)
        return dict(row) if isinstance(row, dict) else None

    def _selected_link(self) -> str:
        row = self._selected_row()
        return str((row or {}).get("link", "") or "").strip()

    def _notify_changed(self) -> None:
        if callable(self.refresh_callback):
            self.refresh_callback()

    def _reload_after_action(self) -> None:
        self.load_page()
        self._notify_changed()

    def open_selected(self) -> None:
        row = self._selected_row()
        if not row:
            return
        link = _normalized_http_url(str(row.get("link", "") or ""))
        if not link:
            QMessageBox.warning(self, "아카이브 검색", "열 수 있는 http/https 링크가 없습니다.")
            return
        if not QDesktopServices.openUrl(QUrl(link)):
            QMessageBox.warning(self, "아카이브 검색", "브라우저에서 링크를 열지 못했습니다.")
            return
        try:
            self.db.update_status(link, "is_read", 1)
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"읽음 처리에 실패했습니다.\n\n{exc}")
            return
        self._reload_after_action()

    def toggle_bookmark(self) -> None:
        row = self._selected_row()
        link = self._selected_link()
        if not row or not link:
            return
        next_value = 0 if int(row.get("is_bookmarked", 0) or 0) else 1
        try:
            self.db.update_status(link, "is_bookmarked", next_value)
            self._reload_after_action()
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"북마크 변경에 실패했습니다.\n\n{exc}")

    def toggle_read(self) -> None:
        row = self._selected_row()
        link = self._selected_link()
        if not row or not link:
            return
        next_value = 0 if int(row.get("is_read", 0) or 0) else 1
        try:
            self.db.update_status(link, "is_read", next_value)
            self._reload_after_action()
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"읽음 상태 변경에 실패했습니다.\n\n{exc}")

    def edit_note(self) -> None:
        row = self._selected_row()
        link = self._selected_link()
        if not row or not link:
            return
        current = str(row.get("notes", "") or "")
        text, ok = QInputDialog.getMultiLineText(self, "메모 편집", "메모:", current)
        if not ok:
            return
        note_value, note_truncated = truncate_note(text)
        try:
            save_note = getattr(self.db, "save_note", None)
            if callable(save_note):
                save_note(link, note_value)
            else:
                self.db.update_status(link, "notes", note_value)
            self._reload_after_action()
            if note_truncated:
                QMessageBox.information(self, "메모 편집", "메모가 10,000자로 잘려 저장되었습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"메모 저장에 실패했습니다.\n\n{exc}")

    def edit_tags(self) -> None:
        row = self._selected_row()
        link = self._selected_link()
        if not row or not link:
            return
        current_tags = row.get("tags", "")
        if not current_tags:
            try:
                current_tags = tags_to_csv(self.db.get_tags(link))
            except Exception:
                current_tags = ""
        text, ok = QInputDialog.getText(self, "태그 편집", "태그(쉼표 구분):", text=str(current_tags or ""))
        if not ok:
            return
        try:
            self.db.set_tags(link, normalize_tags(text))
            self._reload_after_action()
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"태그 저장에 실패했습니다.\n\n{exc}")

    def restore_deleted(self) -> None:
        row = self._selected_row()
        link = self._selected_link()
        if not row or not link:
            return
        if not int(row.get("is_deleted", 0) or 0):
            return
        try:
            restore = getattr(self.db, "restore_deleted_link", None)
            if not callable(restore) or not restore(link):
                QMessageBox.warning(self, "아카이브 검색", "복구할 삭제 기사를 찾지 못했습니다.")
                return
            self._reload_after_action()
        except Exception as exc:
            QMessageBox.warning(self, "아카이브 검색", f"기사 복구에 실패했습니다.\n\n{exc}")

    def show_context_menu(self, pos) -> None:
        if self.result_list.itemAt(pos) is None:
            return
        row = self._selected_row() or {}
        is_deleted = bool(int(row.get("is_deleted", 0) or 0))
        menu = QMenu(self)
        action_open = menu.addAction("열기")
        action_bookmark = menu.addAction("북마크 토글")
        action_read = menu.addAction("읽음/안읽음")
        action_note = menu.addAction("메모 편집")
        action_tags = menu.addAction("태그 편집")
        action_restore = menu.addAction("삭제 기사 복구") if is_deleted else None
        selected = menu.exec(self.result_list.mapToGlobal(pos))
        if selected == action_open:
            self.open_selected()
        elif selected == action_bookmark:
            self.toggle_bookmark()
        elif selected == action_read:
            self.toggle_read()
        elif selected == action_note:
            self.edit_note()
        elif selected == action_tags:
            self.edit_tags()
        elif action_restore is not None and selected == action_restore:
            self.restore_deleted()

__all__ = ["ArchiveSearchDialog"]
