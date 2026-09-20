
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple, cast

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)

# A soft-deleted row is a tombstone kept so cloud sync can propagate the delete
# to other machines. Once it is older than the retention window there is nothing
# left to propagate, so it becomes reclaimable. delete_updated_at is the real
# signal; created_at is the fallback for rows whose delete timestamp was never
# recorded, so no tombstone can become permanently unreclaimable.
_TOMBSTONE_AGE_SQL = "COALESCE(NULLIF(delete_updated_at, 0), created_at, 0)"
_EXPIRED_TOMBSTONE_SQL = (
    f"COALESCE(is_deleted, 0) = 1 AND {_TOMBSTONE_AGE_SQL} > 0 AND {_TOMBSTONE_AGE_SQL} < ?"
)


class _NewsDeletionMaintenanceMixin:
    def delete_old_news(self: DatabaseManager, days: int) -> int:
        """Delete old non-bookmarked rows and repair duplicates."""
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        try:
            return self.delete_old_news_chunked(days, operation="delete_old_news")
        except sqlite3.Error as e:
            logger.error("delete_old_news failed: %s", e)
            raise self._new_write_error("delete_old_news", e) from e

    def delete_all_news(self: DatabaseManager) -> int:
        """Delete all non-bookmarked rows and repair duplicates."""
        try:
            return self.delete_all_news_chunked(operation="delete_all_news")
        except sqlite3.Error as e:
            logger.error("delete_all_news failed: %s", e)
            raise self._new_write_error("delete_all_news", e) from e

    def _dedupe_links(self: DatabaseManager, links: List[str]) -> List[str]:
        deduped_links: List[str] = []
        for link in links:
            if isinstance(link, str) and link and link not in deduped_links:
                deduped_links.append(link)
        return deduped_links

    def _run_chunked_news_delete(
        self: DatabaseManager,
        where_sql: str,
        params: List[Any],
        *,
        chunk_size: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        operation: str,
    ) -> int:
        conn = self.get_connection()
        deleted_total = 0
        safe_chunk_size = max(1, int(chunk_size or 200))
        try:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM news WHERE {where_sql}",
                    params,
                ).fetchone()[0]
                or 0
            )
            batch_query = f"SELECT link FROM news WHERE {where_sql} ORDER BY link LIMIT ?"
            while True:
                if callable(cancel_check):
                    cancel_check()
                rows = conn.execute(batch_query, [*params, safe_chunk_size]).fetchall()
                links = [str(row[0]) for row in rows if row and row[0]]
                if not links:
                    break
                placeholders = ",".join(["?"] * len(links))
                with conn:
                    affected = self._collect_affected_query_key_hashes(
                        conn,
                        f"n.link IN ({placeholders})",
                        links,
                    )
                    cursor = conn.execute(
                        f"DELETE FROM news_tags WHERE link IN ({placeholders})",
                        links,
                    )
                    conn.execute(
                        f"DELETE FROM news_tag_state WHERE link IN ({placeholders})",
                        links,
                    )
                    cursor = conn.execute(
                        f"DELETE FROM news WHERE link IN ({placeholders})",
                        links,
                    )
                    deleted = int(cursor.rowcount or 0)
                    if deleted > 0:
                        self._recalculate_duplicates_for_affected(conn, affected)
                deleted_total += deleted
                if callable(progress_callback):
                    progress_callback(deleted_total, total)
                if deleted <= 0:
                    break
            return deleted_total
        except sqlite3.Error as e:
            logger.error("%s failed: %s", operation, e)
            raise self._new_write_error(operation, e) from e
        finally:
            self.return_connection(conn)

    def _tombstone_cutoff_timestamp(
        self: DatabaseManager,
        retention_days: Optional[int] = None,
    ) -> float:
        """Timestamp before which a soft-deleted row may be reclaimed.

        Returns 0.0 when retention is disabled (0 days). Because the tombstone
        predicate also requires ``age > 0``, a cutoff of 0.0 matches nothing and
        tombstones are kept forever.
        """
        days = self.TOMBSTONE_RETENTION_DAYS if retention_days is None else retention_days
        safe_days = max(0, int(days or 0))
        if safe_days <= 0:
            return 0.0
        return (datetime.now() - timedelta(days=safe_days)).timestamp()

    def count_reclaimable_tombstones(
        self: DatabaseManager,
        retention_days: Optional[int] = None,
    ) -> Tuple[int, int]:
        """Return (reclaimable_now, total) soft-deleted non-bookmarked rows."""
        conn = self.get_connection()
        try:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) FROM news WHERE COALESCE(is_deleted, 0) = 1 AND is_bookmarked = 0"
                ).fetchone()[0]
                or 0
            )
            reclaimable = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM news WHERE is_bookmarked = 0 AND {_EXPIRED_TOMBSTONE_SQL}",
                    [self._tombstone_cutoff_timestamp(retention_days)],
                ).fetchone()[0]
                or 0
            )
            return reclaimable, total
        except sqlite3.Error as e:
            logger.error("count_reclaimable_tombstones failed: %s", e)
            raise self._new_query_error("count_reclaimable_tombstones", e) from e
        finally:
            self.return_connection(conn)

    def delete_old_news_chunked(
        self: DatabaseManager,
        days: int,
        *,
        chunk_size: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        operation: str = "delete_old_news_chunked",
        tombstone_retention_days: Optional[int] = None,
    ) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        return self._run_chunked_news_delete(
            "is_bookmarked = 0 AND ("
            "("
            "COALESCE(is_deleted, 0) = 0 AND ("
            "(pubDate_ts > 0 AND pubDate_ts < ?) OR "
            "((pubDate_ts IS NULL OR pubDate_ts <= 0) AND COALESCE(created_at, 0) > 0 AND created_at < ?)"
            ")"
            ") OR "
            f"({_EXPIRED_TOMBSTONE_SQL})"
            ")",
            [cutoff, cutoff, self._tombstone_cutoff_timestamp(tombstone_retention_days)],
            chunk_size=chunk_size,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            operation=operation,
        )

    def delete_all_news_chunked(
        self: DatabaseManager,
        *,
        chunk_size: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        operation: str = "delete_all_news_chunked",
        tombstone_retention_days: Optional[int] = None,
    ) -> int:
        return self._run_chunked_news_delete(
            "is_bookmarked = 0 AND ("
            "COALESCE(is_deleted, 0) = 0 OR "
            f"({_EXPIRED_TOMBSTONE_SQL})"
            ")",
            [self._tombstone_cutoff_timestamp(tombstone_retention_days)],
            chunk_size=chunk_size,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            operation=operation,
        )
