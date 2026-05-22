
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


class _CloudSyncMergeRowsMixin:
    def _merge_cloud_news_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_news_columns: Set[str],
    ) -> None:
        s = "s"
        link = self._source_expr(source_news_columns, s, "link", "''")
        keyword = self._source_expr(source_news_columns, s, "keyword", "''")
        title = self._source_expr(source_news_columns, s, "title", "''")
        description = self._source_expr(source_news_columns, s, "description", "''")
        pub_date = self._source_expr(source_news_columns, s, "pubDate", "''")
        publisher = self._source_expr(source_news_columns, s, "publisher", "''")
        is_read = self._source_expr(source_news_columns, s, "is_read", "0")
        is_bookmarked = self._source_expr(source_news_columns, s, "is_bookmarked", "0")
        pub_date_ts = self._source_expr(source_news_columns, s, "pubDate_ts", "0")
        created_at = self._source_expr(source_news_columns, s, "created_at", "0")
        notes = self._source_expr(source_news_columns, s, "notes", "''")
        title_hash = self._source_expr(source_news_columns, s, "title_hash", "''")
        is_duplicate = self._source_expr(source_news_columns, s, "is_duplicate", "0")
        is_deleted = self._source_expr(source_news_columns, s, "is_deleted", "0")
        delete_updated_at = self._source_expr(source_news_columns, s, "delete_updated_at", "0")
        delete_machine_id = self._source_expr(source_news_columns, s, "delete_machine_id", "''")
        delete_reason = self._source_expr(source_news_columns, s, "delete_reason", "''")

        if "read_updated_at" in source_news_columns:
            read_updated_at = "COALESCE(s.read_updated_at, 0)"
        else:
            read_updated_at = "CASE WHEN COALESCE(s.is_read, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if "bookmark_updated_at" in source_news_columns:
            bookmark_updated_at = "COALESCE(s.bookmark_updated_at, 0)"
        else:
            bookmark_updated_at = "CASE WHEN COALESCE(s.is_bookmarked, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if "notes_updated_at" in source_news_columns:
            notes_updated_at = "COALESCE(s.notes_updated_at, 0)"
        else:
            notes_updated_at = "CASE WHEN COALESCE(s.notes, '') != '' THEN COALESCE(s.created_at, 0) ELSE 0 END"

        conn.execute(
            f"""
            INSERT INTO news (
                link, keyword, title, description, pubDate, publisher,
                is_read, is_bookmarked, pubDate_ts, created_at, notes,
                title_hash, is_duplicate,
                read_updated_at, bookmark_updated_at, notes_updated_at,
                is_deleted, delete_updated_at, delete_machine_id, delete_reason
            )
            SELECT
                {link}, {keyword}, {title}, {description}, {pub_date}, {publisher},
                {is_read}, {is_bookmarked}, {pub_date_ts}, {created_at}, {notes},
                {title_hash}, {is_duplicate},
                {read_updated_at}, {bookmark_updated_at}, {notes_updated_at},
                {is_deleted}, {delete_updated_at}, {delete_machine_id}, {delete_reason}
            FROM cloud_src.news s
            WHERE {link} != ''
            ON CONFLICT(link) DO UPDATE SET
                keyword = CASE
                    WHEN news.keyword IS NULL OR news.keyword = '' THEN excluded.keyword
                    ELSE news.keyword
                END,
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE news.title END,
                description = CASE
                    WHEN excluded.description != '' THEN excluded.description
                    ELSE news.description
                END,
                pubDate = CASE WHEN excluded.pubDate != '' THEN excluded.pubDate ELSE news.pubDate END,
                publisher = CASE
                    WHEN excluded.publisher != '' THEN excluded.publisher
                    ELSE news.publisher
                END,
                pubDate_ts = CASE
                    WHEN COALESCE(excluded.pubDate_ts, 0) > COALESCE(news.pubDate_ts, 0)
                    THEN excluded.pubDate_ts
                    ELSE news.pubDate_ts
                END,
                created_at = CASE
                    WHEN COALESCE(news.created_at, 0) = 0 THEN excluded.created_at
                    ELSE news.created_at
                END,
                title_hash = CASE
                    WHEN excluded.title_hash != '' THEN excluded.title_hash
                    ELSE news.title_hash
                END,
                is_read = CASE
                    WHEN COALESCE(excluded.read_updated_at, 0) > COALESCE(news.read_updated_at, 0)
                    THEN excluded.is_read
                    ELSE news.is_read
                END,
                read_updated_at = MAX(
                    COALESCE(news.read_updated_at, 0),
                    COALESCE(excluded.read_updated_at, 0)
                ),
                is_bookmarked = CASE
                    WHEN COALESCE(excluded.bookmark_updated_at, 0) > COALESCE(news.bookmark_updated_at, 0)
                    THEN excluded.is_bookmarked
                    ELSE news.is_bookmarked
                END,
                bookmark_updated_at = MAX(
                    COALESCE(news.bookmark_updated_at, 0),
                    COALESCE(excluded.bookmark_updated_at, 0)
                ),
                notes = CASE
                    WHEN COALESCE(excluded.notes_updated_at, 0) > COALESCE(news.notes_updated_at, 0)
                    THEN excluded.notes
                    ELSE news.notes
                END,
                notes_updated_at = MAX(
                    COALESCE(news.notes_updated_at, 0),
                    COALESCE(excluded.notes_updated_at, 0)
                ),
                is_deleted = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.is_deleted
                    ELSE news.is_deleted
                END,
                delete_updated_at = MAX(
                    COALESCE(news.delete_updated_at, 0),
                    COALESCE(excluded.delete_updated_at, 0)
                ),
                delete_machine_id = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.delete_machine_id
                    ELSE news.delete_machine_id
                END,
                delete_reason = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.delete_reason
                    ELSE news.delete_reason
                END
            """
        )

    def _merge_cloud_keyword_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_keyword_columns: Set[str],
    ) -> None:
        if not source_keyword_columns:
            return
        nk = "nk"
        link = self._source_expr(source_keyword_columns, nk, "link", "''")
        keyword = self._source_expr(source_keyword_columns, nk, "keyword", "''")
        query_key = self._source_expr(source_keyword_columns, nk, "query_key", "''")
        is_duplicate = self._source_expr(source_keyword_columns, nk, "is_duplicate", "0")
        conn.execute(
            f"""
            INSERT INTO news_keywords (link, keyword, query_key, is_duplicate)
            SELECT {link}, {keyword}, {query_key}, {is_duplicate}
            FROM cloud_src.news_keywords nk
            WHERE {link} != ''
              AND {query_key} != ''
              AND EXISTS (SELECT 1 FROM news n WHERE n.link = {link})
            ON CONFLICT(link, query_key) DO UPDATE SET
                keyword = CASE
                    WHEN excluded.keyword != '' THEN excluded.keyword
                    ELSE news_keywords.keyword
                END
            """
        )

    def _merge_cloud_tag_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_news_columns: Set[str],
        has_tag_state: bool,
    ) -> None:
        if not self._table_exists(conn, "cloud_src", "news_tags"):
            return

        if has_tag_state:
            source_ts_expr = (
                "COALESCE((SELECT st.tags_updated_at FROM cloud_src.news_tag_state st "
                "WHERE st.link = nt.link), 0)"
            )
        elif "created_at" in source_news_columns:
            source_ts_expr = (
                "COALESCE((SELECT n.created_at FROM cloud_src.news n "
                "WHERE n.link = nt.link), 0)"
            )
        else:
            source_ts_expr = "0"

        conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")
        conn.execute(
            "CREATE TEMP TABLE temp_cloud_tag_links (link TEXT PRIMARY KEY, tags_updated_at REAL)"
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO temp_cloud_tag_links(link, tags_updated_at)
            SELECT nt.link, MAX({source_ts_expr})
            FROM cloud_src.news_tags nt
            WHERE nt.link IS NOT NULL
              AND nt.link != ''
              AND EXISTS (SELECT 1 FROM news n WHERE n.link = nt.link)
            GROUP BY nt.link
            HAVING MAX({source_ts_expr}) > COALESCE(
                (SELECT local_state.tags_updated_at
                 FROM news_tag_state local_state
                 WHERE local_state.link = nt.link),
                0
            )
            """
        )
        conn.execute(
            """
            DELETE FROM news_tags
            WHERE link IN (SELECT link FROM temp_cloud_tag_links)
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO news_tags(link, tag)
            SELECT nt.link, nt.tag
            FROM cloud_src.news_tags nt
            JOIN temp_cloud_tag_links t ON t.link = nt.link
            WHERE nt.tag IS NOT NULL AND TRIM(nt.tag) != ''
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO news_tag_state(link, tags_updated_at)
            SELECT link, tags_updated_at FROM temp_cloud_tag_links
            """
        )
        conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")
