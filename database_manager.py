import warnings

warnings.warn(
    "Root database_manager imports are deprecated; use core.database instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.database import (
    DatabaseManager,
    DatabaseQueryError,
    DatabaseWriteError,
    NewsCountSummary,
    NewsUpsertResult,
)

__all__ = [
    'DatabaseManager',
    'DatabaseQueryError',
    'DatabaseWriteError',
    'NewsCountSummary',
    'NewsUpsertResult',
]
