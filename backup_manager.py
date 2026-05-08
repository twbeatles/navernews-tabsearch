import warnings

warnings.warn(
    "Root backup_manager imports are deprecated; use core.backup instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.backup import AutoBackup, PENDING_RESTORE_FILENAME, apply_pending_restore_if_any

__all__ = ['AutoBackup', 'PENDING_RESTORE_FILENAME', 'apply_pending_restore_if_any']
