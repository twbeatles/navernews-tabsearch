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

class _BackupDialogUISetupMixin:
    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 백업 생성 버튼
        btn_layout = QHBoxLayout()

        self.btn_create = QPushButton("📦 새 백업 생성")
        self.btn_create.clicked.connect(self.create_backup)

        self.chk_include_db = QCheckBox("데이터베이스 포함")
        self.chk_include_db.setChecked(True)

        btn_layout.addWidget(self.btn_create)
        btn_layout.addWidget(self.chk_include_db)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        info_label = QLabel(
            "참고: 시작 시 자동 백업은 설정만 저장합니다. DB 복원 지점이 필요하면 수동 백업에서 "
            "'데이터베이스 포함'을 선택하세요."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(info_label)

        verify_layout = QHBoxLayout()
        self.btn_verify = QPushButton("🔍 백업 검증")
        self.btn_verify.clicked.connect(self.start_backup_verification)
        self.btn_cancel_verify = QPushButton("⏹ 검증 취소")
        self.btn_cancel_verify.setEnabled(False)
        self.btn_cancel_verify.clicked.connect(self.cancel_backup_verification)
        self.btn_delete_corrupt = QPushButton("손상 백업 일괄 삭제")
        self.btn_delete_corrupt.clicked.connect(self.delete_corrupt_backups)
        verify_layout.addWidget(self.btn_verify)
        verify_layout.addWidget(self.btn_cancel_verify)
        verify_layout.addWidget(self.btn_delete_corrupt)
        verify_layout.addStretch()
        layout.addLayout(verify_layout)

        self.verify_progress = QProgressBar()
        self.verify_progress.setVisible(False)
        layout.addWidget(self.verify_progress)

        self.lbl_verify_status = QLabel("백업 목록을 불러오는 중...")
        self.lbl_verify_status.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_verify_status)

        # 백업 목록
        layout.addWidget(QLabel("📁 백업 목록:"))
        self.backup_list = QListWidget()
        self.backup_list.itemDoubleClicked.connect(self.restore_backup)
        layout.addWidget(self.backup_list)

        # 하단 버튼
        bottom_layout = QHBoxLayout()

        self.btn_restore = QPushButton("♻ 복원")
        self.btn_restore.clicked.connect(self.restore_backup)

        self.btn_delete = QPushButton("🗑 삭제")
        self.btn_delete.clicked.connect(self.delete_backup)

        self.btn_open_folder = QPushButton("📂 폴더 열기")
        self.btn_open_folder.clicked.connect(self.open_backup_folder)

        bottom_layout.addWidget(self.btn_restore)
        bottom_layout.addWidget(self.btn_delete)
        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def closeEvent(self, event: Optional[QCloseEvent]):
        self._stop_verify_worker(wait_ms=600)
        super().closeEvent(event)

    def _stop_verify_worker(self, wait_ms: int = 200):
        worker = getattr(self, "_verify_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            try:
                worker.requestInterruption()
                if not worker.wait(max(0, int(wait_ms))):
                    retain_worker_until_finished(worker)
            except Exception:
                pass
        self._verify_worker = None
