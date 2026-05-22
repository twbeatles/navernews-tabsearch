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

__all__ = ["AutomationRulesDialog"]
