# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple, cast

from core.content_filters import normalize_tags
from core.machine_identity import get_machine_identity
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
                if field == "notes":
                    normalized_value = "" if value is None else str(value)
                    current = conn.execute(
                        "SELECT COALESCE(notes, '') FROM news WHERE link = ?",
                        (link,),
                    ).fetchone()
                    if current is None or str(current[0] or "") == normalized_value:
                        return False
                    value = normalized_value
                else:
                    try:
                        normalized_value = 1 if int(value or 0) else 0
                    except Exception:
                        normalized_value = 1 if bool(value) else 0
                    current = conn.execute(
                        f"SELECT COALESCE({field}, 0) FROM news WHERE link = ?",
                        (link,),
                    ).fetchone()
                    if current is None or int(current[0] or 0) == normalized_value:
                        return False
                    value = normalized_value
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
        """Soft-delete a single article and repair duplicate flags."""
        if not isinstance(link, str) or not link.strip():
            return False

        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE news
                    SET is_deleted = 1,
                        delete_updated_at = ?,
                        delete_machine_id = ?,
                        delete_reason = ?
                    WHERE link = ? AND COALESCE(is_deleted, 0) = 0
                    """,
                    (datetime.now().timestamp(), get_machine_identity(), "manual", link),
                )
                changed = int(cursor.rowcount or 0)
                if changed <= 0:
                    return False
                self._recalculate_duplicate_flags_with_conn(conn)
            return True
        except sqlite3.Error as e:
            logger.error("delete_link failed: %s", e)
            raise self._new_write_error("delete_link", e) from e
        except Exception as e:
            logger.error("delete_link failed: %s", e)
            raise self._new_write_error("delete_link", e) from e
        finally:
            self.return_connection(conn)
    def restore_deleted_link(self: DatabaseManager, link: str) -> bool:
        """Restore a soft-deleted article and publish the restore timestamp for cloud merge."""
        if not isinstance(link, str) or not link.strip():
            return False

        conn = self.get_connection()
        try:
            with conn:
                affected = self._collect_affected_query_key_hashes(conn, "n.link = ?", [link])
                cursor = conn.execute(
                    """
                    UPDATE news
                    SET is_deleted = 0,
                        delete_updated_at = ?,
                        delete_machine_id = ?,
                        delete_reason = ?
                    WHERE link = ? AND COALESCE(is_deleted, 0) != 0
                    """,
                    (datetime.now().timestamp(), get_machine_identity(), "restore", link),
                )
                changed = int(cursor.rowcount or 0)
                if changed <= 0:
                    return False
                self._recalculate_duplicates_for_affected(conn, affected)
            return True
        except sqlite3.Error as e:
            logger.error("restore_deleted_link failed: %s", e)
            raise self._new_write_error("restore_deleted_link", e) from e
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
                """
                SELECT nt.tag
                FROM news_tags nt
                JOIN news n ON n.link = nt.link
                WHERE nt.link = ? AND COALESCE(n.is_deleted, 0) = 0
                ORDER BY lower(nt.tag), nt.tag
                """,
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
                current_tags = self._tags_for_link_with_conn(conn, link)
                if {tag.casefold() for tag in current_tags} == {tag.casefold() for tag in normalized_tags}:
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
        current_tags = self._tags_for_link_with_conn(conn, link)
        if {tag.casefold() for tag in current_tags} == {tag.casefold() for tag in normalized_tags}:
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
                """
                SELECT nt.tag
                FROM news_tags nt
                JOIN news n ON n.link = nt.link
                WHERE COALESCE(n.is_deleted, 0) = 0
                GROUP BY nt.tag
                ORDER BY lower(nt.tag), nt.tag
                """
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
                SELECT nt.tag, COUNT(DISTINCT nt.link) AS count
                FROM news_tags nt
                JOIN news n ON n.link = nt.link
                WHERE COALESCE(n.is_deleted, 0) = 0
                GROUP BY nt.tag
                ORDER BY lower(nt.tag), nt.tag
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
                    """
                    SELECT DISTINCT nt.link
                    FROM news_tags nt
                    JOIN news n ON n.link = nt.link
                    WHERE lower(nt.tag) = lower(?) AND COALESCE(n.is_deleted, 0) = 0
                    """,
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
                    """
                    SELECT DISTINCT nt.link
                    FROM news_tags nt
                    JOIN news n ON n.link = nt.link
                    WHERE lower(nt.tag) = lower(?) AND COALESCE(n.is_deleted, 0) = 0
                    """,
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
                    if not conn.execute(
                        "SELECT 1 FROM news WHERE link = ? AND COALESCE(is_deleted, 0) = 0",
                        (link,),
                    ).fetchone():
                        continue
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
                    if not conn.execute(
                        "SELECT 1 FROM news WHERE link = ? AND COALESCE(is_deleted, 0) = 0",
                        (link,),
                    ).fetchone():
                        continue
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
    def apply_automation_actions(self: DatabaseManager, mutations: List[Dict[str, Any]]) -> Dict[str, int]:
        """Apply evaluated automation actions in one transaction."""
        cleaned: List[Dict[str, Any]] = []
        for mutation in mutations or []:
            if not isinstance(mutation, dict):
                continue
            link = str(mutation.get("link", "") or "").strip()
            if not link:
                continue
            cleaned.append(
                {
                    "link": link,
                    "add_tags": normalize_tags(mutation.get("add_tags", [])),
                    "mark_read": bool(mutation.get("mark_read", False)),
                    "mark_bookmark": bool(mutation.get("mark_bookmark", False)),
                }
            )
        result = {"mutations": len(cleaned), "tagged": 0, "read": 0, "bookmarked": 0}
        if not cleaned:
            return result

        conn = self.get_connection()
        try:
            with conn:
                now_ts = datetime.now().timestamp()
                for mutation in cleaned:
                    link = mutation["link"]
                    if not conn.execute(
                        "SELECT 1 FROM news WHERE link = ? AND COALESCE(is_deleted, 0) = 0",
                        (link,),
                    ).fetchone():
                        continue
                    add_tags = list(mutation.get("add_tags", []) or [])
                    if add_tags:
                        current = self._tags_for_link_with_conn(conn, link)
                        next_tags = list(current)
                        seen = {tag.casefold() for tag in next_tags}
                        for tag in add_tags:
                            key = tag.casefold()
                            if key not in seen:
                                seen.add(key)
                                next_tags.append(tag)
                        if self._set_tags_with_conn(conn, link, next_tags, timestamp=now_ts):
                            result["tagged"] += 1
                    if mutation.get("mark_read"):
                        cursor = conn.execute(
                            """
                            UPDATE news
                            SET is_read = 1, read_updated_at = ?
                            WHERE link = ? AND COALESCE(is_deleted, 0) = 0 AND COALESCE(is_read, 0) != 1
                            """,
                            (now_ts, link),
                        )
                        if int(cursor.rowcount or 0) > 0:
                            result["read"] += 1
                    if mutation.get("mark_bookmark"):
                        cursor = conn.execute(
                            """
                            UPDATE news
                            SET is_bookmarked = 1, bookmark_updated_at = ?
                            WHERE link = ? AND COALESCE(is_deleted, 0) = 0 AND COALESCE(is_bookmarked, 0) != 1
                            """,
                            (now_ts, link),
                        )
                        if int(cursor.rowcount or 0) > 0:
                            result["bookmarked"] += 1
            return result
        except sqlite3.Error as e:
            logger.error("apply_automation_actions failed: %s", e)
            raise self._new_write_error("apply_automation_actions", e) from e
        finally:
            self.return_connection(conn)
