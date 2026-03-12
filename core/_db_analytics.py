# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseAnalyticsMixin:
    def get_statistics(self: DatabaseManager) -> Dict[str, int]:
        """통계 정보"""
        conn = self.get_connection()
        try:
            stats = {}
            stats["total"] = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            stats["unread"] = conn.execute("SELECT COUNT(*) FROM news WHERE is_read=0").fetchone()[0]
            stats["bookmarked"] = conn.execute("SELECT COUNT(*) FROM news WHERE is_bookmarked=1").fetchone()[0]
            stats["with_notes"] = conn.execute("SELECT COUNT(*) FROM news WHERE notes IS NOT NULL AND notes != ''").fetchone()[0]
            stats["duplicates"] = conn.execute(
                "SELECT COUNT(DISTINCT link) FROM news_keywords WHERE is_duplicate=1"
            ).fetchone()[0]
            return stats
        except Exception as e:
            logger.error(f"get_statistics 오류: {e}")
            return {"total": 0, "unread": 0, "bookmarked": 0, "with_notes": 0, "duplicates": 0}
        finally:
            self.return_connection(conn)

    def get_top_publishers(
        self: DatabaseManager,
        keyword: Optional[str] = None,
        limit: int = 10,
        exclude_words: Optional[List[str]] = None,
    ) -> List[Tuple[str, int]]:
        """주요 언론사 통계"""
        conn = self.get_connection()
        try:
            params: List[Any] = []
            if keyword:
                query = """
                    SELECT n.publisher, COUNT(*) as count
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword=?
                """
                params.append(keyword)
            else:
                query = """
                    SELECT n.publisher, COUNT(*) as count
                    FROM news n
                    WHERE 1=1
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
            return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_top_publishers 오류: {e}")
            return []
        finally:
            self.return_connection(conn)
