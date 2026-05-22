
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


class _DatabaseCountQueriesMixin:
    def get_counts(
        self: DatabaseManager,
        keyword: str,
        query_key: Optional[str] = None,
    ) -> int:
        """Count memberships for a keyword or a full query scope."""
        conn = None
        try:
            conn = self.get_connection()
            with perf_timer("db.get_counts", f"kw={keyword}|query_key={query_key or ''}"):
                if query_key:
                    row = conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM news_keywords nk
                        JOIN news n ON n.link = nk.link
                        WHERE nk.query_key = ? AND COALESCE(n.is_deleted, 0) = 0
                        """,
                        (query_key,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM news_keywords nk
                        JOIN news n ON n.link = nk.link
                        WHERE nk.keyword = ? AND COALESCE(n.is_deleted, 0) = 0
                        """,
                        (keyword,),
                    ).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_counts failed: %s", e)
            raise self._new_query_error("get_counts", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)

    def get_unread_count(
        self: DatabaseManager,
        keyword: str,
        query_key: Optional[str] = None,
    ) -> int:
        """Count unread rows for a keyword or a full query scope."""
        conn = None
        try:
            conn = self.get_connection()
            with perf_timer("db.get_unread_count", f"kw={keyword}|query_key={query_key or ''}"):
                params: List[Any] = []
                query = (
                    "SELECT COUNT(*) "
                    "FROM news n "
                    "JOIN news_keywords nk ON nk.link = n.link "
                    "WHERE "
                    + self._append_news_scope_clause(params, keyword, query_key)
                    + " AND n.is_read = 0 AND COALESCE(n.is_deleted, 0) = 0"
                )
                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_unread_count failed: %s", e)
            raise self._new_query_error("get_unread_count", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)

    def get_total_unread_count(
        self: DatabaseManager,
        blocked_publishers: Optional[List[str]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Get unread count across all rows in news."""
        owns_connection = conn is None
        active_conn = conn
        try:
            if active_conn is None:
                active_conn = self.get_connection()
            with perf_timer("db.get_total_unread_count", "scope=all"):
                params: List[Any] = []
                query = "SELECT COUNT(*) FROM news n WHERE n.is_read = 0 AND COALESCE(n.is_deleted, 0) = 0"
                query += self._append_visibility_filter_clause(
                    params,
                    blocked_publishers=blocked_publishers,
                )
                row = active_conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_total_unread_count failed: %s", e)
            raise self._new_query_error("get_total_unread_count", e) from e
        finally:
            if owns_connection and active_conn is not None:
                self.return_connection(active_conn)

    def _get_grouped_unread_counts(
        self: DatabaseManager,
        column_name: str,
        raw_values: List[str],
    ) -> Dict[str, int]:
        if not raw_values:
            return {}

        cleaned = [value for value in raw_values if isinstance(value, str) and value.strip()]
        if not cleaned:
            return {}

        conn = None
        try:
            conn = self.get_connection()
            with perf_timer(f"db.get_unread_counts_by_{column_name}", f"count={len(cleaned)}"):
                placeholders = ",".join(["?"] * len(cleaned))
                query = f"""
                    SELECT nk.{column_name}, COUNT(*) AS unread_count
                    FROM news_keywords nk
                    JOIN news n ON n.link = nk.link
                    WHERE nk.{column_name} IN ({placeholders})
                      AND n.is_read = 0
                      AND COALESCE(n.is_deleted, 0) = 0
                    GROUP BY nk.{column_name}
                """
                rows = conn.execute(query, cleaned).fetchall()
                unread_by_value: Dict[str, int] = {value: 0 for value in cleaned}
                for row in rows:
                    unread_by_value[str(row[0])] = int(row[1])
                return unread_by_value
        except Exception as e:
            logger.error("Grouped unread count lookup failed: %s", e)
            raise self._new_query_error(f"get_unread_counts_by_{column_name}", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)

    def get_unread_counts_by_keywords(
        self: DatabaseManager,
        keywords: List[str],
    ) -> Dict[str, int]:
        """Legacy unread-count batch lookup keyed by representative keyword."""
        return self._get_grouped_unread_counts("keyword", keywords)

    def get_unread_counts_by_query_keys(
        self: DatabaseManager,
        query_keys: List[str],
    ) -> Dict[str, int]:
        """Unread-count batch lookup keyed by full query scope."""
        return self._get_grouped_unread_counts("query_key", query_keys)

    def get_existing_links_for_query(
        self: DatabaseManager,
        links: List[str],
        keyword: str = "",
        query_key: Optional[str] = None,
    ) -> Set[str]:
        """Return the subset of links that already exist in the current query scope."""
        cleaned_links = [
            str(link).strip()
            for link in links
            if isinstance(link, str) and str(link).strip()
        ]
        if not cleaned_links:
            return set()

        deduped_links = list(dict.fromkeys(cleaned_links))
        conn = None
        try:
            conn = self.get_connection()
            with perf_timer(
                "db.get_existing_links_for_query",
                f"kw={keyword}|query_key={query_key or ''}|links={len(deduped_links)}",
            ):
                placeholders = ",".join(["?"] * len(deduped_links))
                params: List[Any] = []
                query = (
                    "SELECT nk.link "
                    "FROM news_keywords nk "
                    "WHERE "
                    + self._append_news_scope_clause(params, keyword, query_key)
                    + f" AND nk.link IN ({placeholders})"
                )
                params.extend(deduped_links)
                rows = conn.execute(query, params).fetchall()
                return {str(row[0]) for row in rows if row and row[0]}
        except Exception as e:
            logger.error("get_existing_links_for_query failed: %s", e)
            raise self._new_query_error("get_existing_links_for_query", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)
