
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


class _NewsAutomationActionsMixin:
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
