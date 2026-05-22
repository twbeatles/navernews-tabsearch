
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


class _DatabaseInitSchemaMixin:
    def init_db(self: DatabaseManager):
        """Initialize tables, migrations, and indexes."""
        conn = sqlite3.connect(self.db_file)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news (
                    link TEXT PRIMARY KEY,
                    keyword TEXT,
                    title TEXT,
                    description TEXT,
                    pubDate TEXT,
                    publisher TEXT,
                    is_read INTEGER DEFAULT 0,
                    is_bookmarked INTEGER DEFAULT 0,
                    pubDate_ts REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    notes TEXT,
                    title_hash TEXT,
                    is_duplicate INTEGER DEFAULT 0
                )
                """
            )
            self._ensure_news_keywords_schema(conn)
            self._ensure_news_tags_schema(conn)
            self._ensure_news_tag_state_schema(conn)
            self._ensure_app_meta_table(conn)
            self._ensure_news_fts_schema(conn)

            existing_columns = self._news_column_names(conn)
            columns_before_migration = set(existing_columns)
            for col, dtype in [
                ("pubDate_ts", "REAL"),
                ("publisher", "TEXT"),
                ("is_read", "INTEGER DEFAULT 0"),
                ("is_bookmarked", "INTEGER DEFAULT 0"),
                ("created_at", "REAL DEFAULT (strftime('%s', 'now'))"),
                ("notes", "TEXT"),
                ("title_hash", "TEXT"),
                ("is_duplicate", "INTEGER DEFAULT 0"),
                ("read_updated_at", "REAL DEFAULT 0"),
                ("bookmark_updated_at", "REAL DEFAULT 0"),
                ("notes_updated_at", "REAL DEFAULT 0"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("delete_updated_at", "REAL DEFAULT 0"),
                ("delete_machine_id", "TEXT DEFAULT ''"),
                ("delete_reason", "TEXT DEFAULT ''"),
            ]:
                self._ensure_news_column(conn, existing_columns, col, dtype)

            state_timestamp_added = any(
                column not in columns_before_migration
                for column in (
                    "read_updated_at",
                    "bookmark_updated_at",
                    "notes_updated_at",
                )
            )
            if state_timestamp_added:
                now_ts = datetime.now().timestamp()
                conn.execute(
                    "UPDATE news SET read_updated_at = ? "
                    "WHERE COALESCE(is_read, 0) != 0 AND COALESCE(read_updated_at, 0) = 0",
                    (now_ts,),
                )
                conn.execute(
                    "UPDATE news SET bookmark_updated_at = ? "
                    "WHERE COALESCE(is_bookmarked, 0) != 0 AND COALESCE(bookmark_updated_at, 0) = 0",
                    (now_ts,),
                )
                conn.execute(
                    "UPDATE news SET notes_updated_at = ? "
                    "WHERE COALESCE(notes, '') != '' AND COALESCE(notes_updated_at, 0) = 0",
                    (now_ts,),
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO news_tag_state(link, tags_updated_at)
                SELECT DISTINCT link, ?
                FROM news_tags
                WHERE link IS NOT NULL AND link != ''
                """,
                (datetime.now().timestamp(),),
            )

            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)",
                "CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)",
                "CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)",
                "CREATE INDEX IF NOT EXISTS idx_read_ts ON news(is_read, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_title_hash ON news(title_hash)",
                "CREATE INDEX IF NOT EXISTS idx_duplicate ON news(is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_deleted ON news(is_deleted)",
                "CREATE INDEX IF NOT EXISTS idx_deleted_ts ON news(is_deleted, delete_updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_read ON news(keyword, is_read)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_ts ON news(keyword, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_dup ON news(keyword, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked_ts ON news(is_bookmarked, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked_read_ts ON news(is_bookmarked, is_read, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword ON news_keywords(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_nk_query_key ON news_keywords(query_key)",
                "CREATE INDEX IF NOT EXISTS idx_nk_link ON news_keywords(link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_link ON news_keywords(keyword, link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_query_key_keyword ON news_keywords(query_key, keyword)",
                "CREATE INDEX IF NOT EXISTS idx_nk_query_key_link ON news_keywords(query_key, link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_dup ON news_keywords(keyword, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_nk_query_key_dup ON news_keywords(query_key, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_nk_query_key_keyword_dup ON news_keywords(query_key, keyword, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_news_tags_tag ON news_tags(tag)",
                "CREATE INDEX IF NOT EXISTS idx_news_tags_link ON news_tags(link)",
            ]
            for idx in indexes:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError as e:
                    logger.debug("Index creation skipped: %s", e)

            self._backfill_missing_title_hashes(conn)
            self._backfill_missing_pubdate_ts(conn)

            conn.execute(
                """
                INSERT OR IGNORE INTO news_keywords (link, keyword, query_key, is_duplicate)
                SELECT
                    link,
                    TRIM(keyword),
                    LOWER(TRIM(keyword)) || '|',
                    COALESCE(is_duplicate, 0)
                FROM news
                WHERE keyword IS NOT NULL AND TRIM(keyword) != ''
                """
            )
            self._set_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, self._get_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, "0"))
            self._set_app_meta(
                conn,
                self.FTS_BACKFILL_CURSOR_KEY,
                self._get_app_meta(conn, self.FTS_BACKFILL_CURSOR_KEY, "0"),
            )
            self._recalculate_duplicate_flags_with_conn(conn)

        conn.close()
