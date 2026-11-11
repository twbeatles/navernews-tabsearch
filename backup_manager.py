import warnings

from core.backup import (
    PENDING_RESTORE_FILENAME,
    AutoBackup,
    apply_pending_restore_if_any,
)

warnings.warn(
    "Root backup_manager imports are deprecated; use core.backup instead.",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ['AutoBackup', 'PENDING_RESTORE_FILENAME', 'apply_pending_restore_if_any']
