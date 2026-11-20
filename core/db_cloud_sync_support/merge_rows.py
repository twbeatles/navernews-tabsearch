# pyright: reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Set

from core.db_cloud_sync_support.policy import (
    CONTENT_FIELDS,
    content_wins,
    register_content_functions,
    source_content_projection,
    source_timestamp,
    source_wins,
    tag_candidates_sql,
)

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
        pub_date_ts = "content.pubDate_ts"
        created_at = self._source_expr(source_news_columns, s, "created_at", "0")
        notes = self._source_expr(source_news_columns, s, "notes", "''")
        title_hash = "content.title_hash"
        is_duplicate = self._source_expr(source_news_columns, s, "is_duplicate", "0")
        is_deleted = self._source_expr(source_news_columns, s, "is_deleted", "0")
        delete_updated_at = self._source_expr(
            source_news_columns, s, "delete_updated_at", "0"
        )
        delete_machine_id = self._source_expr(
            source_news_columns, s, "delete_machine_id", "''"
        )
        delete_reason = self._source_expr(source_news_columns, s, "delete_reason", "''")

        content_updated_at = self._source_expr(
            source_news_columns, s, "content_updated_at", "0"
        )

        read_updated_at = source_timestamp(source_news_columns, "read_updated_at")
        bookmark_updated_at = source_timestamp(
            source_news_columns, "bookmark_updated_at"
        )
        notes_updated_at = source_timestamp(source_news_columns, "notes_updated_at")
        register_content_functions(conn, self._calculate_title_hash)
        content_source = source_content_projection(source_news_columns)

        content_choice = content_wins()
        content_updates = ",\n                ".join(
            f"{field} = CASE WHEN {content_choice} THEN excluded.{field} ELSE news.{field} END"
            for field in CONTENT_FIELDS
        )
        winners = {}
        for field, timestamp in (
            ("is_read", "read_updated_at"),
            ("is_bookmarked", "bookmark_updated_at"),
            ("notes", "notes_updated_at"),
        ):
            default = "''" if field == "notes" else "0"
            winners[field] = source_wins(
                f"COALESCE(excluded.{timestamp}, 0)",
                f"COALESCE(news.{timestamp}, 0)",
                f"COALESCE(excluded.{field}, {default})",
                f"COALESCE(news.{field}, {default})",
            )
        delete_choice = source_wins(
            "COALESCE(excluded.delete_updated_at, 0)",
            "COALESCE(news.delete_updated_at, 0)",
            "(COALESCE(excluded.is_deleted, 0), COALESCE(excluded.delete_machine_id, ''), COALESCE(excluded.delete_reason, ''))",
            "(COALESCE(news.is_deleted, 0), COALESCE(news.delete_machine_id, ''), COALESCE(news.delete_reason, ''))",
        )

        conn.execute(
            f"""
            INSERT INTO news (
                link, keyword, title, description, pubDate, publisher,
                is_read, is_bookmarked, pubDate_ts, created_at, notes,
                title_hash, is_duplicate,
                read_updated_at, bookmark_updated_at, notes_updated_at,
                is_deleted, delete_updated_at, delete_machine_id, delete_reason, content_updated_at
            )
            SELECT
                {link}, {keyword}, {title}, {description}, {pub_date}, {publisher},
                {is_read}, {is_bookmarked}, {pub_date_ts}, {created_at}, {notes},
                {title_hash}, {is_duplicate},
                {read_updated_at}, {bookmark_updated_at}, {notes_updated_at},
                {is_deleted}, {delete_updated_at}, {delete_machine_id}, {delete_reason}, {content_updated_at}
            FROM cloud_src.news s
            JOIN ({content_source}) content ON content.link=s.link
            WHERE {link} != ''
            ON CONFLICT(link) DO UPDATE SET
                keyword = CASE
                    WHEN news.keyword IS NULL OR news.keyword = '' THEN excluded.keyword
                    ELSE news.keyword
                END,
                {content_updates},
                content_updated_at = MAX(COALESCE(news.content_updated_at, 0), excluded.content_updated_at),
                created_at = CASE
                    WHEN COALESCE(news.created_at, 0) = 0 THEN excluded.created_at
                    ELSE news.created_at
                END,
                is_read = CASE
                    WHEN {winners["is_read"]}
                    THEN excluded.is_read
                    ELSE news.is_read
                END,
                read_updated_at = MAX(
                    COALESCE(news.read_updated_at, 0),
                    COALESCE(excluded.read_updated_at, 0)
                ),
                is_bookmarked = CASE
                    WHEN {winners["is_bookmarked"]}
                    THEN excluded.is_bookmarked
                    ELSE news.is_bookmarked
                END,
                bookmark_updated_at = MAX(
                    COALESCE(news.bookmark_updated_at, 0),
                    COALESCE(excluded.bookmark_updated_at, 0)
                ),
                notes = CASE
                    WHEN {winners["notes"]}
                    THEN excluded.notes
                    ELSE news.notes
                END,
                notes_updated_at = MAX(
                    COALESCE(news.notes_updated_at, 0),
                    COALESCE(excluded.notes_updated_at, 0)
                ),
                is_deleted = CASE
                    WHEN {delete_choice}
                    THEN excluded.is_deleted
                    ELSE news.is_deleted
                END,
                delete_updated_at = MAX(
                    COALESCE(news.delete_updated_at, 0),
                    COALESCE(excluded.delete_updated_at, 0)
                ),
                delete_machine_id = CASE
                    WHEN {delete_choice}
                    THEN excluded.delete_machine_id
                    ELSE news.delete_machine_id
                END,
                delete_reason = CASE
                    WHEN {delete_choice}
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
        is_duplicate = self._source_expr(
            source_keyword_columns, nk, "is_duplicate", "0"
        )
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
        candidates = tag_candidates_sql(conn, source_news_columns, has_tag_state)
        conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")
        conn.execute(
            "CREATE TEMP TABLE temp_cloud_tag_links (link TEXT PRIMARY KEY, tags_updated_at REAL)"
        )
        conn.execute(
            f"INSERT INTO temp_cloud_tag_links SELECT link, tags_updated_at FROM ({candidates})"
        )
        conn.execute(
            "DELETE FROM news_tags WHERE link IN (SELECT link FROM temp_cloud_tag_links)"
        )
        if self._table_exists(conn, "cloud_src", "news_tags"):
            conn.execute(
                """
                INSERT OR IGNORE INTO news_tags(link, tag)
                SELECT nt.link, nt.tag FROM cloud_src.news_tags nt
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
