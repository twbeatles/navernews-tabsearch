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

class _BackupDialogCreateDeleteMixin:
    def _create_backup_legacy_unused(self):
        """백업 생성"""
        dialogs = get_dialog_adapter(self)
        include_db = self.chk_include_db.isChecked()
        ok, reason = self.auto_backup.validate_create_backup_prerequisites(include_db=include_db)
        if not ok:
            dialogs.warning(self, "백업 생성 실패", reason)
            return
        result = self.auto_backup.create_backup(include_db)

        if result:
            dialogs.information(self, "완료", f"백업이 생성되었습니다:\n{result}")
            self.load_backups()
        else:
            self.load_backups()
            dialogs.warning(self, "오류", "백업 생성에 실패했습니다.")

    def create_backup(self):
        """백업 생성"""
        dialogs = get_dialog_adapter(self)
        include_db = self.chk_include_db.isChecked()
        ok, reason = self.auto_backup.validate_create_backup_prerequisites(include_db=include_db)
        if not ok:
            dialogs.warning(self, "백업 생성 실패", reason)
            return

        result = self.auto_backup.create_backup(include_db)
        self.load_backups()
        if result:
            dialogs.information(self, "완료", f"백업이 생성되었습니다.\n{result}")
            return

        error_detail = str(getattr(self.auto_backup, "last_create_error", "") or "").strip()
        if error_detail:
            dialogs.warning(self, "오류", f"백업 생성에 실패했습니다.\n\n{error_detail}")
        else:
            dialogs.warning(self, "오류", "백업 생성에 실패했습니다.")

    def _handle_corrupt_backup(self, backup_name: str, corrupt_error: str) -> None:
        dialogs = get_dialog_adapter(self)
        if dialogs.ask_corrupt_backup_action(self, backup_name, corrupt_error) == "delete":
            deleted, error = self.auto_backup.delete_backup(backup_name)
            if deleted:
                self.load_backups()
                dialogs.information(self, "완료", "손상된 백업 항목을 삭제했습니다.")
            else:
                dialogs.warning(self, "오류", f"삭제 실패: {error}")

    def delete_corrupt_backups(self) -> None:
        """Delete every backup currently detected as corrupt."""
        dialogs = get_dialog_adapter(self)
        if not dialogs.ask_yes_no(
            self,
            "손상 백업 일괄 삭제",
            "손상된 백업 항목을 모두 삭제하시겠습니까?",
        ):
            return

        deleted_count, errors = self.auto_backup.delete_corrupt_backups()
        self.load_backups()
        if errors:
            preview = "\n".join(errors[:5])
            suffix = "\n..." if len(errors) > 5 else ""
            dialogs.warning(
                self,
                "손상 백업 삭제",
                f"{deleted_count:,}개를 삭제했지만 일부 항목 삭제에 실패했습니다.\n\n{preview}{suffix}",
            )
            return

        if deleted_count > 0:
            dialogs.information(self, "손상 백업 삭제", f"손상된 백업 {deleted_count:,}개를 삭제했습니다.")
        else:
            dialogs.information(self, "손상 백업 삭제", "삭제할 손상 백업이 없습니다.")

    def delete_backup(self):
        """백업 삭제"""
        dialogs = get_dialog_adapter(self)
        current_item = self.backup_list.currentItem()
        if not current_item:
            return

        item_meta = current_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_meta, dict):
            backup_name = str(item_meta.get("backup_name", "")).strip()
        else:
            backup_name = str(item_meta or "").strip()

        if not backup_name:
            dialogs.warning(self, "오류", "선택한 백업 정보를 읽을 수 없습니다.")
            return

        if dialogs.ask_yes_no(
            self,
            "백업 삭제",
            f"'{backup_name}' 백업을 삭제하시겠습니까?",
        ):
            deleted, error = self.auto_backup.delete_backup(backup_name)
            if deleted:
                self.load_backups()
            else:
                dialogs.warning(self, "오류", f"삭제 실패: {error}")

    def open_backup_folder(self):
        """백업 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.auto_backup.backup_dir))
