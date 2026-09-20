
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from core.content_filters import normalize_note, normalize_tags
from core.machine_identity import get_machine_identity

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _NewsArticleStateMixin:
    def import_article_state(
        self: DatabaseManager,
        link: str,
        *,
        bookmark: Optional[int] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically import bookmark/note values for one existing article."""
        if not isinstance(link, str) or not link.strip():
            return {"status": "missing", "bookmark_changed": False, "note_changed": False}
        normalized_note = normalize_note(note) if note is not None else None
        normalized_bookmark = 1 if int(bookmark or 0) else 0 if bookmark is not None else None
        conn = self.get_connection()
        try:
            with conn:
                current = conn.execute(
                    "SELECT COALESCE(is_bookmarked, 0), COALESCE(notes, '') FROM news WHERE link = ?",
                    (link,),
                ).fetchone()
                if current is None:
                    return {"status": "missing", "bookmark_changed": False, "note_changed": False}
                bookmark_changed = normalized_bookmark is not None and int(current[0] or 0) != normalized_bookmark
                note_changed = normalized_note is not None and str(current[1] or "") != normalized_note
                now = datetime.now().timestamp()
                if bookmark_changed:
                    conn.execute(
                        "UPDATE news SET is_bookmarked = ?, bookmark_updated_at = ? WHERE link = ?",
                        (normalized_bookmark, now, link),
                    )
                if note_changed:
                    conn.execute(
                        "UPDATE news SET notes = ?, notes_updated_at = ? WHERE link = ?",
                        (normalized_note, now, link),
                    )
            return {
                "status": "updated" if bookmark_changed or note_changed else "unchanged",
                "bookmark_changed": bookmark_changed,
                "note_changed": note_changed,
            }
        except Exception as exc:
            logger.error("import_article_state failed: %s", exc)
            raise self._new_write_error("import_article_state", exc) from exc
        finally:
            self.return_connection(conn)

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
                    normalized_value = normalize_note(value)
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
                # Collect the duplicate groups this article belongs to BEFORE the
                # flag flips; afterwards only these groups need recomputing, so
                # the cost stays proportional to the group and not to the archive.
                affected = self._collect_affected_query_key_hashes(
                    conn,
                    "n.link = ?",
                    [link],
                    include_deleted=True,
                )
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

    def restore_deleted_link(self: DatabaseManager, link: str) -> bool:
        """Restore a soft-deleted article and publish the restore timestamp for cloud merge."""
        if not isinstance(link, str) or not link.strip():
            return False

        conn = self.get_connection()
        try:
            with conn:
                # The row is still soft-deleted here, so its groups are only
                # visible with include_deleted=True. Without it the collection
                # came back empty and the restored article left stale duplicate
                # flags on its peers.
                affected = self._collect_affected_query_key_hashes(
                    conn,
                    "n.link = ?",
                    [link],
                    include_deleted=True,
                )
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
