# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, cast

from core.content_filters import normalize_tags
from core.query_parser import build_fetch_key
from core.text_utils import parse_date_to_ts, perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)

class _NewsStateTagsMixin:
    # news.is_duplicate is a legacy schema column; duplicate truth lives in news_keywords.
    ALLOWED_UPDATE_FIELDS = {"is_read", "is_bookmarked", "notes"}

    def update_status(self: DatabaseManager, link: str, field: str, value) -> bool:
        """Update a safe allow-listed status field."""
        if field not in self.ALLOWED_UPDATE_FIELDS:
            logger.error("Rejected update for unsupported field: %s", field)
            return False
        if not isinstance(link, str) or not link.strip():
            return False

        conn = self.get_connection()
        try:
            with conn:
                timestamp_field = {
                    "is_read": "read_updated_at",
                    "is_bookmarked": "bookmark_updated_at",
                    "notes": "notes_updated_at",
                }.get(field)
                if timestamp_field:
                    cursor = conn.execute(
                        f"UPDATE news SET {field} = ?, {timestamp_field} = ? WHERE link = ?",
                        (value, datetime.now().timestamp(), link),
                    )
                else:
                    cursor = conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return int(cursor.rowcount or 0) > 0
        except sqlite3.Error as e:
            logger.error("DB update failed: %s", e)
            raise self._new_write_error("update_status", e) from e
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
                conn.execute("DELETE FROM news_tags WHERE link = ?", (link,))
                conn.execute("DELETE FROM news_tag_state WHERE link = ?", (link,))
                cursor = conn.execute("DELETE FROM news WHERE link = ?", (link,))
                deleted = int(cursor.rowcount or 0)
                if deleted <= 0:
                    return False
                self._recalculate_duplicates_for_affected(conn, affected)
            return True
        except sqlite3.Error as e:
            logger.error("delete_link failed: %s", e)
            raise self._new_write_error("delete_link", e) from e
        except Exception as e:
            logger.error("delete_link failed: %s", e)
            raise self._new_write_error("delete_link", e) from e
        finally:
            self.return_connection(conn)
    def get_note(self: DatabaseManager, link: str) -> str:
        conn = self.get_connection()
        try:
            result = conn.execute("SELECT notes FROM news WHERE link = ?", (link,)).fetchone()
            return str(result[0]) if result and result[0] else ""
        except sqlite3.Error as e:
            logger.error("get_note failed: %s", e)
            raise self._new_query_error("get_note", e) from e
        except Exception as e:
            logger.error("get_note failed: %s", e)
            raise self._new_query_error("get_note", e) from e
        finally:
            self.return_connection(conn)
    def get_tags(self: DatabaseManager, link: str) -> List[str]:
        if not isinstance(link, str) or not link.strip():
            return []
        conn = self.get_connection()
        try:
            rows = conn.execute(
                "SELECT tag FROM news_tags WHERE link = ? ORDER BY lower(tag), tag",
                (link,),
            ).fetchall()
            return [str(row[0]) for row in rows if row and row[0]]
        except sqlite3.Error as e:
            logger.error("get_tags failed: %s", e)
            raise self._new_query_error("get_tags", e) from e
        finally:
            self.return_connection(conn)
    def set_tags(self: DatabaseManager, link: str, tags: Any) -> bool:
        normalized_tags = normalize_tags(tags)
        if not isinstance(link, str) or not link.strip():
            return False
        conn = self.get_connection()
        try:
            with conn:
                exists = conn.execute("SELECT 1 FROM news WHERE link = ?", (link,)).fetchone()
                if not exists:
                    return False
                conn.execute("DELETE FROM news_tags WHERE link = ?", (link,))
                if normalized_tags:
                    conn.executemany(
                        "INSERT OR IGNORE INTO news_tags(link, tag) VALUES (?, ?)",
                        [(link, tag) for tag in normalized_tags],
                    )
                conn.execute(
                    """
                    INSERT INTO news_tag_state(link, tags_updated_at)
                    VALUES (?, ?)
                    ON CONFLICT(link) DO UPDATE SET
                        tags_updated_at = excluded.tags_updated_at
                    """,
                    (link, datetime.now().timestamp()),
                )
            return True
        except sqlite3.Error as e:
            logger.error("set_tags failed: %s", e)
            raise self._new_write_error("set_tags", e) from e
        finally:
            self.return_connection(conn)
    def _set_tags_with_conn(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        link: str,
        tags: Any,
        *,
        timestamp: Optional[float] = None,
    ) -> bool:
        normalized_tags = normalize_tags(tags)
        if not isinstance(link, str) or not link.strip():
            return False
        exists = conn.execute("SELECT 1 FROM news WHERE link = ?", (link,)).fetchone()
        if not exists:
            return False
        conn.execute("DELETE FROM news_tags WHERE link = ?", (link,))
        if normalized_tags:
            conn.executemany(
                "INSERT OR IGNORE INTO news_tags(link, tag) VALUES (?, ?)",
                [(link, tag) for tag in normalized_tags],
            )
        conn.execute(
            """
            INSERT INTO news_tag_state(link, tags_updated_at)
            VALUES (?, ?)
            ON CONFLICT(link) DO UPDATE SET
                tags_updated_at = excluded.tags_updated_at
            """,
            (link, float(timestamp or datetime.now().timestamp())),
        )
        return True
    def get_known_tags(self: DatabaseManager) -> List[str]:
        conn = self.get_connection()
        try:
            rows = conn.execute(
                "SELECT tag FROM news_tags GROUP BY tag ORDER BY lower(tag), tag"
            ).fetchall()
            return [str(row[0]) for row in rows if row and row[0]]
        except sqlite3.Error as e:
            logger.error("get_known_tags failed: %s", e)
            raise self._new_query_error("get_known_tags", e) from e
        finally:
            self.return_connection(conn)
    def get_tag_usage(self: DatabaseManager) -> List[Tuple[str, int]]:
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT tag, COUNT(DISTINCT link) AS count
                FROM news_tags
                GROUP BY tag
                ORDER BY lower(tag), tag
                """
            ).fetchall()
            return [(str(row[0]), int(row[1])) for row in rows if row and row[0]]
        except sqlite3.Error as e:
            logger.error("get_tag_usage failed: %s", e)
            raise self._new_query_error("get_tag_usage", e) from e
        finally:
            self.return_connection(conn)
    def rename_tag(self: DatabaseManager, old_tag: str, new_tag: str) -> int:
        old_normalized = normalize_tags([old_tag])
        new_normalized = normalize_tags([new_tag])
        if not old_normalized or not new_normalized:
            return 0
        old_value = old_normalized[0]
        new_value = new_normalized[0]
        conn = self.get_connection()
        try:
            with conn:
                rows = conn.execute(
                    "SELECT DISTINCT link FROM news_tags WHERE lower(tag) = lower(?)",
                    (old_value,),
                ).fetchall()
                links = [str(row[0]) for row in rows if row and row[0]]
                if not links:
                    return 0
                now_ts = datetime.now().timestamp()
                for link in links:
                    current = self._tags_for_link_with_conn(conn, link)
                    changed = False
                    next_tags: List[str] = []
                    seen = set()
                    for tag in current:
                        replacement = new_value if tag.casefold() == old_value.casefold() else tag
                        key = replacement.casefold()
                        if key not in seen:
                            seen.add(key)
                            next_tags.append(replacement)
                        changed = changed or replacement != tag
                    if changed:
                        self._set_tags_with_conn(conn, link, next_tags, timestamp=now_ts)
                return len(links)
        except sqlite3.Error as e:
            logger.error("rename_tag failed: %s", e)
            raise self._new_write_error("rename_tag", e) from e
        finally:
            self.return_connection(conn)
    def delete_tag_everywhere(self: DatabaseManager, tag: str) -> int:
        normalized = normalize_tags([tag])
        if not normalized:
            return 0
        target = normalized[0]
        conn = self.get_connection()
        try:
            with conn:
                rows = conn.execute(
                    "SELECT DISTINCT link FROM news_tags WHERE lower(tag) = lower(?)",
                    (target,),
                ).fetchall()
                links = [str(row[0]) for row in rows if row and row[0]]
                if not links:
                    return 0
                now_ts = datetime.now().timestamp()
                for link in links:
                    current = [
                        item for item in self._tags_for_link_with_conn(conn, link)
                        if item.casefold() != target.casefold()
                    ]
                    self._set_tags_with_conn(conn, link, current, timestamp=now_ts)
                return len(links)
        except sqlite3.Error as e:
            logger.error("delete_tag_everywhere failed: %s", e)
            raise self._new_write_error("delete_tag_everywhere", e) from e
        finally:
            self.return_connection(conn)
    def _tags_for_link_with_conn(self: DatabaseManager, conn: sqlite3.Connection, link: str) -> List[str]:
        rows = conn.execute(
            "SELECT tag FROM news_tags WHERE link = ? ORDER BY lower(tag), tag",
            (link,),
        ).fetchall()
        return [str(row[0]) for row in rows if row and row[0]]
    def bulk_add_tag_to_links(self: DatabaseManager, links: List[str], tag: str) -> int:
        normalized = normalize_tags([tag])
        if not normalized:
            return 0
        target = normalized[0]
        deduped_links = self._dedupe_links(links)
        if not deduped_links:
            return 0
        conn = self.get_connection()
        changed = 0
        try:
            with conn:
                now_ts = datetime.now().timestamp()
                for link in deduped_links:
                    current = self._tags_for_link_with_conn(conn, link)
                    if any(item.casefold() == target.casefold() for item in current):
                        continue
                    if self._set_tags_with_conn(conn, link, [*current, target], timestamp=now_ts):
                        changed += 1
            return changed
        except sqlite3.Error as e:
            logger.error("bulk_add_tag_to_links failed: %s", e)
            raise self._new_write_error("bulk_add_tag_to_links", e) from e
        finally:
            self.return_connection(conn)
    def bulk_remove_tag_from_links(self: DatabaseManager, links: List[str], tag: str) -> int:
        normalized = normalize_tags([tag])
        if not normalized:
            return 0
        target = normalized[0]
        deduped_links = self._dedupe_links(links)
        if not deduped_links:
            return 0
        conn = self.get_connection()
        changed = 0
        try:
            with conn:
                now_ts = datetime.now().timestamp()
                for link in deduped_links:
                    current = self._tags_for_link_with_conn(conn, link)
                    next_tags = [item for item in current if item.casefold() != target.casefold()]
                    if len(next_tags) == len(current):
                        continue
                    if self._set_tags_with_conn(conn, link, next_tags, timestamp=now_ts):
                        changed += 1
            return changed
        except sqlite3.Error as e:
            logger.error("bulk_remove_tag_from_links failed: %s", e)
            raise self._new_write_error("bulk_remove_tag_from_links", e) from e
        finally:
            self.return_connection(conn)
