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

class _BackupDialogListingMixin:
    @staticmethod
    def format_backup_timestamp(timestamp: str, created_at: Optional[str] = None) -> str:
        raw_timestamp = str(timestamp or "").strip()
        for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
            try:
                dt = datetime.strptime(raw_timestamp, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

        raw_created_at = str(created_at or "").strip()
        if raw_created_at:
            try:
                dt = datetime.fromisoformat(raw_created_at)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        return raw_timestamp or "Unknown"

    def _backup_item_text(self, backup: Dict[str, Any]) -> str:
        timestamp = backup.get("timestamp", "Unknown")
        version = backup.get("app_version", "?")
        include_db_value = backup.get("include_db")
        resolved_include_db = backup.get("resolved_include_db")
        if isinstance(include_db_value, bool):
            include_db = "DB 포함" if include_db_value else "설정만"
        elif isinstance(resolved_include_db, bool):
            include_db = "DB 포함" if resolved_include_db else "설정만"
        else:
            include_db = "자동 판별"
        trigger_label = "자동" if str(backup.get("trigger", "manual")).lower() == "auto" else "수동"
        date_str = self.format_backup_timestamp(
            str(timestamp),
            created_at=str(backup.get("created_at", "")),
        )

        is_corrupt = bool(backup.get("is_corrupt", False))
        is_restorable = bool(backup.get("is_restorable", not is_corrupt))
        verification_state = str(backup.get("verification_state", "pending") or "pending").lower()
        restore_error = str(backup.get("restore_error", "") or "")
        verification_error = str(backup.get("verification_error", "") or "")

        if is_corrupt:
            item_text = f"[손상됨] {date_str} (v{version})"
            if verification_error:
                item_text += f" - {verification_error}"
            return item_text

        if verification_state == "pending":
            return f"[검증 전] {date_str} (v{version}) {include_db} {trigger_label}"

        if not is_restorable:
            item_text = f"[복원 불가] {date_str} (v{version}) {include_db} {trigger_label}"
            if restore_error:
                item_text += f" - {restore_error}"
            return item_text

        return f"{date_str} (v{version}) {include_db} {trigger_label} [정상]"

    def _backup_item_meta(self, backup: Dict[str, Any]) -> Dict[str, Any]:
        is_corrupt = bool(backup.get("is_corrupt", False))
        return {
            "name": str(backup.get("name", "") or backup.get("backup_name", "")),
            "backup_name": str(backup.get("name", "") or backup.get("backup_name", "")),
            "path": str(backup.get("path", "") or ""),
            "timestamp": str(backup.get("timestamp", "") or ""),
            "app_version": str(backup.get("app_version", "") or ""),
            "include_db": backup.get("include_db") if isinstance(backup.get("include_db"), bool) else None,
            "resolved_include_db": bool(backup.get("resolved_include_db", backup.get("include_db", False))),
            "trigger": str(backup.get("trigger", "manual")).lower(),
            "created_at": str(backup.get("created_at", "") or ""),
            "is_corrupt": is_corrupt,
            "error": str(backup.get("error", "") or ""),
            "is_restorable": bool(backup.get("is_restorable", not is_corrupt)),
            "restore_error": str(backup.get("restore_error", "") or ""),
            "verification_state": str(backup.get("verification_state", "pending") or "pending"),
            "verification_error": str(backup.get("verification_error", "") or ""),
            "last_verified_at": str(backup.get("last_verified_at", "") or ""),
        }

    def _apply_backup_item_state(self, item, backup: Dict[str, Any]):
        text_value = self._backup_item_text(backup)
        if hasattr(item, "setText"):
            item.setText(text_value)
        else:
            item.text = text_value
        item.setData(Qt.ItemDataRole.UserRole, self._backup_item_meta(backup))

    def _find_backup_item(self, backup_name: str):
        for index in range(self.backup_list.count()):
            item = self.backup_list.item(index)
            if item is None:
                continue
            meta = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(meta, dict) and str(meta.get("backup_name", "")).strip() == str(backup_name).strip():
                return item
        return None

    def load_backups(self):
        """백업 목록 로드"""
        if hasattr(self, "_stop_verify_worker"):
            self._stop_verify_worker(wait_ms=250)
        self.backup_list.clear()
        backups = self.auto_backup.get_backup_list()

        for backup in backups:
            item_text = self._backup_item_text(backup)
            self.backup_list.addItem(item_text)
            item = self.backup_list.item(self.backup_list.count() - 1)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole, self._backup_item_meta(backup))

        if not backups:
            if hasattr(self, "verify_progress"):
                self.verify_progress.setVisible(False)
            if hasattr(self, "lbl_verify_status"):
                self.lbl_verify_status.setText("검증할 백업이 없습니다.")
            if hasattr(self, "btn_verify"):
                self.btn_verify.setEnabled(False)
            if hasattr(self, "btn_cancel_verify"):
                self.btn_cancel_verify.setEnabled(False)
            return

        if hasattr(self, "btn_verify"):
            self.btn_verify.setEnabled(True)
        if hasattr(self, "btn_cancel_verify"):
            self.btn_cancel_verify.setEnabled(False)
        if hasattr(self, "lbl_verify_status"):
            self.lbl_verify_status.setText("백업 목록을 불러왔습니다. 필요 시 '백업 검증'을 실행하세요.")
