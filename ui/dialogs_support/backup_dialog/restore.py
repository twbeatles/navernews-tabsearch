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

class _BackupDialogRestoreMixin:
    def _sqlite_table_count(self, db_path: str, table_name: str) -> Optional[int]:
        if not db_path or not os.path.exists(db_path):
            return None
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                return 0
            row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            logger.warning("dry-run table count failed (%s.%s): %s", db_path, table_name, exc)
            return None
        finally:
            if conn is not None:
                conn.close()

    def _build_restore_dry_run_report(
        self,
        backup_name: str,
        *,
        restore_db: bool,
        verified_item: Dict[str, Any],
    ) -> str:
        backup_path = os.path.join(self.auto_backup.backup_dir, backup_name)
        cfg_name = os.path.basename(getattr(self.auto_backup, "config_file", "news_scraper_config.json"))
        live_cfg_path = getattr(self.auto_backup, "config_file", "")
        backup_cfg_path = os.path.join(backup_path, cfg_name)

        config_summary = "설정 파일: 확인 불가"
        try:
            live_cfg = {}
            backup_cfg = {}
            if os.path.exists(live_cfg_path):
                with open(live_cfg_path, "r", encoding="utf-8") as f:
                    live_cfg = json.load(f)
            if os.path.exists(backup_cfg_path):
                with open(backup_cfg_path, "r", encoding="utf-8") as f:
                    backup_cfg = json.load(f)
            live_settings = live_cfg.get("app_settings", {}) if isinstance(live_cfg, dict) else {}
            backup_settings = backup_cfg.get("app_settings", {}) if isinstance(backup_cfg, dict) else {}
            changed_keys = sorted(
                key
                for key in set(live_settings.keys()) | set(backup_settings.keys())
                if live_settings.get(key) != backup_settings.get(key)
            )
            if changed_keys:
                preview = ", ".join(changed_keys[:6])
                suffix = "..." if len(changed_keys) > 6 else ""
                config_summary = f"설정 변경: {len(changed_keys)}개 항목 ({preview}{suffix})"
            else:
                config_summary = "설정 변경: 없음"
        except Exception as exc:
            config_summary = f"설정 파일: 비교 실패 ({exc})"

        db_summary = "데이터베이스: 변경 없음"
        if restore_db:
            db_name = os.path.basename(getattr(self.auto_backup, "db_file", "news_database.db"))
            live_db_path = getattr(self.auto_backup, "db_file", "")
            backup_db_path = os.path.join(backup_path, db_name)
            live_news = self._sqlite_table_count(live_db_path, "news")
            backup_news = self._sqlite_table_count(backup_db_path, "news")
            live_tags = self._sqlite_table_count(live_db_path, "news_tags")
            backup_tags = self._sqlite_table_count(backup_db_path, "news_tags")
            db_summary = (
                "데이터베이스: 복원 예정\n"
                f"현재 기사/태그: {live_news if live_news is not None else '?'} / {live_tags if live_tags is not None else '?'}\n"
                f"백업 기사/태그: {backup_news if backup_news is not None else '?'} / {backup_tags if backup_tags is not None else '?'}"
            )

        verification_state = str(verified_item.get("verification_state", "pending") or "pending")
        verification_error = str(verified_item.get("verification_error", "") or "")
        verification_summary = f"검증 상태: {verification_state}"
        if verification_error:
            verification_summary += f" ({verification_error})"

        return f"{config_summary}\n{db_summary}\n{verification_summary}"

    def restore_backup(self):
        """백업 복원 예약 (재시작 시 적용)"""
        dialogs = get_dialog_adapter(self)
        current_item = self.backup_list.currentItem()
        if not current_item:
            dialogs.information(self, "알림", "복원할 백업을 선택하세요.")
            return

        item_meta = current_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_meta, dict):
            backup_name = str(item_meta.get("backup_name", "")).strip()
            include_db_meta = item_meta.get("include_db")
            is_corrupt = bool(item_meta.get("is_corrupt", False))
            corrupt_error = str(item_meta.get("error", "") or "")
            is_restorable = bool(item_meta.get("is_restorable", True))
            restore_error = str(item_meta.get("restore_error", "") or "")
        else:
            backup_name = str(item_meta or "").strip()
            include_db_meta = None
            is_corrupt = False
            corrupt_error = ""
            is_restorable = True
            restore_error = ""

        if not backup_name:
            dialogs.warning(self, "오류", "선택한 백업 정보를 읽을 수 없습니다.")
            return

        if is_corrupt:
            self._handle_corrupt_backup(backup_name, corrupt_error)
            return

        if not is_restorable:
            dialogs.warning(
                self,
                "복원 불가",
                restore_error or "선택한 백업은 필요한 파일이 없어 복원할 수 없습니다.",
            )
            return

        if isinstance(include_db_meta, bool):
            restore_db = include_db_meta
        else:
            db_name = os.path.basename(getattr(self.auto_backup, "db_file", "news_database.db"))
            db_backup_path = os.path.join(self.auto_backup.backup_dir, backup_name, db_name)
            restore_db = os.path.exists(db_backup_path)

        verified_item = self.auto_backup.verify_backup_by_name(
            backup_name,
            require_db=restore_db,
            persist=True,
        )
        self._apply_backup_item_state(current_item, verified_item)
        if bool(verified_item.get("is_corrupt", False)):
            self._handle_corrupt_backup(backup_name, str(verified_item.get("error", "") or ""))
            return
        if not bool(verified_item.get("is_restorable", False)):
            dialogs.warning(
                self,
                "복원 불가",
                str(verified_item.get("restore_error", "") or "선택한 백업은 복원할 수 없습니다."),
            )
            return

        restore_scope = "설정 + 데이터베이스" if restore_db else "설정만"
        restore_notice = (
            "주의: 현재 설정과 데이터가 덮어써집니다."
            if restore_db
            else "주의: 현재 설정만 덮어써집니다. 데이터베이스는 변경되지 않습니다."
        )
        dry_run_builder = getattr(self, "_build_restore_dry_run_report", None)
        dry_run_report = (
            dry_run_builder(backup_name, restore_db=restore_db, verified_item=verified_item)
            if callable(dry_run_builder)
            else ""
        )
        dry_run_block = f"{dry_run_report}\n\n" if dry_run_report else ""

        if dialogs.ask_yes_no(
            self,
            "백업 복원",
            f"'{backup_name}' 백업을 복원하시겠습니까?\n\n"
            f"복원 범위: {restore_scope}\n"
            f"{dry_run_block}"
            f"{restore_notice}\n"
            "복원은 프로그램을 재시작해야 적용됩니다.",
        ):
            safeguard = self.auto_backup.create_backup(include_db=restore_db, trigger="manual")
            if safeguard is None:
                if not dialogs.ask_yes_no(
                    self,
                    "보호 백업 실패",
                    "현재 상태의 보호 백업 생성에 실패했습니다.\n"
                    "백업 없이 복원을 계속 진행하시겠습니까?",
                ):
                    return
            if self.auto_backup.schedule_restore(backup_name, restore_db=restore_db):
                dialogs.information(
                    self,
                    "완료",
                    "복원을 예약했습니다.\n프로그램을 재시작하면 백업이 적용됩니다.",
                )
            else:
                dialogs.warning(self, "오류", "백업 복원 예약에 실패했습니다.")
