import warnings

from core.database import (
    DatabaseConnectionError,
    DatabaseManager,
    DatabaseQueryError,
    DatabaseWriteError,
    NewsCountSummary,
    NewsUpsertResult,
)

warnings.warn(
    "Root database_manager imports are deprecated; use core.database instead.",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = [
    'DatabaseConnectionError',
    'DatabaseManager',
    'DatabaseQueryError',
    'DatabaseWriteError',
    'NewsCountSummary',
    'NewsUpsertResult',
]
