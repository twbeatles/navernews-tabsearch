
# pyright: reportGeneralTypeIssues=false
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from typing import TYPE_CHECKING, Any, Dict, List, Set

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _CloudSyncRollbackMixin:
    def _create_cloud_merge_rollback_backup(self: DatabaseManager, conn: sqlite3.Connection) -> str:
        db_dir = os.path.dirname(os.path.abspath(self.db_file)) or "."
        os.makedirs(db_dir, exist_ok=True)
        fd, backup_path = tempfile.mkstemp(
            prefix=".cloud_merge_rollback_",
            suffix=".db",
            dir=db_dir,
        )
        os.close(fd)
        dst_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
        return backup_path

    def _restore_cloud_merge_rollback_backup(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        backup_path: str,
    ) -> None:
        if not backup_path or not os.path.exists(backup_path):
            return
        src_conn = sqlite3.connect(backup_path)
        try:
            src_conn.backup(conn)
            conn.commit()
        finally:
            src_conn.close()
