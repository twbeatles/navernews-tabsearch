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
        # CROSS JOIN is a join-ORDER hint here, not a cartesian product: the ON
        # clause still applies. It forces SQLite to start from the highly
        # selective idx_title_hash instead of scanning every membership row in
        # the scope via idx_nk_query_key_link, which is the difference between
        # ~62ms and ~0.01ms on a 120k-row archive. Do not "simplify" to JOIN.
        rows = conn.execute(
            f"""
            SELECT nk.link, COALESCE(n.title_hash, '')
            FROM news n
            CROSS JOIN news_keywords nk ON nk.link = n.link
            WHERE n.title_hash IN ({placeholders})
              AND nk.query_key = ?
              AND COALESCE(n.is_deleted, 0) = 0
            """,
            normalized_hashes + [query_key],
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

    def _recalculate_duplicate_flags_for_entire_database(
        self: DatabaseManager,
        conn: sqlite3.Connection,
    ) -> int:
        """Recalculate duplicate flags for EVERY row in news_keywords.

        Cost is O(size of the whole archive) and every membership row is
        rewritten even when its value does not change, so this must not be
        called from per-article actions or from startup. Scoped callers use
        ``_recalculate_duplicates_for_affected`` or
        ``_recalculate_duplicate_flags_for_query_key_hashes`` instead; this
        entrypoint is reserved for whole-database repair (manual maintenance,
        cloud merge, schema migration).
        """
        with perf_timer("db.recalculate_duplicate_flags", "scope=all"):
            rows = conn.execute(
                """
                SELECT nk.query_key, nk.link, COALESCE(n.title_hash, '') AS title_hash
                FROM news_keywords nk
                JOIN news n ON n.link = nk.link
                WHERE nk.query_key IS NOT NULL AND nk.query_key != ''
                  AND COALESCE(n.is_deleted, 0) = 0
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
        *,
        include_deleted: bool = False,
    ) -> Dict[str, Set[str]]:
        """Collect duplicate groups (query_key + title_hash) affected by a change.

        ``include_deleted=True`` is required when the target row is (or is about
        to be) soft-deleted: the caller still needs the groups that row belongs
        to so they can be recomputed. Group membership itself always ignores
        soft-deleted rows, so the recalculation stays correct either way.
        """
        where_sql = (
            " AND (" + news_where_clause + ")"
            if isinstance(news_where_clause, str) and news_where_clause.strip()
            else ""
        )
        deleted_sql = "" if include_deleted else " AND COALESCE(n.is_deleted, 0) = 0"
        rows = conn.execute(
            f"""
            SELECT nk.query_key, COALESCE(n.title_hash, '')
            FROM news_keywords nk
            JOIN news n ON n.link = nk.link
            WHERE nk.query_key IS NOT NULL AND nk.query_key != ''
            {deleted_sql}
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
                return self._recalculate_duplicate_flags_for_entire_database(conn)

        updated = 0
        for query_key, hashes in affected.items():
            updated += self._recalculate_duplicate_flags_for_query_key_hashes(
                conn,
                query_key,
                sorted(hashes),
            )
        return updated

    def recalculate_duplicate_flags(self: DatabaseManager) -> int:
        """Public whole-database duplicate-recalculation entrypoint (manual repair)."""
        conn = self.get_connection()
        try:
            with conn:
                return self._recalculate_duplicate_flags_for_entire_database(conn)
        finally:
            self.return_connection(conn)

    def _calculate_title_hash(self: DatabaseManager, title: str) -> str:
        """Stable title hash used for duplicate grouping."""
        normalized = RE_WHITESPACE.sub("", title.lower())
        return hashlib.md5(normalized.encode()).hexdigest()
