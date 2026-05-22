
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from core.content_filters import normalize_tags
from core.machine_identity import get_machine_identity

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _NewsTagsMixin:
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
