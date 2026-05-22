
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


class _CloudSyncMetadataMixin:
    CLOUD_SYNC_SEEN_META_KEY = "cloud_sync.seen_snapshot_ids"
    CLOUD_SYNC_MAX_SEEN_IDS = 300

    def _table_exists(self: DatabaseManager, conn: sqlite3.Connection, schema: str, table: str) -> bool:
        row = conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_columns(self: DatabaseManager, conn: sqlite3.Connection, schema: str, table: str) -> Set[str]:
        if not self._table_exists(conn, schema, table):
            return set()
        rows = conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
        return {str(row[1]) for row in rows}

    def _source_expr(
        self: DatabaseManager,
        columns: Set[str],
        alias: str,
        column: str,
        default_sql: str,
    ) -> str:
        if column in columns:
            return f"COALESCE({alias}.{column}, {default_sql})"
        return default_sql

    def get_cloud_sync_seen_snapshot_ids(self: DatabaseManager) -> Set[str]:
        conn = self.get_connection()
        try:
            raw = self._get_app_meta(conn, self.CLOUD_SYNC_SEEN_META_KEY, "[]")
            try:
                payload = json.loads(raw)
            except Exception:
                return set()
            if not isinstance(payload, list):
                return set()
            return {str(item) for item in payload if isinstance(item, str) and item.strip()}
        except Exception as e:
            logger.warning("Failed to load cloud sync seen snapshots: %s", e)
            return set()
        finally:
            self.return_connection(conn)

    def mark_cloud_sync_snapshot_seen(self: DatabaseManager, snapshot_id: str) -> None:
        normalized = str(snapshot_id or "").strip()
        if not normalized:
            return
        conn = self.get_connection()
        try:
            with conn:
                raw = self._get_app_meta(conn, self.CLOUD_SYNC_SEEN_META_KEY, "[]")
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = []
                seen: List[str] = [
                    str(item)
                    for item in (payload if isinstance(payload, list) else [])
                    if isinstance(item, str) and item.strip()
                ]
                if normalized in seen:
                    seen.remove(normalized)
                seen.insert(0, normalized)
                seen = seen[: self.CLOUD_SYNC_MAX_SEEN_IDS]
                self._set_app_meta(
                    conn,
                    self.CLOUD_SYNC_SEEN_META_KEY,
                    json.dumps(seen, ensure_ascii=False),
                )
        finally:
            self.return_connection(conn)
