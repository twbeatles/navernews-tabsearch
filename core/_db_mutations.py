# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts, perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseMutationsMixin:
    ALLOWED_UPDATE_FIELDS = {"is_read", "is_bookmarked", "notes", "is_duplicate"}

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
        resolved_query_key = self._resolve_query_key(keyword, query_key)
        clause = f"{alias}.query_key = ?"
        params.append(resolved_query_key)
        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword:
            clause += f" AND {alias}.keyword = ?"
            params.append(normalized_keyword)
        return clause

    def upsert_news(
        self: DatabaseManager,
        items: List[Dict[str, Any]],
        keyword: str,
        query_key: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Insert or update rows and maintain query-scoped duplicate flags."""
        if not items:
            return 0, 0

        scope_query_key = self._resolve_query_key(keyword, query_key)
        conn = self.get_connection()
        added_count = 0
        duplicate_count = 0

        try:
            with perf_timer(
                "db.upsert_news",
                f"kw={keyword}|query_key={scope_query_key}|items={len(items)}",
            ):
                prepared_items: List[Dict[str, Any]] = []
                hashes: List[str] = []

                for item in items:
                    pub_date = item.get("pubDate", "")
                    title = item.get("title", "")
                    title_hash = self._calculate_title_hash(title)
                    hashes.append(title_hash)
                    prepared_items.append(
                        {
                            "link": item.get("link", ""),
                            "keyword": keyword,
                            "query_key": scope_query_key,
                            "title": title,
                            "description": item.get("description", ""),
                            "pubDate": pub_date,
                            "publisher": item.get("publisher", ""),
                            "pubDate_ts": parse_date_to_ts(pub_date),
                            "title_hash": title_hash,
                        }
                    )

                with conn:
                    unique_hashes = sorted({h for h in hashes if h})
                    incoming_links = sorted(
                        {item.get("link", "") for item in prepared_items if item.get("link", "")}
                    )

                    existing_links_by_hash: Dict[str, Set[str]] = {}
                    if unique_hashes:
                        hash_placeholders = ",".join(["?"] * len(unique_hashes))
                        hash_rows = conn.execute(
                            f"""
                            SELECT n.title_hash, nk.link
                            FROM news n
                            JOIN news_keywords nk ON nk.link = n.link
                            WHERE nk.query_key = ? AND n.title_hash IN ({hash_placeholders})
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
                    affected_hashes: Set[str] = set(unique_hashes)

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
                        else:
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
                        return 0, 0

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
                                ELSE pubDate_ts
                            END,
                            title_hash = excluded.title_hash
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
                        """,
                        scope_insert_data,
                    )

                    self._recalculate_duplicate_flags_for_query_key_hashes(
                        conn,
                        scope_query_key,
                        list(affected_hashes),
                    )

            return added_count, duplicate_count
        except sqlite3.Error as e:
            logger.error("DB batch upsert failed: %s", e)
            raise self._new_write_error("upsert_news", e) from e
        finally:
            self.return_connection(conn)

    def update_status(self: DatabaseManager, link: str, field: str, value) -> bool:
        """Update a safe allow-listed status field."""
        if field not in self.ALLOWED_UPDATE_FIELDS:
            logger.error("Rejected update for unsupported field: %s", field)
            return False

        conn = self.get_connection()
        try:
            with conn:
                conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return True
        except sqlite3.Error as e:
            logger.error("DB update failed: %s", e)
            return False
        finally:
            self.return_connection(conn)

    def save_note(self: DatabaseManager, link: str, note: str) -> bool:
        return self.update_status(link, "notes", note)

    def delete_link(self: DatabaseManager, link: str) -> bool:
        """Delete a single article and repair duplicate flags."""
        if not isinstance(link, str) or not link.strip():
            return False

        conn = self.get_connection()
        try:
            with conn:
                affected = self._collect_affected_query_key_hashes(conn, "n.link = ?", [link])
                cursor = conn.execute("DELETE FROM news WHERE link = ?", (link,))
                deleted = int(cursor.rowcount or 0)
                if deleted <= 0:
                    return False
                self._recalculate_duplicates_for_affected(conn, affected)
            return True
        except Exception as e:
            logger.error("delete_link failed: %s", e)
            return False
        finally:
            self.return_connection(conn)

    def get_note(self: DatabaseManager, link: str) -> str:
        conn = self.get_connection()
        try:
            result = conn.execute("SELECT notes FROM news WHERE link = ?", (link,)).fetchone()
            return str(result[0]) if result and result[0] else ""
        except Exception as e:
            logger.error("get_note failed: %s", e)
            return ""
        finally:
            self.return_connection(conn)

    def delete_old_news(self: DatabaseManager, days: int) -> int:
        """Delete old non-bookmarked rows and repair duplicates."""
        conn = self.get_connection()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        try:
            with conn:
                affected = self._collect_affected_query_key_hashes(
                    conn,
                    "n.is_bookmarked = 0 AND n.pubDate_ts > 0 AND n.pubDate_ts < ?",
                    [cutoff],
                )
                cur = conn.execute(
                    "DELETE FROM news WHERE is_bookmarked = 0 AND pubDate_ts > 0 AND pubDate_ts < ?",
                    (cutoff,),
                )
                deleted = int(cur.rowcount or 0)
                if deleted > 0:
                    self._recalculate_duplicates_for_affected(conn, affected)
                return deleted
        except Exception as e:
            logger.error("delete_old_news failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

    def delete_all_news(self: DatabaseManager) -> int:
        """Delete all non-bookmarked rows and repair duplicates."""
        conn = self.get_connection()
        try:
            with conn:
                affected = self._collect_affected_query_key_hashes(conn, "n.is_bookmarked = 0", [])
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked = 0")
                deleted = int(cur.rowcount or 0)
                if deleted > 0:
                    self._recalculate_duplicates_for_affected(conn, affected)
                return deleted
        except Exception as e:
            logger.error("delete_all_news failed: %s", e)
            return 0
        finally:
            self.return_connection(conn)

    def _dedupe_links(self: DatabaseManager, links: List[str]) -> List[str]:
        deduped_links: List[str] = []
        for link in links:
            if isinstance(link, str) and link and link not in deduped_links:
                deduped_links.append(link)
        return deduped_links

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
            cursor = conn.execute(
                f"UPDATE news SET is_read = 1 WHERE is_read = 0 AND link IN ({placeholders})",
                chunk,
            )
            if cursor.rowcount and cursor.rowcount > 0:
                updated_count += int(cursor.rowcount)
        return updated_count

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
                    cursor = conn.execute(
                        "UPDATE news SET is_read = 1 WHERE is_bookmarked = 1 AND is_read = 0"
                    )
                else:
                    params: List[Any] = []
                    cursor = conn.execute(
                        """
                        UPDATE news
                        SET is_read = 1
                        WHERE is_read = 0
                          AND link IN (
                              SELECT link FROM news_keywords nk
                              WHERE
                        """
                        + self._append_query_scope_sql(params, keyword, query_key)
                        + ")",
                        params,
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
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query_key: Optional[str] = None,
    ) -> int:
        """Mark unread rows in the current query scope as read."""
        conn = self.get_connection()
        try:
            params: List[Any] = []
            if only_bookmark:
                scope_query = "SELECT n.link FROM news n WHERE n.is_bookmarked = 1 AND n.is_read = 0"
            else:
                scope_query = (
                    "SELECT n.link FROM news n "
                    "JOIN news_keywords nk ON nk.link = n.link "
                    "WHERE "
                    + self._append_query_scope_sql(params, keyword, query_key)
                    + " AND n.is_read = 0"
                )

            if hide_duplicates:
                if only_bookmark:
                    scope_query += (
                        " AND NOT EXISTS ("
                        "SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                    )
                else:
                    scope_query += " AND nk.is_duplicate = 0"

            if filter_txt:
                scope_query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                wildcard = f"%{filter_txt}%"
                params.extend([wildcard, wildcard])

            if exclude_words:
                for exclude_word in exclude_words:
                    if not exclude_word:
                        continue
                    scope_query += " AND NOT (n.title LIKE ? OR n.description LIKE ?)"
                    wildcard = f"%{exclude_word}%"
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

            query = (
                "UPDATE news SET is_read = 1 WHERE is_read = 0 AND link IN ("
                + scope_query
                + ")"
            )
            with conn:
                cursor = conn.execute(query, params)
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error("mark_query_as_read failed: %s", e)
            raise
        finally:
            self.return_connection(conn)
