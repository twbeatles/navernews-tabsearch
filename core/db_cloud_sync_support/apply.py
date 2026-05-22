
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


class _CloudSyncApplyMixin:
    def merge_cloud_snapshot_db(
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
            self.mark_cloud_sync_snapshot_seen(normalized_snapshot_id)
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
            raise self._new_write_error("merge_cloud_snapshot_db", FileNotFoundError(source_path))

        conn = self.get_connection()
        rollback_backup = ""
        attached = False
        before_news = 0
        before_memberships = 0
        preview: Dict[str, int] = {}
        try:
            rollback_backup = self._create_cloud_merge_rollback_backup(conn)
            conn.execute("ATTACH DATABASE ? AS cloud_src", (source_path,))
            attached = True
            if not self._table_exists(conn, "cloud_src", "news"):
                raise sqlite3.DatabaseError("snapshot database does not contain news table")

            source_news_columns = self._table_columns(conn, "cloud_src", "news")
            source_keyword_columns = self._table_columns(conn, "cloud_src", "news_keywords")
            has_tag_state = self._table_exists(conn, "cloud_src", "news_tag_state")

            with conn:
                preview = self._preview_cloud_merge_with_attached(
                    conn,
                    source_news_columns,
                    source_keyword_columns,
                    has_tag_state,
                )
                before_news = int(conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] or 0)
                before_memberships = int(
                    conn.execute("SELECT COUNT(*) FROM news_keywords").fetchone()[0] or 0
                )
                self._merge_cloud_news_rows(conn, source_news_columns)
                self._merge_cloud_keyword_rows(conn, source_keyword_columns)
                self._merge_cloud_tag_rows(conn, source_news_columns, has_tag_state)
                self._recalculate_duplicate_flags_with_conn(conn)
                if normalized_snapshot_id:
                    raw_seen = self._get_app_meta(conn, self.CLOUD_SYNC_SEEN_META_KEY, "[]")
                    try:
                        seen_payload = json.loads(raw_seen)
                    except Exception:
                        seen_payload = []
                    seen = [
                        str(item)
                        for item in (seen_payload if isinstance(seen_payload, list) else [])
                        if isinstance(item, str) and item.strip()
                    ]
                    if normalized_snapshot_id in seen:
                        seen.remove(normalized_snapshot_id)
                    seen.insert(0, normalized_snapshot_id)
                    self._set_app_meta(
                        conn,
                        self.CLOUD_SYNC_SEEN_META_KEY,
                        json.dumps(seen[: self.CLOUD_SYNC_MAX_SEEN_IDS], ensure_ascii=False),
                    )

                after_news = int(conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] or 0)
                after_memberships = int(
                    conn.execute("SELECT COUNT(*) FROM news_keywords").fetchone()[0] or 0
                )

            result = {
                "merged": True,
                "skipped": False,
                "reason": "",
                "snapshot_id": normalized_snapshot_id,
                "news_added": max(0, after_news - before_news),
                "memberships_added": max(0, after_memberships - before_memberships),
                "rollback_backup_created": bool(rollback_backup),
            }
            result.update(preview)
            result["news_added"] = max(0, after_news - before_news)
            result["memberships_added"] = max(0, after_memberships - before_memberships)
            return result
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                self._restore_cloud_merge_rollback_backup(conn, rollback_backup)
            except Exception as restore_error:
                logger.error("Cloud merge rollback restore failed: %s", restore_error)
            logger.error("Cloud snapshot DB merge failed: %s", e)
            raise self._new_write_error("merge_cloud_snapshot_db", e) from e
        finally:
            if attached:
                try:
                    conn.execute("DETACH DATABASE cloud_src")
                except Exception:
                    pass
            try:
                conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")
            except Exception:
                pass
            self.return_connection(conn)
            if rollback_backup and os.path.exists(rollback_backup):
                try:
                    os.remove(rollback_backup)
                except OSError:
                    pass
