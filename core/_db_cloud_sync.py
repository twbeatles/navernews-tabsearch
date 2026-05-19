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


class _DatabaseCloudSyncMixin:
    CLOUD_SYNC_SEEN_META_KEY = "cloud_sync.seen_snapshot_ids"
    CLOUD_SYNC_MAX_SEEN_IDS = 300

    def _table_exists(self: DatabaseManager, conn: sqlite3.Connection, schema: str, table: str) -> bool:
        row = conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_columns(self: DatabaseManager, conn: sqlite3.Connection, schema: str, table: str) -> Set[str]:
        if not self._table_exists(conn, schema, table):
            return set()
        rows = conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
        return {str(row[1]) for row in rows}

    def _source_expr(
        self: DatabaseManager,
        columns: Set[str],
        alias: str,
        column: str,
        default_sql: str,
    ) -> str:
        if column in columns:
            return f"COALESCE({alias}.{column}, {default_sql})"
        return default_sql

    def get_cloud_sync_seen_snapshot_ids(self: DatabaseManager) -> Set[str]:
        conn = self.get_connection()
        try:
            raw = self._get_app_meta(conn, self.CLOUD_SYNC_SEEN_META_KEY, "[]")
            try:
                payload = json.loads(raw)
            except Exception:
                return set()
            if not isinstance(payload, list):
                return set()
            return {str(item) for item in payload if isinstance(item, str) and item.strip()}
        except Exception as e:
            logger.warning("Failed to load cloud sync seen snapshots: %s", e)
            return set()
        finally:
            self.return_connection(conn)

    def mark_cloud_sync_snapshot_seen(self: DatabaseManager, snapshot_id: str) -> None:
        normalized = str(snapshot_id or "").strip()
        if not normalized:
            return
        conn = self.get_connection()
        try:
            with conn:
                raw = self._get_app_meta(conn, self.CLOUD_SYNC_SEEN_META_KEY, "[]")
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = []
                seen: List[str] = [
                    str(item)
                    for item in (payload if isinstance(payload, list) else [])
                    if isinstance(item, str) and item.strip()
                ]
                if normalized in seen:
                    seen.remove(normalized)
                seen.insert(0, normalized)
                seen = seen[: self.CLOUD_SYNC_MAX_SEEN_IDS]
                self._set_app_meta(
                    conn,
                    self.CLOUD_SYNC_SEEN_META_KEY,
                    json.dumps(seen, ensure_ascii=False),
                )
        finally:
            self.return_connection(conn)

    def _create_cloud_merge_rollback_backup(self: DatabaseManager, conn: sqlite3.Connection) -> str:
        db_dir = os.path.dirname(os.path.abspath(self.db_file)) or "."
        os.makedirs(db_dir, exist_ok=True)
        fd, backup_path = tempfile.mkstemp(
            prefix=".cloud_merge_rollback_",
            suffix=".db",
            dir=db_dir,
        )
        os.close(fd)
        dst_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
        return backup_path

    def _restore_cloud_merge_rollback_backup(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        backup_path: str,
    ) -> None:
        if not backup_path or not os.path.exists(backup_path):
            return
        src_conn = sqlite3.connect(backup_path)
        try:
            src_conn.backup(conn)
            conn.commit()
        finally:
            src_conn.close()

    def _merge_cloud_news_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_news_columns: Set[str],
    ) -> None:
        s = "s"
        link = self._source_expr(source_news_columns, s, "link", "''")
        keyword = self._source_expr(source_news_columns, s, "keyword", "''")
        title = self._source_expr(source_news_columns, s, "title", "''")
        description = self._source_expr(source_news_columns, s, "description", "''")
        pub_date = self._source_expr(source_news_columns, s, "pubDate", "''")
        publisher = self._source_expr(source_news_columns, s, "publisher", "''")
        is_read = self._source_expr(source_news_columns, s, "is_read", "0")
        is_bookmarked = self._source_expr(source_news_columns, s, "is_bookmarked", "0")
        pub_date_ts = self._source_expr(source_news_columns, s, "pubDate_ts", "0")
        created_at = self._source_expr(source_news_columns, s, "created_at", "0")
        notes = self._source_expr(source_news_columns, s, "notes", "''")
        title_hash = self._source_expr(source_news_columns, s, "title_hash", "''")
        is_duplicate = self._source_expr(source_news_columns, s, "is_duplicate", "0")
        is_deleted = self._source_expr(source_news_columns, s, "is_deleted", "0")
        delete_updated_at = self._source_expr(source_news_columns, s, "delete_updated_at", "0")
        delete_machine_id = self._source_expr(source_news_columns, s, "delete_machine_id", "''")
        delete_reason = self._source_expr(source_news_columns, s, "delete_reason", "''")

        if "read_updated_at" in source_news_columns:
            read_updated_at = "COALESCE(s.read_updated_at, 0)"
        else:
            read_updated_at = "CASE WHEN COALESCE(s.is_read, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if "bookmark_updated_at" in source_news_columns:
            bookmark_updated_at = "COALESCE(s.bookmark_updated_at, 0)"
        else:
            bookmark_updated_at = "CASE WHEN COALESCE(s.is_bookmarked, 0) != 0 THEN COALESCE(s.created_at, 0) ELSE 0 END"
        if "notes_updated_at" in source_news_columns:
            notes_updated_at = "COALESCE(s.notes_updated_at, 0)"
        else:
            notes_updated_at = "CASE WHEN COALESCE(s.notes, '') != '' THEN COALESCE(s.created_at, 0) ELSE 0 END"

        conn.execute(
            f"""
            INSERT INTO news (
                link, keyword, title, description, pubDate, publisher,
                is_read, is_bookmarked, pubDate_ts, created_at, notes,
                title_hash, is_duplicate,
                read_updated_at, bookmark_updated_at, notes_updated_at,
                is_deleted, delete_updated_at, delete_machine_id, delete_reason
            )
            SELECT
                {link}, {keyword}, {title}, {description}, {pub_date}, {publisher},
                {is_read}, {is_bookmarked}, {pub_date_ts}, {created_at}, {notes},
                {title_hash}, {is_duplicate},
                {read_updated_at}, {bookmark_updated_at}, {notes_updated_at},
                {is_deleted}, {delete_updated_at}, {delete_machine_id}, {delete_reason}
            FROM cloud_src.news s
            WHERE {link} != ''
            ON CONFLICT(link) DO UPDATE SET
                keyword = CASE
                    WHEN news.keyword IS NULL OR news.keyword = '' THEN excluded.keyword
                    ELSE news.keyword
                END,
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE news.title END,
                description = CASE
                    WHEN excluded.description != '' THEN excluded.description
                    ELSE news.description
                END,
                pubDate = CASE WHEN excluded.pubDate != '' THEN excluded.pubDate ELSE news.pubDate END,
                publisher = CASE
                    WHEN excluded.publisher != '' THEN excluded.publisher
                    ELSE news.publisher
                END,
                pubDate_ts = CASE
                    WHEN COALESCE(excluded.pubDate_ts, 0) > COALESCE(news.pubDate_ts, 0)
                    THEN excluded.pubDate_ts
                    ELSE news.pubDate_ts
                END,
                created_at = CASE
                    WHEN COALESCE(news.created_at, 0) = 0 THEN excluded.created_at
                    ELSE news.created_at
                END,
                title_hash = CASE
                    WHEN excluded.title_hash != '' THEN excluded.title_hash
                    ELSE news.title_hash
                END,
                is_read = CASE
                    WHEN COALESCE(excluded.read_updated_at, 0) > COALESCE(news.read_updated_at, 0)
                    THEN excluded.is_read
                    ELSE news.is_read
                END,
                read_updated_at = MAX(
                    COALESCE(news.read_updated_at, 0),
                    COALESCE(excluded.read_updated_at, 0)
                ),
                is_bookmarked = CASE
                    WHEN COALESCE(excluded.bookmark_updated_at, 0) > COALESCE(news.bookmark_updated_at, 0)
                    THEN excluded.is_bookmarked
                    ELSE news.is_bookmarked
                END,
                bookmark_updated_at = MAX(
                    COALESCE(news.bookmark_updated_at, 0),
                    COALESCE(excluded.bookmark_updated_at, 0)
                ),
                notes = CASE
                    WHEN COALESCE(excluded.notes_updated_at, 0) > COALESCE(news.notes_updated_at, 0)
                    THEN excluded.notes
                    ELSE news.notes
                END,
                notes_updated_at = MAX(
                    COALESCE(news.notes_updated_at, 0),
                    COALESCE(excluded.notes_updated_at, 0)
                ),
                is_deleted = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.is_deleted
                    ELSE news.is_deleted
                END,
                delete_updated_at = MAX(
                    COALESCE(news.delete_updated_at, 0),
                    COALESCE(excluded.delete_updated_at, 0)
                ),
                delete_machine_id = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.delete_machine_id
                    ELSE news.delete_machine_id
                END,
                delete_reason = CASE
                    WHEN COALESCE(excluded.delete_updated_at, 0) > COALESCE(news.delete_updated_at, 0)
                    THEN excluded.delete_reason
                    ELSE news.delete_reason
                END
            """
        )

    def _merge_cloud_keyword_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_keyword_columns: Set[str],
    ) -> None:
        if not source_keyword_columns:
            return
        nk = "nk"
        link = self._source_expr(source_keyword_columns, nk, "link", "''")
        keyword = self._source_expr(source_keyword_columns, nk, "keyword", "''")
        query_key = self._source_expr(source_keyword_columns, nk, "query_key", "''")
        is_duplicate = self._source_expr(source_keyword_columns, nk, "is_duplicate", "0")
        conn.execute(
            f"""
            INSERT INTO news_keywords (link, keyword, query_key, is_duplicate)
            SELECT {link}, {keyword}, {query_key}, {is_duplicate}
            FROM cloud_src.news_keywords nk
            WHERE {link} != ''
              AND {query_key} != ''
              AND EXISTS (SELECT 1 FROM news n WHERE n.link = {link})
            ON CONFLICT(link, query_key) DO UPDATE SET
                keyword = CASE
                    WHEN excluded.keyword != '' THEN excluded.keyword
                    ELSE news_keywords.keyword
                END
            """
        )

    def _merge_cloud_tag_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        source_news_columns: Set[str],
        has_tag_state: bool,
    ) -> None:
        if not self._table_exists(conn, "cloud_src", "news_tags"):
            return

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

        conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")
        conn.execute(
            "CREATE TEMP TABLE temp_cloud_tag_links (link TEXT PRIMARY KEY, tags_updated_at REAL)"
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO temp_cloud_tag_links(link, tags_updated_at)
            SELECT nt.link, MAX({source_ts_expr})
            FROM cloud_src.news_tags nt
            WHERE nt.link IS NOT NULL
              AND nt.link != ''
              AND EXISTS (SELECT 1 FROM news n WHERE n.link = nt.link)
            GROUP BY nt.link
            HAVING MAX({source_ts_expr}) > COALESCE(
                (SELECT local_state.tags_updated_at
                 FROM news_tag_state local_state
                 WHERE local_state.link = nt.link),
                0
            )
            """
        )
        conn.execute(
            """
            DELETE FROM news_tags
            WHERE link IN (SELECT link FROM temp_cloud_tag_links)
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO news_tags(link, tag)
            SELECT nt.link, nt.tag
            FROM cloud_src.news_tags nt
            JOIN temp_cloud_tag_links t ON t.link = nt.link
            WHERE nt.tag IS NOT NULL AND TRIM(nt.tag) != ''
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO news_tag_state(link, tags_updated_at)
            SELECT link, tags_updated_at FROM temp_cloud_tag_links
            """
        )
        conn.execute("DROP TABLE IF EXISTS temp_cloud_tag_links")

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
