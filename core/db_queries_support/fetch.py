
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from core.publisher_aliases import expand_publisher_filters
from core.text_utils import perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)
RE_FTS_ACCEL_TOKEN = re.compile(r"[0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3]{2,}")


@dataclass(frozen=True)
class NewsCountSummary:
    total_count: int
    unread_count: int


class _DatabaseFetchQueriesMixin:
    def fetch_news(
        self: DatabaseManager,
        keyword: str,
        filter_txt: str = "",
        sort_mode: str = "최신순",
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        exclude_words: Optional[List[str]] = None,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        query_key: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch rows for a tab or bookmark view."""
        managed_conn = conn is None
        news_items: List[Dict[str, Any]] = []
        scope_meta = (
            f"kw={keyword}|query_key={query_key or ''}|bookmark={int(only_bookmark)}|"
            f"unread={int(only_unread)}|hide_dup={int(hide_duplicates)}|"
            f"ex={len(exclude_words) if exclude_words else 0}|limit={limit}|offset={offset}"
        )
        try:
            if conn is None:
                conn = self.get_connection()
            with perf_timer("db.fetch_news", scope_meta):
                params: List[Any] = []
                fts_match = self._fts_match_expression(filter_txt)

                if only_bookmark:
                    query = (
                        """
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
                        WHERE n.is_bookmarked = 1
                          AND COALESCE(n.is_deleted, 0) = 0
                        """
                    )
                else:
                    query = (
                        """
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
                            COALESCE((
                                SELECT GROUP_CONCAT(nt.tag, ',')
                                FROM news_tags nt
                                WHERE nt.link = n.link
                            ), '') AS tags,
                            n.title_hash,
                            nk.is_duplicate AS is_duplicate
                        FROM news n
                        JOIN news_keywords nk ON nk.link = n.link
                        WHERE
                        """
                        + self._append_news_scope_clause(params, keyword, query_key)
                        + " AND COALESCE(n.is_deleted, 0) = 0"
                    )

                if fts_match:
                    query += (
                        " AND n.rowid IN ("
                        "SELECT rowid FROM news_fts WHERE news_fts MATCH ?"
                        ")"
                    )
                    params.append(fts_match)

                if only_unread:
                    query += " AND n.is_read = 0"

                if hide_duplicates:
                    if only_bookmark:
                        query += (
                            " AND NOT EXISTS ("
                            "SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                        )
                    else:
                        query += " AND nk.is_duplicate = 0"

                query += self._append_visibility_filter_clause(
                    params,
                    blocked_publishers=blocked_publishers,
                    preferred_publishers=preferred_publishers,
                    only_preferred_publishers=only_preferred_publishers,
                    tag_filter=tag_filter,
                )

                query += self._append_text_filter_clause(params, filter_txt)

                if exclude_words:
                    for exclude_word in exclude_words:
                        if not exclude_word:
                            continue
                        query += " AND NOT (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')"
                        wildcard = self._like_contains(exclude_word)
                        params.extend([wildcard, wildcard])

                if start_date:
                    try:
                        s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                        query += " AND n.pubDate_ts >= ?"
                        params.append(s_ts)
                    except ValueError:
                        logger.warning("Invalid start_date format: %s", start_date)

                if end_date:
                    try:
                        e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                        query += " AND n.pubDate_ts < ?"
                        params.append(e_ts)
                    except ValueError:
                        logger.warning("Invalid end_date format: %s", end_date)

                if sort_mode == "최신순":
                    query += " ORDER BY n.pubDate_ts DESC, n.link DESC"
                else:
                    query += " ORDER BY n.pubDate_ts ASC, n.link ASC"

                safe_offset = max(0, int(offset))
                if limit is not None:
                    query += " LIMIT ? OFFSET ?"
                    params.append(max(0, int(limit)))
                    params.append(safe_offset)

                cursor = conn.cursor()
                cursor.execute(query, params)
                columns = [column[0] for column in cursor.description]
                for row in cursor.fetchall():
                    news_items.append(dict(zip(columns, row)))
        except Exception as e:
            logger.error("fetch_news failed: %s", e)
            raise self._new_query_error("fetch_news", e) from e
        finally:
            if managed_conn and conn is not None:
                self.return_connection(conn)

        return news_items

    def _build_count_news_query(
        self: DatabaseManager,
        keyword: str,
        *,
        select_expression: str,
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        filter_txt: str = "",
        exclude_words: Optional[List[str]] = None,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
    ) -> tuple[str, List[Any]]:
        params: List[Any] = []
        fts_match = self._fts_match_expression(filter_txt)
        if only_bookmark:
            query = (
                f"SELECT {select_expression} "
                "FROM news n "
                "WHERE n.is_bookmarked = 1 AND COALESCE(n.is_deleted, 0) = 0"
            )
        else:
            query = (
                f"SELECT {select_expression} "
                "FROM news n "
                "JOIN news_keywords nk ON nk.link = n.link "
                "WHERE "
                + self._append_news_scope_clause(params, keyword, query_key)
                + " AND COALESCE(n.is_deleted, 0) = 0"
            )

        if fts_match:
            query += (
                " AND n.rowid IN ("
                "SELECT rowid FROM news_fts WHERE news_fts MATCH ?"
                ")"
            )
            params.append(fts_match)

        if only_unread:
            query += " AND n.is_read = 0"

        if hide_duplicates:
            if only_bookmark:
                query += (
                    " AND NOT EXISTS ("
                    "SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                )
            else:
                query += " AND nk.is_duplicate = 0"

        query += self._append_visibility_filter_clause(
            params,
            blocked_publishers=blocked_publishers,
            preferred_publishers=preferred_publishers,
            only_preferred_publishers=only_preferred_publishers,
            tag_filter=tag_filter,
        )

        query += self._append_text_filter_clause(params, filter_txt)

        if exclude_words:
            for exclude_word in exclude_words:
                if not exclude_word:
                    continue
                query += " AND NOT (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')"
                wildcard = self._like_contains(exclude_word)
                params.extend([wildcard, wildcard])

        if start_date:
            try:
                s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                query += " AND n.pubDate_ts >= ?"
                params.append(s_ts)
            except ValueError:
                logger.warning("Invalid start_date format: %s", start_date)

        if end_date:
            try:
                e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                query += " AND n.pubDate_ts < ?"
                params.append(e_ts)
            except ValueError:
                logger.warning("Invalid end_date format: %s", end_date)

        return query, params

    def count_news(
        self: DatabaseManager,
        keyword: str,
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        filter_txt: str = "",
        exclude_words: Optional[List[str]] = None,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Count rows for a tab or bookmark view."""
        managed_conn = conn is None
        scope_meta = (
            f"kw={keyword}|query_key={query_key or ''}|bookmark={int(only_bookmark)}|"
            f"unread={int(only_unread)}|hide_dup={int(hide_duplicates)}"
        )
        try:
            if conn is None:
                conn = self.get_connection()
            with perf_timer("db.count_news", scope_meta):
                query, params = self._build_count_news_query(
                    keyword,
                    select_expression="COUNT(*)",
                    only_bookmark=only_bookmark,
                    only_unread=only_unread,
                    hide_duplicates=hide_duplicates,
                    filter_txt=filter_txt,
                    exclude_words=exclude_words,
                    blocked_publishers=blocked_publishers,
                    preferred_publishers=preferred_publishers,
                    only_preferred_publishers=only_preferred_publishers,
                    tag_filter=tag_filter,
                    start_date=start_date,
                    end_date=end_date,
                    query_key=query_key,
                )
                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("count_news failed: %s", e)
            raise self._new_query_error("count_news", e) from e
        finally:
            if managed_conn and conn is not None:
                self.return_connection(conn)

    def count_news_states(
        self: DatabaseManager,
        keyword: str,
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        filter_txt: str = "",
        exclude_words: Optional[List[str]] = None,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> NewsCountSummary:
        """Count total and unread rows for the same visible scope in one query."""
        managed_conn = conn is None
        scope_meta = (
            f"kw={keyword}|query_key={query_key or ''}|bookmark={int(only_bookmark)}|"
            f"unread={int(only_unread)}|hide_dup={int(hide_duplicates)}"
        )
        try:
            if conn is None:
                conn = self.get_connection()
            with perf_timer("db.count_news_states", scope_meta):
                query, params = self._build_count_news_query(
                    keyword,
                    select_expression=(
                        "COUNT(*) AS total_count, "
                        "COALESCE(SUM(CASE WHEN n.is_read = 0 THEN 1 ELSE 0 END), 0) AS unread_count"
                    ),
                    only_bookmark=only_bookmark,
                    only_unread=only_unread,
                    hide_duplicates=hide_duplicates,
                    filter_txt=filter_txt,
                    exclude_words=exclude_words,
                    blocked_publishers=blocked_publishers,
                    preferred_publishers=preferred_publishers,
                    only_preferred_publishers=only_preferred_publishers,
                    tag_filter=tag_filter,
                    start_date=start_date,
                    end_date=end_date,
                    query_key=query_key,
                )
                row = conn.execute(query, params).fetchone()
                if not row:
                    return NewsCountSummary(0, 0)
                return NewsCountSummary(
                    total_count=max(0, int(row[0] or 0)),
                    unread_count=max(0, int(row[1] or 0)),
                )
        except Exception as e:
            logger.error("count_news_states failed: %s", e)
            raise self._new_query_error("count_news_states", e) from e
        finally:
            if managed_conn and conn is not None:
                self.return_connection(conn)
