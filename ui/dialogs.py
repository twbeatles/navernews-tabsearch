"""Compatibility facade for auxiliary dialogs."""

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
from ui.dialogs_support import (
    ArchiveSearchDialog,
    AutomationRulesDialog,
    BackupDialog,
    KeywordGroupDialog,
    LogViewerDialog,
    NoteDialog,
    PublisherAliasDialog,
    TagManagerDialog,
    _verify_backups_job,
)

configure_logging()
logger = logging.getLogger(__name__)

__all__ = [
    "ArchiveSearchDialog",
    "AutomationRulesDialog",
    "BackupDialog",
    "KeywordGroupDialog",
    "LogViewerDialog",
    "NoteDialog",
    "PublisherAliasDialog",
    "TagManagerDialog",
    "_verify_backups_job",
]
