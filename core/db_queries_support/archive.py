
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from core.publisher_aliases import expand_publisher_filters
from core.text_utils import perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)
RE_FTS_ACCEL_TOKEN = re.compile(r"[0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3]{2,}")


class _DatabaseArchiveQueriesMixin:
    def _archive_base_select(self: DatabaseManager, *, include_deleted: bool = False) -> str:
        deleted_filter = "1 = 1" if include_deleted else "COALESCE(n.is_deleted, 0) = 0"
        return f"""
            SELECT
                n.link,
                n.title,
                n.description,
                n.pubDate,
                n.publisher,
                n.is_read,
                n.is_bookmarked,
                n.pubDate_ts,
                n.created_at,
                n.notes,
                COALESCE(n.is_deleted, 0) AS is_deleted,
                COALESCE(n.delete_updated_at, 0) AS delete_updated_at,
                COALESCE(n.delete_machine_id, '') AS delete_machine_id,
                COALESCE(n.delete_reason, '') AS delete_reason,
                COALESCE((
                    SELECT GROUP_CONCAT(nt.tag, ',')
                    FROM news_tags nt
                    WHERE nt.link = n.link
                ), '') AS tags,
                n.title_hash,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM news_keywords nk
                        WHERE nk.link = n.link AND nk.is_duplicate = 1
                    ) THEN 1
                    ELSE 0
                END AS is_duplicate
            FROM news n
            WHERE {deleted_filter}
        """

    def _append_archive_filters(
        self: DatabaseManager,
        query: str,
        params: List[Any],
        *,
        filter_txt: str = "",
        notes_txt: str = "",
        publisher_filter: str = "",
        publisher_aliases: Optional[Dict[str, str]] = None,
        tag_filter: str = "",
        only_bookmark: bool = False,
        only_unread: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        fts_match = self._fts_match_expression(filter_txt)
        if fts_match:
            query += " AND n.rowid IN (SELECT rowid FROM news_fts WHERE news_fts MATCH ?)"
            params.append(fts_match)
        query += self._append_text_filter_clause(params, filter_txt)

        raw_notes = str(notes_txt or "").strip()
        if raw_notes:
            query += " AND COALESCE(n.notes, '') LIKE ? ESCAPE '\\'"
            params.append(self._like_contains(raw_notes))

        expanded_publishers = expand_publisher_filters(
            [publisher_filter] if str(publisher_filter or "").strip() else [],
            publisher_aliases or {},
        )
        if expanded_publishers:
            match_clause = self._append_publisher_match_clause(
                params,
                "LOWER(COALESCE(n.publisher, ''))",
                self._normalize_publisher_match_values(expanded_publishers),
            )
            if match_clause:
                query += " AND " + match_clause

        normalized_tag = str(tag_filter or "").strip()
        if normalized_tag:
            query += " AND EXISTS (SELECT 1 FROM news_tags nt WHERE nt.link = n.link AND lower(nt.tag) = lower(?))"
            params.append(normalized_tag)

        if only_bookmark:
            query += " AND n.is_bookmarked = 1"
        if only_unread:
            query += " AND n.is_read = 0"

        if start_date:
            try:
                s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                query += " AND n.pubDate_ts >= ?"
                params.append(s_ts)
            except ValueError:
                logger.warning("Invalid start_date format for archive search: %s", start_date)
        if end_date:
            try:
                e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                query += " AND n.pubDate_ts < ?"
                params.append(e_ts)
            except ValueError:
                logger.warning("Invalid end_date format for archive search: %s", end_date)
        return query

    def search_archive(
        self: DatabaseManager,
        *,
        filter_txt: str = "",
        notes_txt: str = "",
        publisher_filter: str = "",
        publisher_aliases: Optional[Dict[str, str]] = None,
        tag_filter: str = "",
        only_bookmark: bool = False,
        only_unread: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sort_mode: str = "최신순",
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[Dict[str, Any]]:
        owns_connection = conn is None
        active_conn = conn
        rows_out: List[Dict[str, Any]] = []
        try:
            if active_conn is None:
                active_conn = self.get_connection()
            params: List[Any] = []
            query = self._append_archive_filters(
                self._archive_base_select(include_deleted=include_deleted),
                params,
                filter_txt=filter_txt,
                notes_txt=notes_txt,
                publisher_filter=publisher_filter,
                publisher_aliases=publisher_aliases,
                tag_filter=tag_filter,
                only_bookmark=only_bookmark,
                only_unread=only_unread,
                start_date=start_date,
                end_date=end_date,
            )
            if sort_mode == "오래된순":
                query += " ORDER BY n.pubDate_ts ASC, n.link ASC"
            else:
                query += " ORDER BY n.pubDate_ts DESC, n.link DESC"
            query += " LIMIT ? OFFSET ?"
            params.extend([max(1, int(limit or 50)), max(0, int(offset or 0))])
            cursor = active_conn.execute(query, params)
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                rows_out.append(dict(zip(columns, row)))
            return rows_out
        except Exception as e:
            logger.error("search_archive failed: %s", e)
            raise self._new_query_error("search_archive", e) from e
        finally:
            if owns_connection and active_conn is not None:
                self.return_connection(active_conn)

    def count_archive(
        self: DatabaseManager,
        *,
        filter_txt: str = "",
        notes_txt: str = "",
        publisher_filter: str = "",
        publisher_aliases: Optional[Dict[str, str]] = None,
        tag_filter: str = "",
        only_bookmark: bool = False,
        only_unread: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_deleted: bool = False,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        owns_connection = conn is None
        active_conn = conn
        try:
            if active_conn is None:
                active_conn = self.get_connection()
            params: List[Any] = []
            deleted_filter = "1 = 1" if include_deleted else "COALESCE(n.is_deleted, 0) = 0"
            query = self._append_archive_filters(
                f"SELECT COUNT(*) FROM news n WHERE {deleted_filter}",
                params,
                filter_txt=filter_txt,
                notes_txt=notes_txt,
                publisher_filter=publisher_filter,
                publisher_aliases=publisher_aliases,
                tag_filter=tag_filter,
                only_bookmark=only_bookmark,
                only_unread=only_unread,
                start_date=start_date,
                end_date=end_date,
            )
            row = active_conn.execute(query, params).fetchone()
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error("count_archive failed: %s", e)
            raise self._new_query_error("count_archive", e) from e
        finally:
            if owns_connection and active_conn is not None:
                self.return_connection(active_conn)
