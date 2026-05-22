
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


class _NewsTableSchemaMixin:
    def _ensure_news_tags_schema(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_tags (
                link TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (link, tag),
                FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
            )
            """
        )

    def _ensure_news_tag_state_schema(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_tag_state (
                link TEXT PRIMARY KEY,
                tags_updated_at REAL DEFAULT 0,
                FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
            )
            """
        )

    def _ensure_app_meta_table(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    def _ensure_news_fts_schema(self: DatabaseManager, conn: sqlite3.Connection) -> None:
        legacy_map_exists = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='news_fts_map'
            """
        ).fetchone()
        if legacy_map_exists:
            for trigger_name in ("trg_news_fts_insert", "trg_news_fts_delete", "trg_news_fts_update"):
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
            conn.execute("DROP TABLE IF EXISTS news_fts_map")
            conn.execute("DROP TABLE IF EXISTS news_fts")
            self._set_app_meta(conn, self.FTS_BACKFILL_CURSOR_KEY, "0")
            self._set_app_meta(conn, self.FTS_BACKFILL_DONE_KEY, "0")

        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS news_fts
            USING fts5(title, description, tokenize='unicode61')
            """
        )

        trigger_specs = {
            "trg_news_fts_insert": """
                CREATE TRIGGER trg_news_fts_insert
                AFTER INSERT ON news
                BEGIN
                    DELETE FROM news_fts WHERE rowid = NEW.rowid;
                    INSERT INTO news_fts(rowid, title, description)
                    VALUES (NEW.rowid, COALESCE(NEW.title, ''), COALESCE(NEW.description, ''));
                END
            """,
            "trg_news_fts_delete": """
                CREATE TRIGGER trg_news_fts_delete
                BEFORE DELETE ON news
                BEGIN
                    DELETE FROM news_fts WHERE rowid = OLD.rowid;
                END
            """,
            "trg_news_fts_update": """
                CREATE TRIGGER trg_news_fts_update
                AFTER UPDATE OF title, description ON news
                BEGIN
                    DELETE FROM news_fts WHERE rowid = NEW.rowid;
                    INSERT INTO news_fts(rowid, title, description)
                    VALUES (NEW.rowid, COALESCE(NEW.title, ''), COALESCE(NEW.description, ''));
                END
            """,
        }
        for trigger_name, ddl in trigger_specs.items():
            exists = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='trigger' AND name=?
                """,
                (trigger_name,),
            ).fetchone()
            if not exists:
                conn.execute(ddl)

    def _set_app_meta(self: DatabaseManager, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO app_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(key), str(value)),
        )

    def _get_app_meta(self: DatabaseManager, conn: sqlite3.Connection, key: str, default: str = "") -> str:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (str(key),)).fetchone()
        return str(row[0]) if row and row[0] is not None else str(default)
