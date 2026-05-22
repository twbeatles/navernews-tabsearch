
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

from core.db_schema_support.types import IntegrityCheckResult
from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _NewsBackfillSchemaMixin:
    def is_news_fts_backfill_complete(self: DatabaseManager) -> bool:
        conn = self.get_connection()
        try:
            return self._get_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, "0") == "1"
        finally:
            self.return_connection(conn)

    def backfill_news_fts_chunk(self: DatabaseManager, limit: int = 250) -> dict[str, int | bool]:
        conn = self.get_connection()
        processed = 0
        done = False
        try:
            safe_limit = max(1, int(limit))
            with conn:
                last_rowid = int(self._get_app_meta(conn, self.FTS_BACKFILL_CURSOR_KEY, "0") or 0)
                rows = conn.execute(
                    """
                    SELECT rowid, title, description
                    FROM news
                    WHERE rowid > ?
                    ORDER BY rowid
                    LIMIT ?
                    """,
                    (last_rowid, safe_limit),
                ).fetchall()
                if not rows:
                    self._set_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, "1")
                    done = True
                    return {"processed": 0, "done": True}

                for row in rows:
                    news_rowid = int(row[0])
                    conn.execute("DELETE FROM news_fts WHERE rowid = ?", (news_rowid,))
                    conn.execute(
                        "INSERT INTO news_fts(rowid, title, description) VALUES (?, ?, ?)",
                        (news_rowid, str(row[1] or ""), str(row[2] or "")),
                    )
                    last_rowid = news_rowid
                    processed += 1

                self._set_app_meta(conn, self.FTS_BACKFILL_CURSOR_KEY, str(last_rowid))
                next_row = conn.execute(
                    "SELECT rowid FROM news WHERE rowid > ? ORDER BY rowid LIMIT 1",
                    (last_rowid,),
                ).fetchone()
                done = next_row is None
                if done:
                    self._set_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, "1")
        finally:
            self.return_connection(conn)
        return {"processed": processed, "done": done}

    def _backfill_missing_title_hashes(self: DatabaseManager, conn: sqlite3.Connection) -> int:
        total_updated = 0
        safe_chunk_size = max(1, int(self.TITLE_HASH_BACKFILL_CHUNK_SIZE))

        while True:
            rows = conn.execute(
                "SELECT link, title FROM news WHERE title_hash IS NULL LIMIT ?",
                (safe_chunk_size,),
            ).fetchall()
            if not rows:
                break

            updates = [
                (self._calculate_title_hash(str(title or "")), str(link or ""))
                for link, title in rows
                if str(link or "").strip()
            ]
            if not updates:
                break

            conn.executemany("UPDATE news SET title_hash = ? WHERE link = ?", updates)
            conn.commit()
            total_updated += len(updates)

        remaining = int(
            conn.execute("SELECT COUNT(*) FROM news WHERE title_hash IS NULL").fetchone()[0]
        )
        if remaining > 0:
            logger.warning("title_hash backfill incomplete: remaining=%s", remaining)
        elif total_updated > 0:
            logger.info("Backfilled title_hash for %s rows", total_updated)
        return total_updated

    def _backfill_missing_pubdate_ts(self: DatabaseManager, conn: sqlite3.Connection) -> int:
        total_updated = 0
        safe_chunk_size = max(1, int(self.PUBDATE_TS_BACKFILL_CHUNK_SIZE))

        while True:
            rows = conn.execute(
                "SELECT link, pubDate FROM news WHERE pubDate_ts IS NULL LIMIT ?",
                (safe_chunk_size,),
            ).fetchall()
            if not rows:
                break

            updates = [
                (parse_date_to_ts(str(pub_date or "")), str(link or ""))
                for link, pub_date in rows
                if str(link or "").strip()
            ]
            if not updates:
                break

            conn.executemany("UPDATE news SET pubDate_ts = ? WHERE link = ?", updates)
            conn.commit()
            total_updated += len(updates)

        remaining = int(
            conn.execute("SELECT COUNT(*) FROM news WHERE pubDate_ts IS NULL").fetchone()[0]
        )
        if remaining > 0:
            logger.warning("pubDate_ts backfill incomplete: remaining=%s", remaining)
        elif total_updated > 0:
            logger.info("Backfilled pubDate_ts for %s rows", total_updated)
        return total_updated
