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
from core.content_filters import normalize_tags, tags_to_csv
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

class TagManagerDialog(QDialog):
    def __init__(self, db, scope_items_provider=None, refresh_callback=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.scope_items_provider = scope_items_provider
        self.refresh_callback = refresh_callback
        self._scope_worker: Optional[IterativeJobWorker] = None
        self._scope_worker_op = ""
        self._maintenance_started = False
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

    def _scope_links(self, context: Optional[Any] = None) -> List[str]:
        if not callable(self.scope_items_provider):
            return []
        provider = cast(Any, self.scope_items_provider)
        try:
            rows = provider(context) or []
        except TypeError:
            rows = provider() or []
        links = []
        seen = set()
        for row in rows:
            link = str(row.get("link", "") or "").strip() if isinstance(row, dict) else ""
            if link and link not in seen:
                seen.add(link)
                links.append(link)
        return links

    def _maintenance_parent(self) -> Optional[Any]:
        parent = self.parent()
        return parent if parent is not None else None

    def _begin_scope_job(self) -> bool:
        parent = self._maintenance_parent()
        begin = getattr(parent, "begin_database_maintenance", None)
        if callable(begin):
            ok, message = cast(tuple[bool, str], begin("tag_scope_update"))
            if not ok:
                QMessageBox.warning(self, "태그", message or "유지보수 모드로 전환하지 못했습니다.")
                return False
            self._maintenance_started = True
        return True

    def _finish_scope_job(self, operation: str, affected_count: int) -> None:
        parent = self._maintenance_parent()
        if self._maintenance_started:
            end = getattr(parent, "end_database_maintenance", None)
            if callable(end):
                end()
            self._maintenance_started = False
        completed = getattr(parent, "on_database_maintenance_completed", None)
        if callable(completed):
            completed(operation, affected_count)
        else:
            self._notify_changed()
        self.reload()

    def _set_scope_buttons_enabled(self, enabled: bool) -> None:
        for button in self.findChildren(QPushButton):
            button.setEnabled(enabled)

    def _start_scope_tag_job(self, tag: str, *, remove: bool) -> None:
        normalized = normalize_tags([tag])
        tag = normalized[0] if normalized else ""
        if not tag:
            QMessageBox.information(self, "태그", "적용할 태그를 입력하세요.")
            return
        if self._scope_worker is not None:
            QMessageBox.information(self, "태그", "이미 현재 탭 전체 작업이 진행 중입니다.")
            return
        if not self._begin_scope_job():
            return

        def job(context):
            links = self._scope_links(context)
            total = len(links)
            context.report(current=0, total=total, message="현재 탭 전체 범위 계산 완료")
            if not links:
                return {"changed": 0, "total": 0, "tag": tag, "remove": remove}
            if remove:
                changed = self.db.bulk_remove_tag_from_links(links, tag)
            else:
                changed = self.db.bulk_add_tag_to_links(links, tag)
            context.report(current=total, total=total, message="태그 적용 완료")
            return {"changed": int(changed or 0), "total": total, "tag": tag, "remove": remove}

        worker = IterativeJobWorker(job, parent=self)
        self._scope_worker = worker
        self._scope_worker_op = "tag_scope_update"
        self._set_scope_buttons_enabled(False)

        def on_finished(result: Dict[str, Any]) -> None:
            changed = int(result.get("changed", 0) or 0)
            total = int(result.get("total", 0) or 0)
            self._scope_worker = None
            self._set_scope_buttons_enabled(True)
            self._finish_scope_job("tag_scope_update", changed)
            action = "제거" if bool(result.get("remove")) else "추가"
            QMessageBox.information(
                self,
                "태그",
                f"현재 탭 전체 범위 {total:,}개 중 {changed:,}개 기사에 태그를 {action}했습니다.",
            )

        def on_error(error_msg: str) -> None:
            self._scope_worker = None
            self._set_scope_buttons_enabled(True)
            self._finish_scope_job("tag_scope_update", 0)
            QMessageBox.warning(self, "태그", f"현재 탭 전체 태그 작업에 실패했습니다.\n\n{error_msg}")

        def on_cancelled() -> None:
            self._scope_worker = None
            self._set_scope_buttons_enabled(True)
            self._finish_scope_job("tag_scope_update", 0)
            QMessageBox.information(self, "태그", "현재 탭 전체 태그 작업을 취소했습니다.")

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.cancelled.connect(on_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()

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
        self._start_scope_tag_job(tag, remove=False)

    def remove_from_scope(self) -> None:
        tag = self._selected_tag()
        if not tag:
            tag, ok = QInputDialog.getText(self, "현재 탭 전체 태그 제거", "제거할 태그:")
            if not ok:
                return
        self._start_scope_tag_job(tag, remove=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._scope_worker is not None and self._scope_worker.isRunning():
            self._scope_worker.stop()
        super().closeEvent(event)
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
            item = QListWidgetItem(
                f"{row.get('pubDate', '')} | {publisher} | {state}{bookmark} | {row.get('title', '')}"
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
        try:
            save_note = getattr(self.db, "save_note", None)
            if callable(save_note):
                save_note(link, text)
            else:
                self.db.update_status(link, "notes", text)
            self._reload_after_action()
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

    def show_context_menu(self, pos) -> None:
        if self.result_list.itemAt(pos) is None:
            return
        menu = QMenu(self)
        action_open = menu.addAction("열기")
        action_bookmark = menu.addAction("북마크 토글")
        action_read = menu.addAction("읽음/안읽음")
        action_note = menu.addAction("메모 편집")
        action_tags = menu.addAction("태그 편집")
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
class AutomationRulesDialog(QDialog):
    def __init__(
        self,
        rules,
        scope_items_provider,
        apply_callback,
        save_callback,
        refresh_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.scope_items_provider = scope_items_provider
        self.apply_callback = apply_callback
        self.save_callback = save_callback
        self.refresh_callback = refresh_callback
        self.rules: List[Dict[str, Any]] = normalize_automation_rules(rules)
        self._apply_worker: Optional[IterativeJobWorker] = None
        self._maintenance_started = False
        self.setWindowTitle("자동화 규칙")
        self.resize(860, 640)

        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.rule_list = QListWidget()
        left.addWidget(self.rule_list)
        list_buttons = QHBoxLayout()
        btn_new = QPushButton("추가")
        btn_delete = QPushButton("삭제")
        list_buttons.addWidget(btn_new)
        list_buttons.addWidget(btn_delete)
        left.addLayout(list_buttons)
        body.addLayout(left, 1)

        form_box = QGroupBox("규칙")
        form = QFormLayout(form_box)
        self.txt_name = QLineEdit()
        self.chk_enabled = QCheckBox("활성화")
        self.txt_keywords = QLineEdit()
        self.txt_keywords.setPlaceholderText("쉼표로 구분")
        self.txt_exclude_words = QLineEdit()
        self.txt_exclude_words.setPlaceholderText("쉼표로 구분")
        self.txt_publishers = QLineEdit()
        self.txt_publishers.setPlaceholderText("언론사/도메인/alias, 쉼표 구분")
        self.txt_queries = QLineEdit()
        self.txt_queries.setPlaceholderText("탭 검색어, 쉼표 구분")
        self.txt_add_tags = QLineEdit()
        self.txt_add_tags.setPlaceholderText("추가 태그, 쉼표 구분")
        self.chk_mark_read = QCheckBox("읽음 처리")
        self.chk_mark_bookmark = QCheckBox("북마크")
        self.chk_exclude = QCheckBox("제외 태그 + 읽음")
        self.chk_suppress_notification = QCheckBox("이번 fetch 알림 억제")
        flags = QHBoxLayout()
        flags.addWidget(self.chk_mark_read)
        flags.addWidget(self.chk_mark_bookmark)
        flags.addWidget(self.chk_exclude)
        flags.addWidget(self.chk_suppress_notification)
        flags.addStretch()
        form.addRow("이름", self.txt_name)
        form.addRow("", self.chk_enabled)
        form.addRow("키워드", self.txt_keywords)
        form.addRow("제외어", self.txt_exclude_words)
        form.addRow("출처", self.txt_publishers)
        form.addRow("검색어", self.txt_queries)
        form.addRow("태그", self.txt_add_tags)
        form.addRow("동작", flags)
        btn_update_form = QPushButton("폼 내용을 목록에 반영")
        form.addRow("", btn_update_form)
        body.addWidget(form_box, 2)
        layout.addLayout(body)

        advanced = QGroupBox("고급 JSON")
        advanced_layout = QVBoxLayout(advanced)
        self.editor = QTextEdit()
        self.editor.setMinimumHeight(130)
        advanced_layout.addWidget(self.editor)
        btn_load_json = QPushButton("JSON에서 목록으로 불러오기")
        advanced_layout.addWidget(btn_load_json)
        layout.addWidget(advanced)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        btn_preview = QPushButton("미리보기")
        btn_apply = QPushButton("현재 탭 전체 적용")
        btn_save = QPushButton("저장")
        btn_close = QPushButton("닫기")
        row.addWidget(btn_preview)
        row.addWidget(btn_apply)
        row.addWidget(btn_save)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)

        btn_new.clicked.connect(self.add_rule)
        btn_delete.clicked.connect(self.delete_selected_rule)
        btn_update_form.clicked.connect(lambda: self.save_form_to_selected(silent=False))
        btn_load_json.clicked.connect(self.load_rules_from_editor)
        btn_preview.clicked.connect(self.preview)
        btn_apply.clicked.connect(self.apply_now)
        btn_save.clicked.connect(self.save)
        btn_close.clicked.connect(self.accept)
        self.rule_list.currentRowChanged.connect(self.load_rule_to_form)

        self.refresh_rule_list(select_row=0 if self.rules else -1)
        self.sync_editor()

    def _split_csv(self, value: str) -> List[str]:
        return [part.strip() for part in str(value or "").split(",") if part.strip()]

    def _join_csv(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return ""

    def selected_index(self) -> int:
        index = self.rule_list.currentRow()
        return index if 0 <= index < len(self.rules) else -1

    def refresh_rule_list(self, *, select_row: int = -1) -> None:
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        for rule in self.rules:
            name = str(rule.get("name") or "규칙")
            enabled = "" if bool(rule.get("enabled", True)) else " (끔)"
            self.rule_list.addItem(f"{name}{enabled}")
        self.rule_list.blockSignals(False)
        if self.rules:
            row = min(max(select_row, 0), len(self.rules) - 1)
            self.rule_list.setCurrentRow(row)
            self.load_rule_to_form(row)
        else:
            self.load_rule_to_form(-1)

    def load_rule_to_form(self, row: int) -> None:
        if row < 0 or row >= len(self.rules):
            self.txt_name.clear()
            self.chk_enabled.setChecked(True)
            self.txt_keywords.clear()
            self.txt_exclude_words.clear()
            self.txt_publishers.clear()
            self.txt_queries.clear()
            self.txt_add_tags.clear()
            self.chk_mark_read.setChecked(False)
            self.chk_mark_bookmark.setChecked(False)
            self.chk_exclude.setChecked(False)
            self.chk_suppress_notification.setChecked(False)
            return
        rule = self.rules[row]
        self.txt_name.setText(str(rule.get("name") or ""))
        self.chk_enabled.setChecked(bool(rule.get("enabled", True)))
        self.txt_keywords.setText(self._join_csv(rule.get("keywords", [])))
        self.txt_exclude_words.setText(self._join_csv(rule.get("exclude_words", [])))
        self.txt_publishers.setText(self._join_csv(rule.get("publishers", [])))
        self.txt_queries.setText(self._join_csv(rule.get("queries", [])))
        self.txt_add_tags.setText(self._join_csv(rule.get("add_tags", [])))
        self.chk_mark_read.setChecked(bool(rule.get("mark_read", False)))
        self.chk_mark_bookmark.setChecked(bool(rule.get("mark_bookmark", False)))
        self.chk_exclude.setChecked(bool(rule.get("exclude", False)))
        self.chk_suppress_notification.setChecked(bool(rule.get("suppress_notification", False)))

    def form_rule(self) -> Dict[str, Any]:
        return {
            "name": self.txt_name.text().strip() or "규칙",
            "enabled": self.chk_enabled.isChecked(),
            "keywords": self._split_csv(self.txt_keywords.text()),
            "exclude_words": self._split_csv(self.txt_exclude_words.text()),
            "publishers": self._split_csv(self.txt_publishers.text()),
            "queries": self._split_csv(self.txt_queries.text()),
            "add_tags": normalize_tags(self.txt_add_tags.text()),
            "mark_read": self.chk_mark_read.isChecked(),
            "mark_bookmark": self.chk_mark_bookmark.isChecked(),
            "exclude": self.chk_exclude.isChecked(),
            "suppress_notification": self.chk_suppress_notification.isChecked(),
        }

    def save_form_to_selected(self, *, silent: bool = False) -> bool:
        index = self.selected_index()
        if index < 0:
            if not silent:
                QMessageBox.information(self, "자동화", "선택된 규칙이 없습니다.")
            return False
        normalized = normalize_automation_rules([self.form_rule()])
        if not normalized:
            if not silent:
                QMessageBox.warning(self, "자동화", "조건과 동작이 모두 있는 규칙만 저장할 수 있습니다.")
            return False
        self.rules[index] = normalized[0]
        self.refresh_rule_list(select_row=index)
        self.sync_editor()
        return True

    def add_rule(self) -> None:
        self.rules.append(
            normalize_automation_rules(
                [
                    {
                        "name": "새 규칙",
                        "keywords": ["키워드"],
                        "add_tags": ["관심"],
                        "enabled": True,
                    }
                ]
            )[0]
        )
        self.refresh_rule_list(select_row=len(self.rules) - 1)
        self.sync_editor()

    def delete_selected_rule(self) -> None:
        index = self.selected_index()
        if index < 0:
            return
        del self.rules[index]
        self.refresh_rule_list(select_row=min(index, len(self.rules) - 1))
        self.sync_editor()

    def sync_editor(self) -> None:
        self.editor.setPlainText(json.dumps(self.rules, ensure_ascii=False, indent=2))

    def load_rules_from_editor(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText() or "[]")
            raw_count = len(payload) if isinstance(payload, list) else 0
            normalized = normalize_automation_rules(payload)
            dropped = max(0, raw_count - len(normalized))
            self.rules = normalized
            self.refresh_rule_list(select_row=0 if self.rules else -1)
            self.sync_editor()
            QMessageBox.information(
                self,
                "자동화",
                f"JSON에서 {len(normalized)}개 규칙을 불러왔습니다. 정규화로 제외된 항목: {dropped}개",
            )
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"JSON 불러오기에 실패했습니다.\n\n{exc}")

    def current_rules(self) -> Optional[List[Dict[str, Any]]]:
        if self.selected_index() >= 0 and not self.save_form_to_selected(silent=False):
            return None
        return normalize_automation_rules(self.rules)

    def _scope_items(self, context: Optional[Any] = None) -> List[Dict[str, Any]]:
        if not callable(self.scope_items_provider):
            return []
        provider = cast(Any, self.scope_items_provider)
        try:
            return list(provider(context) or [])
        except TypeError:
            return list(provider() or [])

    def preview(self) -> None:
        try:
            rules = self.current_rules()
            if rules is None:
                return
            rows = self._scope_items()
            result = self.apply_callback(rows, rules, dry_run=True)
            QMessageBox.information(
                self,
                "자동화 미리보기",
                " / ".join(
                    [
                        f"매칭 {result.get('matched', 0)}개",
                        f"태그 {result.get('tagged', 0)}개",
                        f"읽음 {result.get('read', 0)}개",
                        f"북마크 {result.get('bookmarked', 0)}개",
                        f"알림 억제 {result.get('suppressed', 0)}개",
                    ]
                ),
            )
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"규칙 미리보기에 실패했습니다.\n\n{exc}")

    def _maintenance_parent(self) -> Optional[Any]:
        parent = self.parent()
        return parent if parent is not None else None

    def _begin_apply_job(self) -> bool:
        parent = self._maintenance_parent()
        begin = getattr(parent, "begin_database_maintenance", None)
        if callable(begin):
            ok, message = cast(tuple[bool, str], begin("automation_rules"))
            if not ok:
                QMessageBox.warning(self, "자동화", message or "유지보수 모드로 전환하지 못했습니다.")
                return False
            self._maintenance_started = True
        return True

    def _finish_apply_job(self, affected_count: int) -> None:
        parent = self._maintenance_parent()
        if self._maintenance_started:
            end = getattr(parent, "end_database_maintenance", None)
            if callable(end):
                end()
            self._maintenance_started = False
        completed = getattr(parent, "on_database_maintenance_completed", None)
        if callable(completed):
            completed("automation_rules", affected_count)
        elif callable(self.refresh_callback):
            self.refresh_callback()

    def _apply_rules(self, rows: List[Dict[str, Any]], rules: List[Dict[str, Any]], dry_run: bool) -> Dict[str, Any]:
        try:
            return dict(self.apply_callback(rows, rules, dry_run=dry_run, refresh=False))
        except TypeError as exc:
            if "refresh" not in str(exc):
                raise
            return dict(self.apply_callback(rows, rules, dry_run=dry_run))

    def apply_now(self) -> None:
        rules = self.current_rules()
        if rules is None:
            return
        if self._apply_worker is not None:
            QMessageBox.information(self, "자동화", "이미 현재 탭 전체 적용이 진행 중입니다.")
            return
        if not self._begin_apply_job():
            return

        def job(context):
            rows = self._scope_items(context)
            context.report(current=0, total=len(rows), message="자동화 규칙 적용 중...")
            result = self._apply_rules(rows, rules, dry_run=False)
            context.report(current=len(rows), total=len(rows), message="자동화 규칙 적용 완료")
            result["total"] = len(rows)
            return result

        worker = IterativeJobWorker(job, parent=self)
        self._apply_worker = worker
        self.status_label.setText("현재 탭 전체 적용 중...")

        def on_finished(result: Dict[str, Any]) -> None:
            self._apply_worker = None
            self.save_callback(rules)
            self._finish_apply_job(int(result.get("matched", 0) or 0))
            self.status_label.setText("")
            QMessageBox.information(
                self,
                "자동화",
                " / ".join(
                    [
                        f"검사 {result.get('total', 0)}개",
                        f"매칭 {result.get('matched', 0)}개",
                        f"태그 {result.get('tagged', 0)}개",
                        f"읽음 {result.get('read', 0)}개",
                        f"북마크 {result.get('bookmarked', 0)}개",
                        f"알림 억제 {result.get('suppressed', 0)}개",
                    ]
                ),
            )

        def on_error(error_msg: str) -> None:
            self._apply_worker = None
            self._finish_apply_job(0)
            self.status_label.setText("")
            QMessageBox.warning(self, "자동화", f"규칙 적용에 실패했습니다.\n\n{error_msg}")

        def on_cancelled() -> None:
            self._apply_worker = None
            self._finish_apply_job(0)
            self.status_label.setText("")
            QMessageBox.information(self, "자동화", "규칙 적용을 취소했습니다.")

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.cancelled.connect(on_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()

    def save(self) -> None:
        try:
            rules = self.current_rules()
            if rules is None:
                return
            self.save_callback(rules)
            self.rules = rules
            self.refresh_rule_list(select_row=self.selected_index())
            self.sync_editor()
            QMessageBox.information(self, "자동화", f"규칙 {len(rules)}개를 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "자동화", f"규칙 저장에 실패했습니다.\n\n{exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._apply_worker is not None and self._apply_worker.isRunning():
            self._apply_worker.stop()
        super().closeEvent(event)


class PublisherAliasDialog(QDialog):
    def __init__(self, aliases, save_callback, parent=None):
        super().__init__(parent)
        self.save_callback = save_callback
        self.aliases: Dict[str, str] = normalize_publisher_aliases(aliases)
        self._editing_source = ""
        self.setWindowTitle("출처 Alias")
        self.resize(720, 520)
        layout = QVBoxLayout(self)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.alias_list = QListWidget()
        left.addWidget(self.alias_list)
        row_buttons = QHBoxLayout()
        btn_add_update = QPushButton("추가/수정")
        btn_delete = QPushButton("삭제")
        row_buttons.addWidget(btn_add_update)
        row_buttons.addWidget(btn_delete)
        left.addLayout(row_buttons)
        body.addLayout(left, 1)

        form_box = QGroupBox("Alias")
        form = QFormLayout(form_box)
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("예: naver:oid:001 또는 example.com")
        self.txt_alias = QLineEdit()
        self.txt_alias.setPlaceholderText("예: 연합뉴스")
        form.addRow("source", self.txt_source)
        form.addRow("alias", self.txt_alias)
        body.addWidget(form_box, 2)
        layout.addLayout(body)

        advanced = QGroupBox("고급 JSON")
        advanced_layout = QVBoxLayout(advanced)
        self.editor = QTextEdit()
        self.editor.setMinimumHeight(120)
        advanced_layout.addWidget(self.editor)
        btn_load_json = QPushButton("JSON에서 목록으로 불러오기")
        advanced_layout.addWidget(btn_load_json)
        layout.addWidget(advanced)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

        self.alias_list.currentRowChanged.connect(self.load_alias_to_form)
        btn_add_update.clicked.connect(lambda: self.apply_form(silent=False))
        btn_delete.clicked.connect(self.delete_selected_alias)
        btn_load_json.clicked.connect(self.load_aliases_from_editor)
        self.refresh_alias_list(select_row=0 if self.aliases else -1)
        self.sync_editor()

    def refresh_alias_list(self, *, select_row: int = -1) -> None:
        self.alias_list.blockSignals(True)
        self.alias_list.clear()
        for source, alias in sorted(self.aliases.items(), key=lambda item: item[0].casefold()):
            item = QListWidgetItem(f"{source} -> {alias}")
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.alias_list.addItem(item)
        self.alias_list.blockSignals(False)
        if self.aliases:
            row = min(max(select_row, 0), self.alias_list.count() - 1)
            self.alias_list.setCurrentRow(row)
            self.load_alias_to_form(row)
        else:
            self.load_alias_to_form(-1)

    def load_alias_to_form(self, row: int) -> None:
        if row < 0 or row >= self.alias_list.count():
            self._editing_source = ""
            self.txt_source.clear()
            self.txt_alias.clear()
            return
        item = self.alias_list.item(row)
        if item is None:
            return
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._editing_source = source
        self.txt_source.setText(source)
        self.txt_alias.setText(str(self.aliases.get(source, "")))

    def apply_form(self, *, silent: bool = False) -> bool:
        source = " ".join(self.txt_source.text().strip().split())
        alias = " ".join(self.txt_alias.text().strip().split())
        if not source and not alias:
            return True
        if not source or not alias:
            if not silent:
                QMessageBox.warning(self, "출처 Alias", "source와 alias를 모두 입력하세요.")
            return False
        if self._editing_source and self._editing_source != source:
            self.aliases.pop(self._editing_source, None)
        normalized = normalize_publisher_aliases({**self.aliases, source: alias})
        dropped = max(0, len(self.aliases) + 1 - len(normalized))
        self.aliases = normalized
        self._editing_source = source
        self.refresh_alias_list(select_row=0)
        self.sync_editor()
        if not silent:
            QMessageBox.information(
                self,
                "출처 Alias",
                f"Alias를 반영했습니다. 정규화로 제외된 항목: {dropped}개",
            )
        return True

    def delete_selected_alias(self) -> None:
        item = self.alias_list.currentItem()
        if item is None:
            return
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if source:
            self.aliases.pop(source, None)
        self.refresh_alias_list(select_row=max(0, self.alias_list.currentRow() - 1))
        self.sync_editor()

    def sync_editor(self) -> None:
        self.editor.setPlainText(json.dumps(self.aliases, ensure_ascii=False, indent=2))

    def load_aliases_from_editor(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText() or "{}")
            raw_count = len(payload) if isinstance(payload, dict) else 0
            aliases = normalize_publisher_aliases(payload)
            dropped = max(0, raw_count - len(aliases))
            self.aliases = aliases
            self.refresh_alias_list(select_row=0 if self.aliases else -1)
            self.sync_editor()
            QMessageBox.information(
                self,
                "출처 Alias",
                f"JSON에서 {len(aliases)}개 alias를 불러왔습니다. 정규화로 제외된 항목: {dropped}개",
            )
        except Exception as exc:
            QMessageBox.warning(self, "출처 Alias", f"JSON 불러오기에 실패했습니다.\n\n{exc}")

    def save(self) -> None:
        try:
            if not self.apply_form(silent=True):
                return
            aliases = normalize_publisher_aliases(self.aliases)
            self.save_callback(aliases)
            self.aliases = aliases
            self.refresh_alias_list(select_row=self.alias_list.currentRow())
            self.sync_editor()
            QMessageBox.information(self, "출처 Alias", f"Alias {len(aliases)}개를 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "출처 Alias", f"Alias 저장에 실패했습니다.\n\n{exc}")
