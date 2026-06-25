
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

from core.db_schema_support.types import IntegrityCheckResult
from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _DatabaseConnectionSchemaMixin:
    def _create_connection(self: DatabaseManager):
        """Create a pooled SQLite connection."""
        conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _news_column_names(self: DatabaseManager, conn: sqlite3.Connection) -> set[str]:
        return {str(row[1]) for row in conn.execute("PRAGMA table_info(news)").fetchall()}

    def _ensure_news_column(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        existing_columns: set[str],
        column_name: str,
        column_type: str,
    ) -> None:
        if column_name in existing_columns:
            return
        conn.execute(f"ALTER TABLE news ADD COLUMN {column_name} {column_type}")
        existing_columns.add(column_name)
        logger.info("Added news.%s column", column_name)

    def _check_integrity_with_retry(
        self: DatabaseManager,
        *,
        attempts: int = 3,
        base_delay_sec: float = 0.2,
    ) -> IntegrityCheckResult:
        """Retry unreadable integrity checks before giving up."""
        safe_attempts = max(1, int(attempts))
        last_result = IntegrityCheckResult("unreadable", "")
        for attempt in range(safe_attempts):
            last_result = self._check_integrity()
            if last_result.state != "unreadable":
                return last_result
            if attempt < safe_attempts - 1:
                time.sleep(base_delay_sec * (attempt + 1))
        return last_result

    def _check_integrity(self: DatabaseManager) -> IntegrityCheckResult:
        """Run PRAGMA integrity_check before using an existing DB."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_file, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result and str(result[0]).lower() == "ok":
                return IntegrityCheckResult("ok", "")
            detail = str(result[0]) if result and result[0] is not None else "unknown"
            logger.error("DB integrity check confirmed corruption: %s", detail)
            return IntegrityCheckResult("corrupt", detail)
        except (sqlite3.Error, OSError) as e:
            logger.error("DB integrity check could not read database: %s", e)
            return IntegrityCheckResult("unreadable", str(e))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _move_db_artifact(self: DatabaseManager, src_path: str, dst_path: str) -> bool:
        try:
            os.replace(src_path, dst_path)
            return True
        except OSError:
            try:
                shutil.copy2(src_path, dst_path)
                os.remove(src_path)
                return True
            except OSError as copy_error:
                logger.warning("DB artifact preserve failed: %s -> %s (%s)", src_path, dst_path, copy_error)
                return False

    def _recover_database(self: DatabaseManager):
        """Move a corrupt database aside before recreating it."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_dir = os.path.dirname(os.path.abspath(self.db_file)) or "."
            db_name = os.path.basename(self.db_file)
            corrupt_dir = os.path.join(db_dir, f"{db_name}.corrupt_{timestamp}")
            os.makedirs(corrupt_dir, exist_ok=True)

            preserved_paths = []
            for suffix in ("", "-wal", "-shm"):
                src_path = f"{self.db_file}{suffix}"
                if not os.path.exists(src_path):
                    continue
                dst_path = os.path.join(corrupt_dir, os.path.basename(src_path))
                if self._move_db_artifact(src_path, dst_path):
                    preserved_paths.append(dst_path)

            if preserved_paths:
                logger.info("Corrupt DB set preserved in %s", corrupt_dir)
            else:
                logger.warning("DB recovery started but there was no DB file set to preserve: %s", self.db_file)
        except Exception as e:
            logger.critical("DB recovery failed: %s", e)
