import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
)

from core.backup import AutoBackup
from core.logging_setup import configure_logging
from core.workers import IterativeJobWorker
from ui.dialogs_support.backup_dialog.create_delete import (
    _BackupDialogCreateDeleteMixin,
)
from ui.dialogs_support.backup_dialog.listing import _BackupDialogListingMixin
from ui.dialogs_support.backup_dialog.restore import _BackupDialogRestoreMixin
from ui.dialogs_support.backup_dialog.ui_setup import _BackupDialogUISetupMixin
from ui.dialogs_support.backup_dialog.verification import _BackupDialogVerificationMixin

configure_logging()


logger = logging.getLogger(__name__)


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
        self.setWindowTitle("백업 관리")
        self.resize(500, 400)
        self.auto_backup = auto_backup
        self._verify_worker: Optional[IterativeJobWorker] = None
        self.setup_ui()
        self.load_backups()


__all__ = ["BackupDialog"]
