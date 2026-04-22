# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class IntegrityCheckResult(NamedTuple):
    state: str
    detail: str = ""


class _DatabaseSchemaMixin:
    FTS_BACKFILL_CURSOR_KEY = "news_fts.backfill_rowid"
    FTS_BACKFILL_DONE_KEY = "news_fts.backfill_done"
    TITLE_HASH_BACKFILL_CHUNK_SIZE = 1000
    PUBDATE_TS_BACKFILL_CHUNK_SIZE = 5000

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
            self._ensure_app_meta_table(conn)
            self._ensure_news_fts_schema(conn)

            try:
                conn.execute("ALTER TABLE news ADD COLUMN pubDate_ts REAL")
                logger.info("Added pubDate_ts column")
            except sqlite3.OperationalError:
                pass

            for col, dtype in [
                ("publisher", "TEXT"),
                ("is_read", "INTEGER DEFAULT 0"),
                ("is_bookmarked", "INTEGER DEFAULT 0"),
                ("created_at", "REAL DEFAULT (strftime('%s', 'now'))"),
                ("notes", "TEXT"),
                ("title_hash", "TEXT"),
                ("is_duplicate", "INTEGER DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE news ADD COLUMN {col} {dtype}")
                    logger.info("Added news.%s column", col)
                except sqlite3.OperationalError:
                    pass

            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)",
                "CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)",
                "CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)",
                "CREATE INDEX IF NOT EXISTS idx_read_ts ON news(is_read, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_title_hash ON news(title_hash)",
                "CREATE INDEX IF NOT EXISTS idx_duplicate ON news(is_duplicate)",
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
