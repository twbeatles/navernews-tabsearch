
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple, cast

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _NewsReadMaintenanceMixin:
    def _mark_links_as_read_with_conn(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        links: List[str],
    ) -> int:
        deduped_links = self._dedupe_links(links)
        if not deduped_links:
            return 0

        updated_count = 0
        chunk_size = 400
        for idx in range(0, len(deduped_links), chunk_size):
            chunk = deduped_links[idx: idx + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            now_ts = datetime.now().timestamp()
            cursor = conn.execute(
                f"""
                UPDATE news
                SET is_read = 1, read_updated_at = ?
                WHERE is_read = 0
                  AND COALESCE(is_deleted, 0) = 0
                  AND link IN ({placeholders})
                """,
                [now_ts, *chunk],
            )
            if cursor.rowcount and cursor.rowcount > 0:
                updated_count += int(cursor.rowcount)
        return updated_count

    def _build_mark_query_scope_sql(
        self: DatabaseManager,
        keyword: str,
        exclude_words: Optional[List[str]] = None,
        only_bookmark: bool = False,
        filter_txt: str = "",
        hide_duplicates: bool = False,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        params: List[Any] = []
        if only_bookmark:
            scope_query = (
                "SELECT n.link FROM news n "
                "WHERE n.is_bookmarked = 1 AND n.is_read = 0 AND COALESCE(n.is_deleted, 0) = 0"
            )
        else:
            scope_query = (
                "SELECT n.link FROM news n "
                "JOIN news_keywords nk ON nk.link = n.link "
                "WHERE "
                + self._append_query_scope_sql(params, keyword, query_key)
                + " AND n.is_read = 0 AND COALESCE(n.is_deleted, 0) = 0"
            )

        if hide_duplicates:
            if only_bookmark:
                scope_query += (
                    " AND NOT EXISTS ("
                    "SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                )
            else:
                scope_query += " AND nk.is_duplicate = 0"

        append_visibility = getattr(self, "_append_visibility_filter_clause", None)
        if callable(append_visibility):
            scope_query += cast(str, append_visibility(
                params,
                blocked_publishers=blocked_publishers,
                preferred_publishers=preferred_publishers,
                only_preferred_publishers=only_preferred_publishers,
                tag_filter=tag_filter,
            ))

        append_text_filter = getattr(self, "_append_text_filter_clause", None)
        if callable(append_text_filter):
            scope_query += cast(str, append_text_filter(params, filter_txt))
        elif filter_txt:
            scope_query += " AND (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')"
            wildcard = self._like_contains(filter_txt)
            params.extend([wildcard, wildcard])

        if exclude_words:
            for exclude_word in exclude_words:
                if not exclude_word:
                    continue
                scope_query += " AND NOT (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')"
                wildcard = self._like_contains(exclude_word)
                params.extend([wildcard, wildcard])

        if start_date:
            try:
                s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                scope_query += " AND n.pubDate_ts >= ?"
                params.append(s_ts)
            except ValueError:
                logger.warning("Invalid start_date format for mark_query_as_read: %s", start_date)

        if end_date:
            try:
                e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                scope_query += " AND n.pubDate_ts < ?"
                params.append(e_ts)
            except ValueError:
                logger.warning("Invalid end_date format for mark_query_as_read: %s", end_date)

        return scope_query, params

    def mark_links_as_read(self: DatabaseManager, links: List[str]) -> int:
        """Mark selected links as read."""
        if not links:
            return 0

        conn = self.get_connection()
        try:
            with conn:
                return self._mark_links_as_read_with_conn(conn, links)
        except Exception as e:
            logger.error("mark_links_as_read failed: %s", e)
            raise
        finally:
            self.return_connection(conn)

    def mark_all_as_read(
        self: DatabaseManager,
        keyword: str,
        only_bookmark: bool,
        query_key: Optional[str] = None,
    ) -> int:
        """Mark the entire scope as read."""
        conn = self.get_connection()
        try:
            with conn:
                if only_bookmark:
                    now_ts = datetime.now().timestamp()
                    cursor = conn.execute(
                        """
                        UPDATE news
                        SET is_read = 1, read_updated_at = ?
                        WHERE is_bookmarked = 1
                          AND is_read = 0
                          AND COALESCE(is_deleted, 0) = 0
                        """,
                        (now_ts,),
                    )
                else:
                    now_ts = datetime.now().timestamp()
                    params: List[Any] = []
                    cursor = conn.execute(
                        """
                        UPDATE news
                        SET is_read = 1, read_updated_at = ?
                        WHERE is_read = 0
                          AND COALESCE(is_deleted, 0) = 0
                          AND link IN (
                              SELECT link FROM news_keywords nk
                              WHERE
                        """
                        + self._append_query_scope_sql(params, keyword, query_key)
                        + ")",
                        [now_ts, *params],
                    )
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error("mark_all_as_read failed: %s", e)
            raise
        finally:
            self.return_connection(conn)

    def mark_query_as_read(
        self: DatabaseManager,
        keyword: str,
        exclude_words: Optional[List[str]] = None,
        only_bookmark: bool = False,
        filter_txt: str = "",
        hide_duplicates: bool = False,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
    ) -> int:
        """Mark unread rows in the current query scope as read."""
        conn = self.get_connection()
        try:
            scope_query, params = self._build_mark_query_scope_sql(
                keyword,
                exclude_words=exclude_words,
                only_bookmark=only_bookmark,
                filter_txt=filter_txt,
                hide_duplicates=hide_duplicates,
                blocked_publishers=blocked_publishers,
                preferred_publishers=preferred_publishers,
                only_preferred_publishers=only_preferred_publishers,
                tag_filter=tag_filter,
                start_date=start_date,
                end_date=end_date,
                query_key=query_key,
            )
            query = (
                "UPDATE news SET is_read = 1, read_updated_at = ? "
                "WHERE is_read = 0 AND COALESCE(is_deleted, 0) = 0 AND link IN ("
                + scope_query
                + ")"
            )
            with conn:
                cursor = conn.execute(query, [datetime.now().timestamp(), *params])
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error("mark_query_as_read failed: %s", e)
            raise
        finally:
            self.return_connection(conn)

    def mark_query_as_read_chunked(
        self: DatabaseManager,
        keyword: str,
        exclude_words: Optional[List[str]] = None,
        only_bookmark: bool = False,
        filter_txt: str = "",
        hide_duplicates: bool = False,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
        *,
        chunk_size: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> int:
        """Mark unread rows in the current query scope as read in cancel-aware batches."""
        conn = self.get_connection()
        updated_total = 0
        safe_chunk_size = max(1, int(chunk_size or 200))
        try:
            scope_query, params = self._build_mark_query_scope_sql(
                keyword,
                exclude_words=exclude_words,
                only_bookmark=only_bookmark,
                filter_txt=filter_txt,
                hide_duplicates=hide_duplicates,
                blocked_publishers=blocked_publishers,
                preferred_publishers=preferred_publishers,
                only_preferred_publishers=only_preferred_publishers,
                tag_filter=tag_filter,
                start_date=start_date,
                end_date=end_date,
                query_key=query_key,
            )
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM (" + scope_query + ")",
                    params,
                ).fetchone()[0]
                or 0
            )
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS temp_mark_query_seen_links (link TEXT PRIMARY KEY)"
            )
            conn.execute("DELETE FROM temp_mark_query_seen_links")
            batch_query = (
                "SELECT scoped.link FROM ("
                + scope_query
                + ") AS scoped "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM temp_mark_query_seen_links seen WHERE seen.link = scoped.link"
                ") "
                "ORDER BY scoped.link LIMIT ?"
            )
            while True:
                if callable(cancel_check):
                    cancel_check()
                rows = conn.execute(batch_query, [*params, safe_chunk_size]).fetchall()
                links = [str(row[0]) for row in rows if row and row[0]]
                if not links:
                    break
                with conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO temp_mark_query_seen_links (link) VALUES (?)",
                        [(link,) for link in links],
                    )
                    updated_total += self._mark_links_as_read_with_conn(conn, links)
                if callable(progress_callback):
                    progress_callback(updated_total, total)
            return updated_total
        except sqlite3.Error as e:
            logger.error("mark_query_as_read_chunked failed: %s", e)
            raise self._new_write_error("mark_query_as_read_chunked", e) from e
        finally:
            self.return_connection(conn)
