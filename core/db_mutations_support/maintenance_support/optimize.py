
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple, cast

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _NewsOptimizeMaintenanceMixin:
    def optimize_database(self: DatabaseManager, vacuum: bool = False) -> bool:
        """Run lightweight SQLite optimization and optional VACUUM maintenance."""
        conn = self.get_connection()
        try:
            conn.execute("PRAGMA optimize")
            if bool(vacuum):
                conn.execute("VACUUM")
            return True
        except sqlite3.Error as e:
            logger.error("optimize_database failed: %s", e)
            raise self._new_write_error("optimize_database", e) from e
        finally:
            self.return_connection(conn)
