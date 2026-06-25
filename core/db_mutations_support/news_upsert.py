# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, cast

from core.content_filters import normalize_tags
from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts, perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsUpsertResult:
    added_count: int
    duplicate_count: int
    new_links: Tuple[str, ...] = ()


class _NewsUpsertMixin:
    def _resolve_query_key(self: DatabaseManager, keyword: str, query_key: Optional[str]) -> str:
        normalized_query_key = str(query_key or "").strip()
        if normalized_query_key:
            return normalized_query_key
        return build_fetch_key(str(keyword or "").strip(), [])
    def _append_query_scope_sql(
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

        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword:
            params.append(normalized_keyword)
            return f"{alias}.keyword = ?"

        params.append(self._resolve_query_key(keyword, None))
        return f"{alias}.query_key = ?"
    def upsert_news(
        self: DatabaseManager,
        items: List[Dict[str, Any]],
        keyword: str,
        query_key: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Insert or update rows and maintain query-scoped duplicate flags."""
        result = self.upsert_news_detailed(items, keyword, query_key=query_key)
        return result.added_count, result.duplicate_count

    def upsert_news_detailed(
        self: DatabaseManager,
        items: List[Dict[str, Any]],
        keyword: str,
        query_key: Optional[str] = None,
    ) -> NewsUpsertResult:
        """Insert or update rows and return detailed scope-new link metadata."""
        if not items:
            return NewsUpsertResult(0, 0, ())

        scope_query_key = self._resolve_query_key(keyword, query_key)
        added_count = 0
        duplicate_count = 0
        new_links: List[str] = []
        conn = None

        try:
            conn = self.get_connection()
            with perf_timer(
                "db.upsert_news_detailed",
                f"kw={keyword}|query_key={scope_query_key}|items={len(items)}",
            ):
                prepared_by_link: Dict[str, Dict[str, Any]] = {}
                link_order: List[str] = []

                for item in items:
                    link = str(item.get("link", "") or "").strip()
                    if not link:
                        continue
                    if link not in prepared_by_link:
                        link_order.append(link)
                    pub_date = item.get("pubDate", "")
                    title = item.get("title", "")
                    title_hash = self._calculate_title_hash(title)
                    prepared_by_link[link] = {
                        "link": link,
                        "keyword": keyword,
                        "query_key": scope_query_key,
                        "title": title,
                        "description": item.get("description", ""),
                        "pubDate": pub_date,
                        "publisher": item.get("publisher", ""),
                        "pubDate_ts": parse_date_to_ts(pub_date),
                        "title_hash": title_hash,
                    }

                prepared_items = [prepared_by_link[link] for link in link_order]

                with conn:
                    unique_hashes = sorted(
                        {
                            str(item.get("title_hash", "") or "").strip()
                            for item in prepared_items
                            if str(item.get("title_hash", "") or "").strip()
                        }
                    )
                    incoming_links = sorted(link_order)

                    existing_links_by_hash: Dict[str, Set[str]] = {}
                    if unique_hashes:
                        hash_placeholders = ",".join(["?"] * len(unique_hashes))
                        hash_rows = conn.execute(
                            f"""
                            SELECT n.title_hash, nk.link
                            FROM news n
                            JOIN news_keywords nk ON nk.link = n.link
                            WHERE nk.query_key = ?
                              AND n.title_hash IN ({hash_placeholders})
                              AND COALESCE(n.is_deleted, 0) = 0
                            """,
                            [scope_query_key] + unique_hashes,
                        ).fetchall()
                        for row in hash_rows:
                            title_hash = str(row[0] or "")
                            link = str(row[1] or "")
                            existing_links_by_hash.setdefault(title_hash, set()).add(link)

                    existing_hash_by_link: Dict[str, str] = {}
                    if incoming_links:
                        link_placeholders = ",".join(["?"] * len(incoming_links))
                        link_rows = conn.execute(
                            f"""
                            SELECT nk.link, COALESCE(n.title_hash, '')
                            FROM news_keywords nk
                            JOIN news n ON n.link = nk.link
                            WHERE nk.query_key = ? AND nk.link IN ({link_placeholders})
                            """,
                            [scope_query_key] + incoming_links,
                        ).fetchall()
                        for row in link_rows:
                            existing_hash_by_link[str(row[0] or "")] = str(row[1] or "")

                    news_insert_data: List[Tuple[Any, ...]] = []
                    scope_insert_data: List[Tuple[Any, ...]] = []
                    affected_hashes: Set[str] = set()

                    for item in prepared_items:
                        link = item.get("link", "")
                        title_hash = item["title_hash"]
                        if not isinstance(link, str) or not link:
                            continue

                        hash_links = existing_links_by_hash.setdefault(title_hash, set())
                        previous_hash = existing_hash_by_link.get(link)
                        same_link_exists = previous_hash is not None
                        has_other_link = any(existing_link != link for existing_link in hash_links)

                        if same_link_exists:
                            is_dup = has_other_link
                            if previous_hash and previous_hash != title_hash:
                                affected_hashes.add(previous_hash)
                                affected_hashes.add(title_hash)
                        else:
                            new_links.append(link)
                            affected_hashes.add(title_hash)
                            if has_other_link:
                                duplicate_count += 1
                                is_dup = True
                            else:
                                added_count += 1
                                is_dup = False

                        news_insert_data.append(
                            (
                                link,
                                item["keyword"],
                                item["title"],
                                item["description"],
                                item["pubDate"],
                                item["publisher"],
                                item["pubDate_ts"],
                                item["title_hash"],
                            )
                        )
                        scope_insert_data.append(
                            (link, keyword, scope_query_key, 1 if is_dup else 0)
                        )
                        hash_links.add(link)
                        existing_hash_by_link[link] = title_hash

                    if not news_insert_data:
                        return NewsUpsertResult(0, 0, ())

                    conn.executemany(
                        """
                        INSERT INTO news
                        (link, keyword, title, description, pubDate, publisher, pubDate_ts, title_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(link) DO UPDATE SET
                            keyword = CASE
                                WHEN keyword IS NULL OR keyword = '' THEN excluded.keyword
                                ELSE keyword
                            END,
                            title = excluded.title,
                            description = excluded.description,
                            pubDate = excluded.pubDate,
                            publisher = excluded.publisher,
                            pubDate_ts = CASE
                                WHEN excluded.pubDate_ts > 0 THEN excluded.pubDate_ts
                                ELSE news.pubDate_ts
                            END,
                            title_hash = excluded.title_hash
                        WHERE
                            (
                                (news.keyword IS NULL OR news.keyword = '')
                                AND COALESCE(excluded.keyword, '') != ''
                            )
                            OR COALESCE(news.title, '') != COALESCE(excluded.title, '')
                            OR COALESCE(news.description, '') != COALESCE(excluded.description, '')
                            OR COALESCE(news.pubDate, '') != COALESCE(excluded.pubDate, '')
                            OR COALESCE(news.publisher, '') != COALESCE(excluded.publisher, '')
                            OR (
                                excluded.pubDate_ts > 0
                                AND COALESCE(news.pubDate_ts, 0) != COALESCE(excluded.pubDate_ts, 0)
                            )
                            OR COALESCE(news.title_hash, '') != COALESCE(excluded.title_hash, '')
                        """,
                        news_insert_data,
                    )

                    conn.executemany(
                        """
                        INSERT INTO news_keywords (link, keyword, query_key, is_duplicate)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(link, query_key) DO UPDATE SET
                            keyword = excluded.keyword,
                            is_duplicate = excluded.is_duplicate
                        WHERE
                            COALESCE(news_keywords.keyword, '') != COALESCE(excluded.keyword, '')
                            OR COALESCE(news_keywords.is_duplicate, 0) != COALESCE(excluded.is_duplicate, 0)
                        """,
                        scope_insert_data,
                    )

                    if affected_hashes:
                        self._recalculate_duplicate_flags_for_query_key_hashes(
                            conn,
                            scope_query_key,
                            list(affected_hashes),
                        )

            return NewsUpsertResult(added_count, duplicate_count, tuple(new_links))
        except sqlite3.Error as e:
            logger.error("DB batch upsert failed: %s", e)
            raise self._new_write_error("upsert_news", e) from e
        except Exception as e:
            logger.error("DB batch upsert connection failed: %s", e)
            raise self._new_write_error("upsert_news", e) from e
        finally:
            if conn is not None:
                self.return_connection(conn)
