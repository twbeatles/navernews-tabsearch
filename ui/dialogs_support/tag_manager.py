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

__all__ = ["TagManagerDialog"]
