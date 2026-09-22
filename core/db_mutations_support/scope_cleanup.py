# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
"""Scoped cleanup of memberships left behind by closed tabs (GAP-008)."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Collection, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)

__all__ = [
    "DeadScope",
    "ScopeCleanupPreview",
    "ScopeCleanupResult",
    "_NewsScopeCleanupMixin",
]

_HASH_CHUNK_SIZE = 500


@dataclass(frozen=True)
class DeadScope:
    query_key: str
    keyword_label: str
    membership_count: int


@dataclass(frozen=True)
class ScopeCleanupPreview:
    dead_scopes: Tuple[DeadScope, ...]
    removable_memberships: int
    orphaned_articles: int


@dataclass(frozen=True)
class ScopeCleanupResult:
    removed_memberships: int
    remaining_scopes: int
    orphaned_articles: int
    recalculated_groups: int


class _NewsScopeCleanupMixin:
    def _normalize_scope_keep_set(
        self: DatabaseManager,
        keep_query_keys: Collection[str],
    ) -> List[str]:
        seen: Set[str] = set()
        normalized: List[str] = []
        for raw in keep_query_keys or ():
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    def _dead_scope_rows(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        keep: List[str],
    ) -> List[Tuple[str, str, int]]:
        placeholders = ",".join(["?"] * len(keep))
        return [
            (str(row[0] or ""), str(row[1] or ""), int(row[2] or 0))
            for row in conn.execute(
                f"""
                SELECT nk.query_key, nk.keyword, COUNT(*)
                FROM news_keywords nk
                JOIN news n ON n.link = nk.link
                WHERE nk.query_key NOT IN ({placeholders})
                  AND nk.query_key IS NOT NULL AND nk.query_key != ''
                  AND COALESCE(n.is_deleted, 0) = 0
                GROUP BY nk.query_key, nk.keyword
                """,
                keep,
            ).fetchall()
        ]

    def _build_dead_scopes(
        self: DatabaseManager,
        rows: List[Tuple[str, str, int]],
    ) -> List[DeadScope]:
        totals: Dict[str, int] = {}
        labels: Dict[str, Tuple[int, str]] = {}
        for query_key, keyword, count in rows:
            if not query_key:
                continue
            totals[query_key] = totals.get(query_key, 0) + count
            label = keyword.strip() or query_key
            best = labels.get(query_key)
            if best is None or count > best[0]:
                labels[query_key] = (count, label)
        scopes = [
            DeadScope(
                query_key=query_key,
                keyword_label=labels[query_key][1],
                membership_count=total,
            )
            for query_key, total in totals.items()
        ]
        scopes.sort(key=lambda scope: (-scope.membership_count, scope.query_key))
        return scopes

    def _count_orphaned_articles(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        keep: List[str],
        dead_keys: List[str],
    ) -> int:
        if not dead_keys:
            return 0
        keep_placeholders = ",".join(["?"] * len(keep))
        dead_placeholders = ",".join(["?"] * len(dead_keys))
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM news n
            WHERE COALESCE(n.is_deleted, 0) = 0
              AND EXISTS (
                  SELECT 1 FROM news_keywords nk
                  WHERE nk.link = n.link AND nk.query_key IN ({dead_placeholders})
              )
              AND NOT EXISTS (
                  SELECT 1 FROM news_keywords nk
                  WHERE nk.link = n.link AND nk.query_key IN ({keep_placeholders})
              )
            """,
            dead_keys + keep,
        ).fetchone()
        return int(row[0] or 0)

    def preview_scope_cleanup(
        self: DatabaseManager,
        keep_query_keys: Collection[str],
    ) -> ScopeCleanupPreview:
        """Describe the dead scopes a cleanup would remove, without changing data."""
        keep = self._normalize_scope_keep_set(keep_query_keys)
        if not keep:
            raise ValueError("cleanup_unused_scopes requires at least one live query key")
        conn = self.get_connection()
        try:
            dead_scopes = self._build_dead_scopes(self._dead_scope_rows(conn, keep))
            dead_keys = [scope.query_key for scope in dead_scopes]
            return ScopeCleanupPreview(
                dead_scopes=tuple(dead_scopes),
                removable_memberships=sum(scope.membership_count for scope in dead_scopes),
                orphaned_articles=self._count_orphaned_articles(conn, keep, dead_keys),
            )
        except Exception as e:
            logger.error("preview_scope_cleanup failed: %s", e)
            raise self._new_query_error("preview_scope_cleanup", e) from e
        finally:
            self.return_connection(conn)

    def cleanup_unused_scopes(
        self: DatabaseManager,
        keep_query_keys: Collection[str],
    ) -> ScopeCleanupResult:
        """Delete dead-scope memberships atomically and fix live duplicate flags."""
        keep = self._normalize_scope_keep_set(keep_query_keys)
        if not keep:
            raise ValueError("cleanup_unused_scopes requires at least one live query key")
        conn = self.get_connection()
        try:
            with conn:
                dead_keys = [
                    scope.query_key
                    for scope in self._build_dead_scopes(self._dead_scope_rows(conn, keep))
                ]
                doomed_hashes = self._doomed_title_hashes(conn, dead_keys)
                # Count orphans before the delete using the same definition as the
                # preview: rows that would lose their last membership. Counting
                # after the delete would also sweep in pre-existing orphans and
                # break preview/result consistency.
                orphaned = self._count_orphaned_articles(conn, keep, dead_keys)
                removed = self._delete_dead_memberships(conn, keep)
                recalculated = self._recalculate_live_groups(conn, keep, doomed_hashes)
                remaining = self._count_remaining_scopes(conn)
            return ScopeCleanupResult(
                removed_memberships=removed,
                remaining_scopes=remaining,
                orphaned_articles=orphaned,
                recalculated_groups=recalculated,
            )
        except Exception as e:
            logger.error("cleanup_unused_scopes failed: %s", e)
            raise self._new_write_error("cleanup_unused_scopes", e) from e
        finally:
            self.return_connection(conn)

    def _doomed_title_hashes(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        dead_keys: List[str],
    ) -> List[str]:
        if not dead_keys:
            return []
        hashes: Set[str] = set()
        for index in range(0, len(dead_keys), _HASH_CHUNK_SIZE):
            chunk = dead_keys[index : index + _HASH_CHUNK_SIZE]
            placeholders = ",".join(["?"] * len(chunk))
            for row in conn.execute(
                f"""
                SELECT DISTINCT COALESCE(n.title_hash, '')
                FROM news_keywords nk
                JOIN news n ON n.link = nk.link
                WHERE nk.query_key IN ({placeholders})
                  AND COALESCE(n.is_deleted, 0) = 0
                """,
                chunk,
            ).fetchall():
                title_hash = str(row[0] or "").strip()
                if title_hash:
                    hashes.add(title_hash)
        return sorted(hashes)

    def _delete_dead_memberships(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        keep: List[str],
    ) -> int:
        placeholders = ",".join(["?"] * len(keep))
        cursor = conn.execute(
            f"""
            DELETE FROM news_keywords
            WHERE query_key NOT IN ({placeholders})
              AND query_key IS NOT NULL AND query_key != ''
              AND link IN (SELECT link FROM news WHERE COALESCE(is_deleted, 0) = 0)
            """,
            keep,
        )
        return max(0, int(cursor.rowcount or 0))

    def _recalculate_live_groups(
        self: DatabaseManager,
        conn: sqlite3.Connection,
        keep: List[str],
        doomed_hashes: List[str],
    ) -> int:
        if not doomed_hashes:
            return 0
        keep_placeholders = ",".join(["?"] * len(keep))
        affected: Dict[str, Set[str]] = {}
        for index in range(0, len(doomed_hashes), _HASH_CHUNK_SIZE):
            chunk = doomed_hashes[index : index + _HASH_CHUNK_SIZE]
            hash_placeholders = ",".join(["?"] * len(chunk))
            for row in conn.execute(
                f"""
                SELECT DISTINCT nk.query_key, n.title_hash
                FROM news_keywords nk
                JOIN news n ON n.link = nk.link
                WHERE nk.query_key IN ({keep_placeholders})
                  AND n.title_hash IN ({hash_placeholders})
                  AND COALESCE(n.is_deleted, 0) = 0
                """,
                keep + chunk,
            ).fetchall():
                query_key = str(row[0] or "").strip()
                title_hash = str(row[1] or "").strip()
                if query_key and title_hash:
                    affected.setdefault(query_key, set()).add(title_hash)
        recalculated = 0
        for query_key, hashes in affected.items():
            # Scoped recalculation only: the per-group helper drops blank hashes
            # instead of falling back to a whole-database pass.
            self._recalculate_duplicate_flags_for_query_key_hashes(
                conn, query_key, sorted(hashes)
            )
            recalculated += len(hashes)
        return recalculated

    def _count_remaining_scopes(
        self: DatabaseManager,
        conn: sqlite3.Connection,
    ) -> int:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT query_key) FROM news_keywords
            WHERE query_key IS NOT NULL AND query_key != ''
            """
        ).fetchone()
        return int(row[0] or 0)
