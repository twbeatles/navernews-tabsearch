
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


class _NewsKeywordSchemaMixin:
    def _create_news_keywords_table(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_keywords (
                link TEXT NOT NULL,
                keyword TEXT NOT NULL,
                query_key TEXT NOT NULL,
                is_duplicate INTEGER DEFAULT 0,
                PRIMARY KEY (link, query_key),
                FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
            )
            """
        )

    def _news_keywords_needs_rebuild(self: DatabaseManager, conn: sqlite3.Connection) -> bool:
        rows = conn.execute("PRAGMA table_info(news_keywords)").fetchall()
        if not rows:
            return False

        columns = {str(row[1]): row for row in rows}
        required = {"link", "keyword", "query_key", "is_duplicate"}
        if not required.issubset(columns.keys()):
            return True

        pk_order = {name: int(row[5]) for name, row in columns.items()}
        return pk_order.get("link") != 1 or pk_order.get("query_key") != 2

    def _legacy_query_key_for_keyword(self: DatabaseManager, keyword: str) -> str:
        return build_fetch_key(str(keyword or "").strip(), [])

    def _rebuild_news_keywords_table(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        logger.info("Migrating news_keywords to query_key-aware schema")
        conn.execute(
            """
            CREATE TABLE news_keywords_new (
                link TEXT NOT NULL,
                keyword TEXT NOT NULL,
                query_key TEXT NOT NULL,
                is_duplicate INTEGER DEFAULT 0,
                PRIMARY KEY (link, query_key),
                FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
            )
            """
        )

        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(news_keywords)").fetchall()
        }
        if "query_key" in columns:
            rows = conn.execute(
                """
                SELECT link, keyword, query_key, COALESCE(is_duplicate, 0)
                FROM news_keywords
                """
            ).fetchall()
            insert_rows = [
                (
                    str(row[0] or ""),
                    str(row[1] or "").strip(),
                    str(row[2] or "").strip(),
                    int(row[3] or 0),
                )
                for row in rows
                if str(row[0] or "").strip()
                and str(row[1] or "").strip()
                and str(row[2] or "").strip()
            ]
        else:
            rows = conn.execute(
                """
                SELECT link, keyword, COALESCE(is_duplicate, 0)
                FROM news_keywords
                """
            ).fetchall()
            insert_rows = [
                (
                    str(row[0] or ""),
                    str(row[1] or "").strip(),
                    self._legacy_query_key_for_keyword(str(row[1] or "")),
                    int(row[2] or 0),
                )
                for row in rows
                if str(row[0] or "").strip() and str(row[1] or "").strip()
            ]

        if insert_rows:
            conn.executemany(
                """
                INSERT OR IGNORE INTO news_keywords_new (link, keyword, query_key, is_duplicate)
                VALUES (?, ?, ?, ?)
                """,
                insert_rows,
            )

        conn.execute("DROP TABLE news_keywords")
        conn.execute("ALTER TABLE news_keywords_new RENAME TO news_keywords")

    def _ensure_news_keywords_schema(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        has_table = bool(
            conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type='table' AND name='news_keywords'
                """
            ).fetchone()
        )
        if not has_table:
            self._create_news_keywords_table(conn)
            return

        if self._news_keywords_needs_rebuild(conn):
            self._rebuild_news_keywords_table(conn)
