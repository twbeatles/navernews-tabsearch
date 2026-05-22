
# pyright: reportGeneralTypeIssues=false
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from typing import TYPE_CHECKING, Any, Dict, List, Set

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class _CloudSyncPreviewMixin:
    def _cloud_source_timestamp_expr(
        self: DatabaseManager,
        source_news_columns: Set[str],
        field: str,
    ) -> str:
        if field in source_news_columns:
            return f"COALESCE(s.{field}, 0)"
        if field == "read_updated_at":
            return "CASE WHEN COALESCE(s.is_read, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if field == "bookmark_updated_at":
            return "CASE WHEN COALESCE(s.is_bookmarked, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if field == "notes_updated_at":
            return "CASE WHEN COALESCE(s.notes, '') != '' THEN COALESCE(s.created_at, 0) ELSE 0 END"
        return "0"

    def _preview_cloud_merge_with_attached(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_news_columns: Set[str],
        source_keyword_columns: Set[str],
        has_tag_state: bool,
    ) -> Dict[str, int]:
        summary = {
            "news_added": 0,
            "memberships_added": 0,
            "read_changed": 0,
            "bookmark_changed": 0,
            "notes_changed": 0,
            "tags_changed": 0,
            "deleted": 0,
            "restored": 0,
        }
        if "link" not in source_news_columns:
            return summary

        s = "s"
        link = self._source_expr(source_news_columns, s, "link", "''")
        is_read = self._source_expr(source_news_columns, s, "is_read", "0")
        is_bookmarked = self._source_expr(source_news_columns, s, "is_bookmarked", "0")
        notes = self._source_expr(source_news_columns, s, "notes", "''")
        is_deleted = self._source_expr(source_news_columns, s, "is_deleted", "0")
        delete_updated_at = self._source_expr(source_news_columns, s, "delete_updated_at", "0")
        read_updated_at = self._cloud_source_timestamp_expr(source_news_columns, "read_updated_at")
        bookmark_updated_at = self._cloud_source_timestamp_expr(source_news_columns, "bookmark_updated_at")
        notes_updated_at = self._cloud_source_timestamp_expr(source_news_columns, "notes_updated_at")

        summary["news_added"] = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM cloud_src.news s
                LEFT JOIN news n ON n.link = {link}
                WHERE {link} != '' AND n.link IS NULL
                """
            ).fetchone()[0]
            or 0
        )
        summary["read_changed"] = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM cloud_src.news s
                JOIN news n ON n.link = {link}
                WHERE {link} != ''
                  AND {read_updated_at} > COALESCE(n.read_updated_at, 0)
                  AND COALESCE({is_read}, 0) != COALESCE(n.is_read, 0)
                """
            ).fetchone()[0]
            or 0
        )
        summary["bookmark_changed"] = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM cloud_src.news s
                JOIN news n ON n.link = {link}
                WHERE {link} != ''
                  AND {bookmark_updated_at} > COALESCE(n.bookmark_updated_at, 0)
                  AND COALESCE({is_bookmarked}, 0) != COALESCE(n.is_bookmarked, 0)
                """
            ).fetchone()[0]
            or 0
        )
        summary["notes_changed"] = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM cloud_src.news s
                JOIN news n ON n.link = {link}
                WHERE {link} != ''
                  AND {notes_updated_at} > COALESCE(n.notes_updated_at, 0)
                  AND COALESCE({notes}, '') != COALESCE(n.notes, '')
                """
            ).fetchone()[0]
            or 0
        )
        delete_rows = conn.execute(
            f"""
            SELECT COALESCE({is_deleted}, 0), COUNT(*)
            FROM cloud_src.news s
            LEFT JOIN news n ON n.link = {link}
            WHERE {link} != ''
              AND COALESCE({delete_updated_at}, 0) > COALESCE(n.delete_updated_at, 0)
              AND COALESCE({is_deleted}, 0) != COALESCE(n.is_deleted, 0)
            GROUP BY COALESCE({is_deleted}, 0)
            """
        ).fetchall()
        for row in delete_rows:
            if int(row[0] or 0):
                summary["deleted"] += int(row[1] or 0)
            else:
                summary["restored"] += int(row[1] or 0)

        if source_keyword_columns:
            nk = "nk"
            nk_link = self._source_expr(source_keyword_columns, nk, "link", "''")
            nk_query_key = self._source_expr(source_keyword_columns, nk, "query_key", "''")
            summary["memberships_added"] = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM cloud_src.news_keywords nk
                    LEFT JOIN news_keywords local_nk
                      ON local_nk.link = {nk_link}
                     AND local_nk.query_key = {nk_query_key}
                    WHERE {nk_link} != ''
                      AND {nk_query_key} != ''
                      AND local_nk.link IS NULL
                    """
                ).fetchone()[0]
                or 0
            )

        if self._table_exists(conn, "cloud_src", "news_tags"):
            if has_tag_state:
                source_ts_expr = (
                    "COALESCE((SELECT st.tags_updated_at FROM cloud_src.news_tag_state st "
                    "WHERE st.link = nt.link), 0)"
                )
            elif "created_at" in source_news_columns:
                source_ts_expr = (
                    "COALESCE((SELECT n.created_at FROM cloud_src.news n "
                    "WHERE n.link = nt.link), 0)"
                )
            else:
                source_ts_expr = "0"
            summary["tags_changed"] = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM (
                        SELECT nt.link, MAX({source_ts_expr}) AS tags_updated_at
                        FROM cloud_src.news_tags nt
                        WHERE nt.link IS NOT NULL AND nt.link != ''
                        GROUP BY nt.link
                    ) src
                    WHERE src.tags_updated_at > COALESCE(
                        (SELECT local_state.tags_updated_at
                         FROM news_tag_state local_state
                         WHERE local_state.link = src.link),
                        0
                    )
                    """
                ).fetchone()[0]
                or 0
            )
        return summary

    def preview_cloud_snapshot_db(
        self: DatabaseManager,
        snapshot_db_path: str,
        *,
        snapshot_id: str = "",
        source_machine_id: str = "",
        local_machine_id: str = "",
    ) -> Dict[str, Any]:
        normalized_snapshot_id = str(snapshot_id or "").strip()
        normalized_source_machine_id = str(source_machine_id or "").strip()
        normalized_local_machine_id = str(local_machine_id or "").strip()
        if (
            normalized_snapshot_id
            and normalized_source_machine_id
            and normalized_local_machine_id
            and normalized_source_machine_id == normalized_local_machine_id
        ):
            return {
                "merged": False,
                "skipped": True,
                "reason": "same_machine",
                "snapshot_id": normalized_snapshot_id,
                "news_added": 0,
                "memberships_added": 0,
                "read_changed": 0,
                "bookmark_changed": 0,
                "notes_changed": 0,
                "tags_changed": 0,
                "deleted": 0,
                "restored": 0,
            }
        if normalized_snapshot_id and normalized_snapshot_id in self.get_cloud_sync_seen_snapshot_ids():
            return {
                "merged": False,
                "skipped": True,
                "reason": "already_seen",
                "snapshot_id": normalized_snapshot_id,
                "news_added": 0,
                "memberships_added": 0,
                "read_changed": 0,
                "bookmark_changed": 0,
                "notes_changed": 0,
                "tags_changed": 0,
                "deleted": 0,
                "restored": 0,
            }

        source_path = os.path.abspath(str(snapshot_db_path or ""))
        if not os.path.exists(source_path):
            raise self._new_query_error("preview_cloud_snapshot_db", FileNotFoundError(source_path))

        conn = self.get_connection()
        attached = False
        try:
            conn.execute("ATTACH DATABASE ? AS cloud_src", (source_path,))
            attached = True
            if not self._table_exists(conn, "cloud_src", "news"):
                raise sqlite3.DatabaseError("snapshot database does not contain news table")
            source_news_columns = self._table_columns(conn, "cloud_src", "news")
            source_keyword_columns = self._table_columns(conn, "cloud_src", "news_keywords")
            has_tag_state = self._table_exists(conn, "cloud_src", "news_tag_state")
            preview: Dict[str, Any] = dict(self._preview_cloud_merge_with_attached(
                conn,
                source_news_columns,
                source_keyword_columns,
                has_tag_state,
            ))
            preview.update(
                {
                    "merged": False,
                    "skipped": False,
                    "reason": "",
                    "snapshot_id": normalized_snapshot_id,
                }
            )
            return preview
        except Exception as e:
            logger.error("Cloud snapshot DB preview failed: %s", e)
            raise self._new_query_error("preview_cloud_snapshot_db", e) from e
        finally:
            if attached:
                try:
                    conn.execute("DETACH DATABASE cloud_src")
                except Exception:
                    pass
            self.return_connection(conn)
