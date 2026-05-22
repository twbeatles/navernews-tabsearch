# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
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

def _verify_backups_job(context, auto_backup: AutoBackup, backup_entries: List[Dict[str, Any]]):
    total = len(backup_entries)
    verified_entries: List[Dict[str, Any]] = []
    context.report(current=0, total=total, message="백업 검증 준비 중...", payload={"stage": "start"})

    for index, entry in enumerate(backup_entries, start=1):
        context.check_cancelled()
        backup_name = str(entry.get("backup_name") or entry.get("name") or "").strip()
        verified_entry = auto_backup.verify_backup_entry(entry, persist=True)
        verified_entry["backup_name"] = backup_name
        verified_entries.append(verified_entry)
        context.report(
            current=index,
            total=total,
            message=f"백업 검증 중... ({index}/{total})",
            payload={"stage": "verified", "entry": verified_entry},
        )

    return verified_entries
class _BackupDialogVerificationMixin:
    def start_backup_verification(self):
        if self._verify_worker is not None and self._verify_worker.isRunning():
            return

        backup_entries: List[Dict[str, Any]] = []
        for index in range(self.backup_list.count()):
            item = self.backup_list.item(index)
            if item is None:
                continue
            meta = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(meta, dict):
                backup_entries.append(dict(meta))

        if not backup_entries:
            self.verify_progress.setVisible(False)
            self.lbl_verify_status.setText("검증할 백업이 없습니다.")
            return

        self.verify_progress.setVisible(True)
        self.verify_progress.setRange(0, len(backup_entries))
        self.verify_progress.setValue(0)
        self.lbl_verify_status.setText("백업 검증을 시작합니다...")
        self.btn_verify.setEnabled(False)
        self.btn_cancel_verify.setEnabled(True)

        worker = IterativeJobWorker(_verify_backups_job, self.auto_backup, backup_entries)
        self._verify_worker = worker
        worker.progress.connect(self._on_backup_verification_progress)
        worker.finished.connect(self._on_backup_verification_finished)
        worker.error.connect(self._on_backup_verification_error)
        worker.cancelled.connect(self._on_backup_verification_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()

    def cancel_backup_verification(self):
        if self._verify_worker is None or not self._verify_worker.isRunning():
            return
        self.btn_cancel_verify.setEnabled(False)
        self.lbl_verify_status.setText("백업 검증 취소 요청 중...")
        self._verify_worker.requestInterruption()

    def _on_backup_verification_progress(self, payload: Dict[str, Any]):
        current = int(payload.get("current", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        message = str(payload.get("message", "") or "")
        if total > 0:
            self.verify_progress.setRange(0, total)
            self.verify_progress.setValue(min(current, total))
        if message:
            self.lbl_verify_status.setText(message)

        entry = payload.get("entry")
        if isinstance(entry, dict):
            item = self._find_backup_item(str(entry.get("backup_name", "") or entry.get("name", "")))
            if item is not None:
                self._apply_backup_item_state(item, entry)

    def _finish_backup_verification_ui(self, message: str):
        self._verify_worker = None
        if hasattr(self, "btn_verify"):
            self.btn_verify.setEnabled(self.backup_list.count() > 0)
        if hasattr(self, "btn_cancel_verify"):
            self.btn_cancel_verify.setEnabled(False)
        if hasattr(self, "verify_progress"):
            self.verify_progress.setVisible(self.backup_list.count() > 0)
        if hasattr(self, "lbl_verify_status"):
            self.lbl_verify_status.setText(message)

    def _on_backup_verification_finished(self, result: List[Dict[str, Any]]):
        for entry in result:
            item = self._find_backup_item(str(entry.get("backup_name", "") or entry.get("name", "")))
            if item is not None:
                self._apply_backup_item_state(item, entry)

        ok_count = sum(1 for entry in result if bool(entry.get("is_restorable")) and not bool(entry.get("is_corrupt")))
        failed_count = max(0, len(result) - ok_count)
        self._finish_backup_verification_ui(
            f"백업 검증 완료: 정상 {ok_count}개 / 문제 {failed_count}개"
        )

    def _on_backup_verification_error(self, error_msg: str):
        self._finish_backup_verification_ui(f"백업 검증 실패: {error_msg}")
        get_dialog_adapter(self).warning(
            self,
            "백업 검증",
            f"백업 검증 중 오류가 발생했습니다:\n{error_msg}",
        )

    def _on_backup_verification_cancelled(self):
        self._finish_backup_verification_ui("백업 검증을 취소했습니다.")

__all__ = ['_BackupDialogVerificationMixin', '_verify_backups_job']
