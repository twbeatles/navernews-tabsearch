"""Compatibility facade for backup and restore APIs.

The implementation is split under ``core.backup_support`` while this module
keeps existing imports and test patch points available.
"""

import datetime
import json
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
import traceback
from typing import Any, Dict, List, Optional

from core.backup_support import (
    AutoBackup,
    PENDING_RESTORE_FILENAME,
    _apply_restore_from_backup,
    _apply_restore_sidecars,
    _atomic_copy_replace,
    _cleanup_restore_stage_dir,
    _retry_remove_readonly,
    _rollback_files_from_snapshot,
    _rmtree_force,
    _snapshot_files_for_rollback,
    _validate_config_backup_payload,
    _validate_restore_sources,
    _validate_sidecar_policy,
    _validate_sqlite_backup,
    _write_json_atomic,
    apply_pending_restore_if_any,
    cleanup_applied_pending_restore_files,
    verify_backup_payload,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AutoBackup",
    "PENDING_RESTORE_FILENAME",
    "apply_pending_restore_if_any",
    "cleanup_applied_pending_restore_files",
    "verify_backup_payload",
    "_atomic_copy_replace",
]
