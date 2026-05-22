
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


class _NewsArticleStateMixin:
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
