from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from core.backup_support.auto_backup_support.create import _AutoBackupCreateMixin
from core.backup_support.auto_backup_support.listing import _AutoBackupListingMixin
from core.backup_support.auto_backup_support.metadata import _AutoBackupMetadataMixin
from core.backup_support.auto_backup_support.restore_delete import (
    _AutoBackupRestoreDeleteMixin,
)
from core.backup_support.constants import DEFAULT_BACKUP_DIR, PENDING_RESTORE_FILENAME

logger = logging.getLogger(__name__)


class AutoBackup(
    _AutoBackupMetadataMixin,
    _AutoBackupCreateMixin,
    _AutoBackupListingMixin,
    _AutoBackupRestoreDeleteMixin,
):
    """?? ? ?????? ?? ??"""

    BACKUP_DIR: str = DEFAULT_BACKUP_DIR
    MAX_AUTO_BACKUPS: int = 5
    MAX_MANUAL_BACKUPS: int = 20
    MAX_FAILED_BACKUPS: int = 5

    def __init__(
        self,
        config_file: str,
        db_file: str,
        app_version: str = "unknown",
        pending_restore_file: Optional[str] = None,
    ):
        self.config_file = config_file
        self.db_file = db_file
        self.app_version = app_version
        self.backup_dir = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), self.BACKUP_DIR
        )
        self.pending_restore_file = pending_restore_file or os.path.join(
            os.path.dirname(os.path.abspath(config_file)), PENDING_RESTORE_FILENAME
        )
        self.last_create_error = ""
        self._create_lock = threading.Lock()
        self._ensure_backup_dir()


__all__ = ["AutoBackup"]
