# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from core.text_utils import RE_WHITESPACE, perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager


logger = logging.getLogger(__name__)


class _DatabaseDuplicatesMixin:
    def _recalculate_duplicate_flags_for_query_key_hashes(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        query_key: str,
        title_hashes: List[str],
    ) -> int:
        """Recalculate duplicate flags for a specific query scope and title hashes."""
        normalized_hashes = sorted(
            {
                str(value).strip()
                for value in title_hashes
                if isinstance(value, str) and value.strip()
            }
        )
        if not query_key or not normalized_hashes:
            return 0

        placeholders = ",".join(["?"] * len(normalized_hashes))
        rows = conn.execute(
            f"""
            SELECT nk.link, COALESCE(n.title_hash, '')
            FROM news_keywords nk
            JOIN news n ON n.link = nk.link
            WHERE nk.query_key = ? AND n.title_hash IN ({placeholders})
            """,
            [query_key] + normalized_hashes,
        ).fetchall()
        if not rows:
            return 0

        links_by_hash: Dict[str, Set[str]] = {}
        for row in rows:
            link = str(row[0] or "")
            title_hash = str(row[1] or "")
            links_by_hash.setdefault(title_hash, set()).add(link)

        updates: List[Tuple[int, str, str]] = []
        for row in rows:
            link = str(row[0] or "")
            title_hash = str(row[1] or "")
            is_dup = 1 if len(links_by_hash.get(title_hash, set())) > 1 else 0
            updates.append((is_dup, link, query_key))

        conn.executemany(
            "UPDATE news_keywords SET is_duplicate=? WHERE link=? AND query_key=?",
            updates,
        )
        return len(updates)

    def _recalculate_duplicate_flags_with_conn(
        self: DatabaseManager,
        conn: sqlite3.Connection,
    ) -> int:
        """Recalculate all query-scoped duplicate flags."""
        with perf_timer("db.recalculate_duplicate_flags", "scope=all"):
            rows = conn.execute(
                """
                SELECT nk.query_key, nk.link, COALESCE(n.title_hash, '') AS title_hash
                FROM news_keywords nk
                JOIN news n ON n.link = nk.link
                WHERE nk.query_key IS NOT NULL AND nk.query_key != ''
                """
            ).fetchall()

            if not rows:
                conn.execute("UPDATE news_keywords SET is_duplicate=0 WHERE is_duplicate != 0")
                return 0

            links_by_group: Dict[Tuple[str, str], Set[str]] = {}
            for row in rows:
                query_key = str(row[0] or "")
                link = str(row[1] or "")
                title_hash = str(row[2] or "")
                links_by_group.setdefault((query_key, title_hash), set()).add(link)

            updates: List[Tuple[int, str, str]] = []
            for row in rows:
                query_key = str(row[0] or "")
                link = str(row[1] or "")
                title_hash = str(row[2] or "")
                is_dup = 1 if len(links_by_group.get((query_key, title_hash), set())) > 1 else 0
                updates.append((is_dup, link, query_key))

            conn.executemany(
                "UPDATE news_keywords SET is_duplicate=? WHERE link=? AND query_key=?",
                updates,
            )
            return len(updates)

    def _collect_affected_query_key_hashes(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        news_where_clause: str = "",
        params: Optional[List[Any]] = None,
    ) -> Dict[str, Set[str]]:
        """Collect duplicate groups (query_key + title_hash) affected by deletion."""
        where_sql = (
            " AND (" + news_where_clause + ")"
            if isinstance(news_where_clause, str) and news_where_clause.strip()
            else ""
        )
        rows = conn.execute(
            f"""
            SELECT nk.query_key, COALESCE(n.title_hash, '')
            FROM news_keywords nk
            JOIN news n ON n.link = nk.link
            WHERE nk.query_key IS NOT NULL AND nk.query_key != ''
            {where_sql}
            """,
            list(params or []),
        ).fetchall()

        affected: Dict[str, Set[str]] = {}
        for row in rows:
            query_key = str(row[0] or "").strip()
            if not query_key:
                continue
            title_hash = str(row[1] or "").strip()
            affected.setdefault(query_key, set()).add(title_hash)
        return affected

    def _recalculate_duplicates_for_affected(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        affected: Dict[str, Set[str]],
    ) -> int:
        """Recalculate duplicate flags for affected groups, fallback to full recalc."""
        if not affected:
            return 0

        for hashes in affected.values():
            if any(not hash_value for hash_value in hashes):
                return self._recalculate_duplicate_flags_with_conn(conn)

        updated = 0
        for query_key, hashes in affected.items():
            updated += self._recalculate_duplicate_flags_for_query_key_hashes(
                conn,
                query_key,
                sorted(hashes),
            )
        return updated

    def recalculate_duplicate_flags(self: DatabaseManager) -> int:
        """Public duplicate-recalculation entrypoint."""
        conn = self.get_connection()
        try:
            with conn:
                return self._recalculate_duplicate_flags_with_conn(conn)
        finally:
            self.return_connection(conn)

    def _calculate_title_hash(self: DatabaseManager, title: str) -> str:
        """Stable title hash used for duplicate grouping."""
        normalized = RE_WHITESPACE.sub("", title.lower())
        return hashlib.md5(normalized.encode()).hexdigest()
