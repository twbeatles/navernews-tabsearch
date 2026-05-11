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


class _DatabaseQueriesMixin:
    def _filter_tokens(self: DatabaseManager, filter_txt: str) -> List[str]:
        raw = str(filter_txt or "").strip()
        if not raw:
            return []
        return [token.strip() for token in RE_FTS_ACCEL_TOKEN.findall(raw) if token.strip()]

    def _fts_match_expression(self: DatabaseManager, filter_txt: str) -> str:
        raw = str(filter_txt or "").strip()
        if not raw:
            return ""
        if not self.is_news_fts_backfill_complete():
            return ""
        tokens = self._filter_tokens(raw)
        if len(tokens) < 2:
            return ""
        lowered = []
        for token in tokens:
            normalized = token.strip().lower()
            if not normalized:
                continue
            lowered.append(f'"{normalized}"')
        if len(lowered) < 2:
            return ""
        return " AND ".join(lowered)

    def _append_text_filter_clause(
        self: DatabaseManager,
        params: List[Any],
        filter_txt: str,
    ) -> str:
        raw = str(filter_txt or "").strip()
        if not raw:
            return ""
        tokens = self._filter_tokens(raw)
        if len(tokens) >= 2:
            clauses: List[str] = []
            for token in tokens:
                clauses.append("(n.title LIKE ? OR n.description LIKE ?)")
                wildcard = f"%{token}%"
                params.extend([wildcard, wildcard])
            return " AND " + " AND ".join(clauses)
        wildcard = f"%{raw}%"
        params.extend([wildcard, wildcard])
        return " AND (n.title LIKE ? OR n.description LIKE ?)"

    def _append_news_scope_clause(
        self: DatabaseManager,
        params: List[Any],
        keyword: str,
        query_key: Optional[str],
        alias: str = "nk",
    ) -> str:
        normalized_query_key = str(query_key or "").strip()
        if normalized_query_key:
            params.append(normalized_query_key)
            return f"{alias}.query_key = ?"

        clause = f"{alias}.keyword = ?"
        params.append(keyword)
        return clause

    def _normalize_publisher_match_values(self: DatabaseManager, values: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for item in values or []:
            text = " ".join(str(item or "").strip().split()).casefold()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _append_publisher_match_clause(
        self: DatabaseManager,
        params: List[Any],
        publisher_expr: str,
        values: List[str],
    ) -> str:
        match_clauses: List[str] = []
        for value in values:
            if "." in value:
                match_clauses.append(f"({publisher_expr} = ? OR {publisher_expr} LIKE ?)")
                params.extend([value, f"%.{value}"])
            else:
                match_clauses.append(f"{publisher_expr} = ?")
                params.append(value)
        if not match_clauses:
            return ""
        return "(" + " OR ".join(match_clauses) + ")"

    def _append_visibility_filter_clause(
        self: DatabaseManager,
        params: List[Any],
        *,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
    ) -> str:
        clauses: List[str] = []
        publisher_expr = "LOWER(COALESCE(n.publisher, ''))"
        blocked = self._normalize_publisher_match_values(blocked_publishers)
        preferred = self._normalize_publisher_match_values(preferred_publishers)
        if blocked:
            match_clause = self._append_publisher_match_clause(params, publisher_expr, blocked)
            if match_clause:
                clauses.append(f"NOT {match_clause}")
        if only_preferred_publishers:
            if preferred:
                match_clause = self._append_publisher_match_clause(params, publisher_expr, preferred)
                clauses.append(match_clause if match_clause else "1 = 0")
            else:
                clauses.append("1 = 0")
        normalized_tag = str(tag_filter or "").strip()
        if normalized_tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM news_tags nt WHERE nt.link = n.link AND LOWER(nt.tag) = LOWER(?))"
            )
            params.append(normalized_tag)
        if not clauses:
            return ""
        return " AND " + " AND ".join(clauses)

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

    def _archive_base_select(self: DatabaseManager) -> str:
        return """
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
            WHERE 1 = 1
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
            query += " AND COALESCE(n.notes, '') LIKE ?"
            params.append(f"%{raw_notes}%")

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
                self._archive_base_select(),
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
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        owns_connection = conn is None
        active_conn = conn
        try:
            if active_conn is None:
                active_conn = self.get_connection()
            params: List[Any] = []
            query = self._append_archive_filters(
                "SELECT COUNT(*) FROM news n WHERE 1 = 1",
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
                params: List[Any] = []
                fts_match = self._fts_match_expression(filter_txt)
                if only_bookmark:
                    query = "SELECT COUNT(*) FROM news n WHERE n.is_bookmarked = 1"
                else:
                    query = (
                        "SELECT COUNT(*) FROM news n "
                        "JOIN news_keywords nk ON nk.link = n.link "
                        "WHERE "
                        + self._append_news_scope_clause(params, keyword, query_key)
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
            raise self._new_query_error("count_news", e) from e
        finally:
            if managed_conn and conn is not None:
                self.return_connection(conn)

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
                    + " AND n.is_read = 0"
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
                query = "SELECT COUNT(*) FROM news n WHERE n.is_read = 0"
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
