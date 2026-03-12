# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from core.text_utils import parse_date_to_ts

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseSchemaMixin:
    def _create_connection(self: DatabaseManager):
        """새 DB 연결 생성"""
        conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _check_integrity(self: DatabaseManager) -> bool:
        """데이터베이스 무결성 검사"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == "ok":
                return True
            return False
        except Exception as e:
            logger.error(f"DB 무결성 검사 실패: {e}")
            return False

    def _recover_database(self: DatabaseManager):
        """손상된 데이터베이스 백업 및 재생성"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.db_file}.corrupt_{timestamp}"

            if os.path.exists(self.db_file):
                try:
                    os.rename(self.db_file, backup_name)
                    logger.info(f"손상된 DB 백업 완료: {backup_name}")
                except OSError:
                    import shutil

                    shutil.copy2(self.db_file, backup_name)
                    os.remove(self.db_file)
                    logger.info(f"손상된 DB 복사 및 삭제 완료: {backup_name}")

        except Exception as e:
            logger.critical(f"DB 복구 실패: {e}")

    def init_db(self: DatabaseManager):
        """데이터베이스 초기화"""
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_keywords (
                    link TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    is_duplicate INTEGER DEFAULT 0,
                    PRIMARY KEY (link, keyword),
                    FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
                )
                """
            )

            columns_added = False
            try:
                conn.execute("ALTER TABLE news ADD COLUMN pubDate_ts REAL")
                logger.info("pubDate_ts 컬럼 추가됨")
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
                    logger.info(f"{col} 컬럼 추가됨 (마이그레이션)")
                    if col == "title_hash":
                        columns_added = True
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
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword ON news_keywords(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_nk_link ON news_keywords(link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_link ON news_keywords(keyword, link)",
                "CREATE INDEX IF NOT EXISTS idx_nk_keyword_dup ON news_keywords(keyword, is_duplicate)",
            ]
            for idx in indexes:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError as e:
                    logger.debug(f"Index creation skipped: {e}")

            if columns_added:
                cursor = conn.execute("SELECT link, title FROM news WHERE title_hash IS NULL LIMIT 1000")
                rows = cursor.fetchall()
                if rows:
                    logger.info(f"기존 데이터 마이그레이션 중... ({len(rows)}개)")
                    for link, title in rows:
                        if title:
                            title_hash = self._calculate_title_hash(title)
                            conn.execute("UPDATE news SET title_hash = ? WHERE link = ?", (title_hash, link))
                    logger.info("마이그레이션 완료")

            cursor = conn.execute("SELECT link, pubDate FROM news WHERE pubDate_ts IS NULL LIMIT 5000")
            rows = cursor.fetchall()
            if rows:
                logger.info(f"pubDate_ts 데이터 보정 중... ({len(rows)}개)")
                updates = []
                for link, pub_date in rows:
                    updates.append((parse_date_to_ts(pub_date), link))
                if updates:
                    conn.executemany("UPDATE news SET pubDate_ts = ? WHERE link = ?", updates)
                logger.info("pubDate_ts 데이터 보정 완료")

            conn.execute(
                """
                INSERT OR IGNORE INTO news_keywords (link, keyword, is_duplicate)
                SELECT link, keyword, COALESCE(is_duplicate, 0)
                FROM news
                WHERE keyword IS NOT NULL AND keyword != ''
                """
            )
            self._recalculate_duplicate_flags_with_conn(conn)

        conn.close()
