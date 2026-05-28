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

from ui.dialogs_support.backup_dialog.create_delete import _BackupDialogCreateDeleteMixin
from ui.dialogs_support.backup_dialog.listing import _BackupDialogListingMixin
from ui.dialogs_support.backup_dialog.restore import _BackupDialogRestoreMixin
from ui.dialogs_support.backup_dialog.ui_setup import _BackupDialogUISetupMixin
from ui.dialogs_support.backup_dialog.verification import _BackupDialogVerificationMixin


class BackupDialog(
    _BackupDialogListingMixin,
    _BackupDialogUISetupMixin,
    _BackupDialogVerificationMixin,
    _BackupDialogCreateDeleteMixin,
    _BackupDialogRestoreMixin,
    QDialog,
):
    def __init__(self, auto_backup: AutoBackup, parent=None):
        super().__init__(parent)
        self.setWindowTitle("💾 백업 관리")
        self.resize(500, 400)
        self.auto_backup = auto_backup
        self._verify_worker: Optional[IterativeJobWorker] = None
        self.setup_ui()
        self.load_backups()

__all__ = ["BackupDialog"]
