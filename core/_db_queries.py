# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from core.text_utils import perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseQueriesMixin:
    def _append_news_scope_clause(
        self: DatabaseManager,
        params: List[Any],
        keyword: str,
        query_key: Optional[str],
        alias: str = "nk",
    ) -> str:
        normalized_query_key = str(query_key or "").strip()
        if normalized_query_key:
            clause = f"{alias}.query_key = ?"
            params.append(normalized_query_key)
            normalized_keyword = str(keyword or "").strip()
            if normalized_keyword:
                clause += f" AND {alias}.keyword = ?"
                params.append(normalized_keyword)
            return clause

        clause = f"{alias}.keyword = ?"
        params.append(keyword)
        return clause

    def fetch_news(
        self: DatabaseManager,
        keyword: str,
        filter_txt: str = "",
        sort_mode: str = "최신순",
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        exclude_words: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        query_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch rows for a tab or bookmark view."""
        conn = self.get_connection()
        news_items: List[Dict[str, Any]] = []
        scope_meta = (
            f"kw={keyword}|query_key={query_key or ''}|bookmark={int(only_bookmark)}|"
            f"unread={int(only_unread)}|hide_dup={int(hide_duplicates)}|"
            f"ex={len(exclude_words) if exclude_words else 0}|limit={limit}|offset={offset}"
        )
        try:
            with perf_timer("db.fetch_news", scope_meta):
                params: List[Any] = []

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
                            n.title_hash,
                            nk.is_duplicate AS is_duplicate
                        FROM news n
                        JOIN news_keywords nk ON nk.link = n.link
                        WHERE
                        """
                        + self._append_news_scope_clause(params, keyword, query_key)
                    )

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

                if filter_txt:
                    query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{filter_txt}%"
                    params.extend([wildcard, wildcard])

                if exclude_words:
                    for exclude_word in exclude_words:
                        if not exclude_word:
                            continue
                        query += " AND NOT (n.title LIKE ? OR n.description LIKE ?)"
                        wildcard = f"%{exclude_word}%"
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
                    query += " ORDER BY n.pubDate_ts DESC"
                else:
                    query += " ORDER BY n.pubDate_ts ASC"

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
        finally:
            self.return_connection(conn)

        return news_items

    def count_news(
        self: DatabaseManager,
        keyword: str,
        only_bookmark: bool = False,
        only_unread: bool = False,
        hide_duplicates: bool = False,
        filter_txt: str = "",
        exclude_words: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
    ) -> int:
        """Count rows for a tab or bookmark view."""
        conn = self.get_connection()
        scope_meta = (
            f"kw={keyword}|query_key={query_key or ''}|bookmark={int(only_bookmark)}|"
            f"unread={int(only_unread)}|hide_dup={int(hide_duplicates)}"
        )
        try:
            with perf_timer("db.count_news", scope_meta):
                params: List[Any] = []
                if only_bookmark:
                    query = "SELECT COUNT(*) FROM news n WHERE n.is_bookmarked = 1"
                else:
                    query = (
                        "SELECT COUNT(*) FROM news n "
                        "JOIN news_keywords nk ON nk.link = n.link "
                        "WHERE "
                        + self._append_news_scope_clause(params, keyword, query_key)
                    )

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

                if filter_txt:
                    query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{filter_txt}%"
                    params.extend([wildcard, wildcard])

                if exclude_words:
                    for exclude_word in exclude_words:
                        if not exclude_word:
                            continue
                        query += " AND NOT (n.title LIKE ? OR n.description LIKE ?)"
                        wildcard = f"%{exclude_word}%"
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

                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("count_news failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

    def get_counts(
        self: DatabaseManager,
        keyword: str,
        query_key: Optional[str] = None,
    ) -> int:
        """Count memberships for a keyword or a full query scope."""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_counts", f"kw={keyword}|query_key={query_key or ''}"):
                if query_key:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM news_keywords WHERE query_key = ?",
                        (query_key,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM news_keywords WHERE keyword = ?",
                        (keyword,),
                    ).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_counts failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

    def get_unread_count(
        self: DatabaseManager,
        keyword: str,
        query_key: Optional[str] = None,
    ) -> int:
        """Count unread rows for a keyword or a full query scope."""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_unread_count", f"kw={keyword}|query_key={query_key or ''}"):
                params: List[Any] = []
                query = (
                    "SELECT COUNT(*) "
                    "FROM news n "
                    "JOIN news_keywords nk ON nk.link = n.link "
                    "WHERE "
                    + self._append_news_scope_clause(params, keyword, query_key)
                    + " AND n.is_read = 0"
                )
                row = conn.execute(query, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_unread_count failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

    def get_total_unread_count(self: DatabaseManager) -> int:
        """Get unread count across all rows in news."""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_total_unread_count", "scope=all"):
                row = conn.execute("SELECT COUNT(*) FROM news WHERE is_read = 0").fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("get_total_unread_count failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

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

        conn = self.get_connection()
        try:
            with perf_timer(f"db.get_unread_counts_by_{column_name}", f"count={len(cleaned)}"):
                placeholders = ",".join(["?"] * len(cleaned))
                query = f"""
                    SELECT nk.{column_name}, COUNT(*) AS unread_count
                    FROM news_keywords nk
                    JOIN news n ON n.link = nk.link
                    WHERE nk.{column_name} IN ({placeholders}) AND n.is_read = 0
                    GROUP BY nk.{column_name}
                """
                rows = conn.execute(query, cleaned).fetchall()
                unread_by_value: Dict[str, int] = {value: 0 for value in cleaned}
                for row in rows:
                    unread_by_value[str(row[0])] = int(row[1])
                return unread_by_value
        except Exception as e:
            logger.error("Grouped unread count lookup failed: %s", e)
            return {value: 0 for value in cleaned}
        finally:
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
        conn = self.get_connection()
        try:
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
            return set()
        finally:
            self.return_connection(conn)
