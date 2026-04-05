# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseAnalyticsMixin:
    def get_statistics(self: DatabaseManager) -> Dict[str, int]:
        """Return top-level database statistics."""
        conn = None
        try:
            conn = self.get_connection()
            stats = {}
            stats["total"] = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            stats["unread"] = conn.execute("SELECT COUNT(*) FROM news WHERE is_read = 0").fetchone()[0]
            stats["bookmarked"] = conn.execute(
                "SELECT COUNT(*) FROM news WHERE is_bookmarked = 1"
            ).fetchone()[0]
            stats["with_notes"] = conn.execute(
                "SELECT COUNT(*) FROM news WHERE notes IS NOT NULL AND notes != ''"
            ).fetchone()[0]
            stats["duplicates"] = conn.execute(
                "SELECT COUNT(DISTINCT link) FROM news_keywords WHERE is_duplicate = 1"
            ).fetchone()[0]
            return stats
        except Exception as e:
            logger.error("get_statistics failed: %s", e)
            raise self._new_query_error("get_statistics", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)

    def get_top_publishers(
        self: DatabaseManager,
        keyword: Optional[str] = None,
        limit: int = 10,
        exclude_words: Optional[List[str]] = None,
        query_key: Optional[str] = None,
    ) -> List[Tuple[str, int]]:
        """Return publisher counts for all news or a specific tab scope."""
        conn = None
        try:
            conn = self.get_connection()
            params: List[Any] = []
            if query_key:
                query = """
                    SELECT n.publisher, COUNT(*) as count
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.query_key = ?
                """
                params.append(query_key)
                if keyword:
                    query += " AND nk.keyword = ?"
                    params.append(keyword)
            elif keyword:
                query = """
                    SELECT n.publisher, COUNT(*) as count
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword = ?
                """
                params.append(keyword)
            else:
                query = """
                    SELECT n.publisher, COUNT(*) as count
                    FROM news n
                    WHERE 1 = 1
                """

            if exclude_words:
                for exclude_word in exclude_words:
                    if not exclude_word:
                        continue
                    query += " AND NOT (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{exclude_word}%"
                    params.extend([wildcard, wildcard])

            query += """
                GROUP BY n.publisher
                ORDER BY count DESC
                LIMIT ?
            """
            params.append(limit)
            cursor = conn.execute(query, params)
            return [(str(row[0]), int(row[1])) for row in cursor.fetchall()]
        except Exception as e:
            logger.error("get_top_publishers failed: %s", e)
            raise self._new_query_error("get_top_publishers", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)
