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
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from core.backup import AutoBackup
from core.automation_rules import normalize_automation_rules
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.constants import LOG_FILE
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases
from core.workers import IterativeJobWorker, delete_qthread_when_finished, retain_worker_until_finished
from ui.dialog_adapters import get_dialog_adapter

configure_logging()
logger = logging.getLogger(__name__)

class TagManagerDialog(QDialog):
    def __init__(self, db, scope_items_provider=None, refresh_callback=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.scope_items_provider = scope_items_provider
        self.refresh_callback = refresh_callback
        self.setWindowTitle("태그 관리자")
        self.resize(520, 460)
        layout = QVBoxLayout(self)
        self.tag_list = QListWidget()
        layout.addWidget(self.tag_list)
        row1 = QHBoxLayout()
        btn_rename = QPushButton("이름 변경")
        btn_merge = QPushButton("병합")
        btn_delete = QPushButton("삭제")
        row1.addWidget(btn_rename)
        row1.addWidget(btn_merge)
        row1.addWidget(btn_delete)
        layout.addLayout(row1)
        row2 = QHBoxLayout()
        btn_scope_add = QPushButton("현재 탭 전체에 추가")
        btn_scope_remove = QPushButton("현재 탭 전체에서 제거")
        row2.addWidget(btn_scope_add)
        row2.addWidget(btn_scope_remove)
        layout.addLayout(row2)
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        btn_rename.clicked.connect(self.rename_selected)
        btn_merge.clicked.connect(self.merge_selected)
        btn_delete.clicked.connect(self.delete_selected)
        btn_scope_add.clicked.connect(self.add_to_scope)
        btn_scope_remove.clicked.connect(self.remove_from_scope)
        self.reload()

    def _selected_tag(self) -> str:
        item = self.tag_list.currentItem()
        if item is None:
            return ""
        text = str(item.text() or "")
        return text.split(" (", 1)[0].strip()

    def _scope_links(self) -> List[str]:
        if not callable(self.scope_items_provider):
            return []
        rows = cast(Any, self.scope_items_provider)() or []
        links = []
        for row in rows:
            link = str(row.get("link", "") or "").strip() if isinstance(row, dict) else ""
            if link and link not in links:
                links.append(link)
        return links

    def _notify_changed(self) -> None:
        if callable(self.refresh_callback):
            self.refresh_callback()

    def reload(self) -> None:
        self.tag_list.clear()
        try:
            for tag, count in self.db.get_tag_usage():
                self.tag_list.addItem(f"{tag} ({count})")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 목록을 불러오지 못했습니다.\n\n{exc}")

    def rename_selected(self) -> None:
        tag = self._selected_tag()
        if not tag:
            return
        new_tag, ok = QInputDialog.getText(self, "태그 이름 변경", "새 태그 이름:", text=tag)
        if not ok:
            return
        try:
            changed = self.db.rename_tag(tag, new_tag)
            self.reload()
            self._notify_changed()
            QMessageBox.information(self, "태그", f"{changed}개 기사 태그를 변경했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 이름 변경에 실패했습니다.\n\n{exc}")

    def merge_selected(self) -> None:
        tag = self._selected_tag()
        if not tag:
            return
        target, ok = QInputDialog.getText(self, "태그 병합", "병합할 대상 태그:", text=tag)
        if not ok:
            return
        try:
            changed = self.db.rename_tag(tag, target)
            self.reload()
            self._notify_changed()
            QMessageBox.information(self, "태그", f"{changed}개 기사 태그를 병합했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 병합에 실패했습니다.\n\n{exc}")

    def delete_selected(self) -> None:
        tag = self._selected_tag()
        if not tag:
            return
        reply = QMessageBox.question(
            self,
            "태그 삭제",
            f"'{tag}' 태그를 모든 기사에서 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            changed = self.db.delete_tag_everywhere(tag)
            self.reload()
            self._notify_changed()
            QMessageBox.information(self, "태그", f"{changed}개 기사에서 태그를 삭제했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 삭제에 실패했습니다.\n\n{exc}")

    def add_to_scope(self) -> None:
        tag, ok = QInputDialog.getText(self, "현재 탭 전체 태그 추가", "추가할 태그:")
        if not ok:
            return
        links = self._scope_links()
        if not links:
            QMessageBox.information(self, "태그", "현재 탭 범위에 적용할 기사가 없습니다.")
            return
        try:
            changed = self.db.bulk_add_tag_to_links(links, tag)
            self.reload()
            self._notify_changed()
            QMessageBox.information(self, "태그", f"{changed}개 기사에 태그를 추가했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 추가에 실패했습니다.\n\n{exc}")

    def remove_from_scope(self) -> None:
        tag = self._selected_tag()
        if not tag:
            tag, ok = QInputDialog.getText(self, "현재 탭 전체 태그 제거", "제거할 태그:")
            if not ok:
                return
        links = self._scope_links()
        if not links:
            QMessageBox.information(self, "태그", "현재 탭 범위에 적용할 기사가 없습니다.")
            return
        try:
            changed = self.db.bulk_remove_tag_from_links(links, tag)
            self.reload()
            self._notify_changed()
            QMessageBox.information(self, "태그", f"{changed}개 기사에서 태그를 제거했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "태그", f"태그 제거에 실패했습니다.\n\n{exc}")
class ArchiveSearchDialog(QDialog):
    def __init__(self, db, publisher_aliases=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.publisher_aliases = normalize_publisher_aliases(publisher_aliases or {})
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
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["최신순", "오래된순"])
        self.btn_search = QPushButton("검색")
        row.addWidget(self.chk_bookmark)
        row.addWidget(self.chk_unread)
        row.addWidget(self.sort_combo)
        row.addWidget(self.btn_search)
        layout.addLayout(row)
        self.result_label = QLabel("")
        layout.addWidget(self.result_label)
        self.result_list = QListWidget()
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
            self.result_list.addItem(
                f"{row.get('pubDate', '')} | {publisher} | {state}{bookmark} | {row.get('title', '')}"
            )
        start = 0 if self.total == 0 else self.offset + 1
        end = min(self.offset + len(rows), self.total)
        self.result_label.setText(f"{start}-{end} / {self.total}개")
        self.btn_prev.setEnabled(self.offset > 0)
        self.btn_next.setEnabled(self.offset + self.limit < self.total)
class AutomationRulesDialog(QDialog):
    def __init__(self, rules, scope_items_provider, apply_callback, save_callback, parent=None):
        super().__init__(parent)
        self.scope_items_provider = scope_items_provider
        self.apply_callback = apply_callback
        self.save_callback = save_callback
        self.setWindowTitle("자동화 규칙")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        info = QLabel("JSON 목록으로 규칙을 편집합니다. 조건: keywords/exclude_words/publishers/queries, 동작: add_tags/mark_read/mark_bookmark/exclude")
        layout.addWidget(info)
        self.editor = QTextEdit()
        self.editor.setPlainText(json.dumps(normalize_automation_rules(rules), ensure_ascii=False, indent=2))
        layout.addWidget(self.editor)
        row = QHBoxLayout()
        btn_preview = QPushButton("미리보기")
        btn_apply = QPushButton("지금 적용")
        btn_save = QPushButton("저장")
        btn_close = QPushButton("닫기")
        row.addWidget(btn_preview)
        row.addWidget(btn_apply)
        row.addWidget(btn_save)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)
        btn_preview.clicked.connect(self.preview)
        btn_apply.clicked.connect(self.apply_now)
        btn_save.clicked.connect(self.save)
        btn_close.clicked.connect(self.accept)

    def _rules(self) -> List[Dict[str, Any]]:
        payload = json.loads(self.editor.toPlainText() or "[]")
        return normalize_automation_rules(payload)

    def preview(self) -> None:
        try:
            rules = self._rules()
            rows = self.scope_items_provider() if callable(self.scope_items_provider) else []
            result = self.apply_callback(rows, rules, dry_run=True)
            QMessageBox.information(self, "자동화 미리보기", f"매칭 {result.get('matched', 0)}개 / 태그 {result.get('tagged', 0)}개 / 읽음 {result.get('read', 0)}개 / 북마크 {result.get('bookmarked', 0)}개")
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"규칙 미리보기에 실패했습니다.\n\n{exc}")

    def apply_now(self) -> None:
        try:
            rules = self._rules()
            rows = self.scope_items_provider() if callable(self.scope_items_provider) else []
            result = self.apply_callback(rows, rules, dry_run=False)
            self.save_callback(rules)
            QMessageBox.information(self, "자동화", f"적용 완료: 매칭 {result.get('matched', 0)}개")
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"규칙 적용에 실패했습니다.\n\n{exc}")

    def save(self) -> None:
        try:
            rules = self._rules()
            self.save_callback(rules)
            self.editor.setPlainText(json.dumps(rules, ensure_ascii=False, indent=2))
            QMessageBox.information(self, "자동화", "규칙을 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"규칙 저장에 실패했습니다.\n\n{exc}")
class PublisherAliasDialog(QDialog):
    def __init__(self, aliases, save_callback, parent=None):
        super().__init__(parent)
        self.save_callback = save_callback
        self.setWindowTitle("출처 Alias")
        self.resize(620, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('JSON 객체로 입력합니다. 예: {"naver:oid:001": "연합뉴스"}'))
        self.editor = QTextEdit()
        self.editor.setPlainText(json.dumps(normalize_publisher_aliases(aliases), ensure_ascii=False, indent=2))
        layout.addWidget(self.editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def save(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText() or "{}")
            aliases = normalize_publisher_aliases(payload)
            self.save_callback(aliases)
            self.editor.setPlainText(json.dumps(aliases, ensure_ascii=False, indent=2))
            QMessageBox.information(self, "출처 Alias", "Alias 설정을 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "출처 Alias", f"Alias 저장에 실패했습니다.\n\n{exc}")
