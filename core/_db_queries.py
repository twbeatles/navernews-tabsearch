# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.text_utils import perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseQueriesMixin:
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
    ) -> List[Dict[str, Any]]:
        """뉴스 조회 - 안전한 버전 (날짜 필터 추가)"""
        conn = self.get_connection()
        news_items: List[Dict[str, Any]] = []
        scope_meta = (
            f"kw={keyword}|bookmark={int(only_bookmark)}|unread={int(only_unread)}|"
            f"hide_dup={int(hide_duplicates)}|ex={len(exclude_words) if exclude_words else 0}|"
            f"limit={limit}|offset={offset}"
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
                        WHERE nk.keyword = ?
                        """
                    )
                    params.append(keyword)

                if only_unread:
                    query += " AND n.is_read = 0"

                if hide_duplicates:
                    if only_bookmark:
                        query += " AND NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
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
                        logger.warning(f"Invalid start_date format: {start_date}")

                if end_date:
                    try:
                        e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                        query += " AND n.pubDate_ts < ?"
                        params.append(e_ts)
                    except ValueError:
                        logger.warning(f"Invalid end_date format: {end_date}")

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
            logger.error(f"뉴스 조회 오류: {e}")
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
    ) -> int:
        """뉴스 개수 조회 (필터 적용)."""
        conn = self.get_connection()
        scope_meta = (
            f"kw={keyword}|bookmark={int(only_bookmark)}|unread={int(only_unread)}|"
            f"hide_dup={int(hide_duplicates)}"
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
                        "WHERE nk.keyword = ?"
                    )
                    params.append(keyword)

                if only_unread:
                    query += " AND n.is_read = 0"

                if hide_duplicates:
                    if only_bookmark:
                        query += " AND NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
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
                        logger.warning(f"Invalid start_date format: {start_date}")

                if end_date:
                    try:
                        e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                        query += " AND n.pubDate_ts < ?"
                        params.append(e_ts)
                    except ValueError:
                        logger.warning(f"Invalid end_date format: {end_date}")

                cursor = conn.execute(query, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"count_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_counts(self: DatabaseManager, keyword: str) -> int:
        """특정 키워드 뉴스 개수"""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_counts", f"kw={keyword}"):
                cursor = conn.execute("SELECT COUNT(*) FROM news_keywords WHERE keyword=?", (keyword,))
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_counts 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_unread_count(self: DatabaseManager, keyword: str) -> int:
        """안 읽은 뉴스 개수"""
        conn = self.get_connection()
        try:
            with perf_timer("db.get_unread_count", f"kw={keyword}"):
                cursor = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword = ? AND n.is_read = 0
                    """,
                    (keyword,),
                )
                return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_unread_count 오류: {e}")
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
            logger.error(f"get_total_unread_count 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_unread_counts_by_keywords(
        self: DatabaseManager,
        keywords: List[str],
    ) -> Dict[str, int]:
        """여러 키워드의 미읽음 기사 개수를 한 번에 조회."""
        if not keywords:
            return {}

        cleaned = [k for k in keywords if isinstance(k, str) and k.strip()]
        if not cleaned:
            return {}

        conn = self.get_connection()
        try:
            with perf_timer("db.get_unread_counts_by_keywords", f"kw_count={len(cleaned)}"):
                placeholders = ",".join(["?"] * len(cleaned))
                query = f"""
                    SELECT nk.keyword, COUNT(*) AS unread_count
                    FROM news_keywords nk
                    JOIN news n ON n.link = nk.link
                    WHERE nk.keyword IN ({placeholders}) AND n.is_read = 0
                    GROUP BY nk.keyword
                """
                rows = conn.execute(query, cleaned).fetchall()
                unread_by_kw: Dict[str, int] = {k: 0 for k in cleaned}
                for row in rows:
                    unread_by_kw[str(row[0])] = int(row[1])
                return unread_by_kw
        except Exception as e:
            logger.error(f"get_unread_counts_by_keywords 오류: {e}")
            return {k: 0 for k in cleaned}
        finally:
            self.return_connection(conn)
