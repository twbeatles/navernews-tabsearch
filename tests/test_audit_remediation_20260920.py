"""Regression tests for the 2026-09-20 audit remediation.

These lock in behaviour that the existing suite did not cover: the previous
defects all passed every correctness test while being wrong about *cost*
(ISSUE-001, ISSUE-002) or about what a cleanup job reclaims (ISSUE-003). The
cost assertions below count the rows a statement touches rather than timing it,
so they stay stable on slow or loaded machines.
"""

import os
import sqlite3
import tempfile
import time
import unittest
from typing import Any, Dict, List

from core.database import DatabaseManager


def _item(link: str, title: str) -> Dict[str, Any]:
    return {
        "link": link,
        "title": title,
        "description": "d",
        "pubDate": "Tue, 01 Jan 2030 00:00:00 +0900",
        "publisher": "pub",
    }


class _CountingConnection:
    """Wraps a sqlite3 connection and records UPDATE row counts."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.updated_rows = 0

    def execute(self, sql, params=()):
        cursor = self._conn.execute(sql, params)
        if sql.strip().upper().startswith("UPDATE"):
            self.updated_rows += max(0, int(cursor.rowcount or 0))
        return cursor

    def executemany(self, sql, seq):
        rows = list(seq)
        cursor = self._conn.executemany(sql, rows)
        if sql.strip().upper().startswith("UPDATE"):
            self.updated_rows += len(rows)
        return cursor

    def __getattr__(self, name):
        return getattr(self._conn, name)

    # Dunder lookup bypasses __getattr__, so the context manager has to be
    # forwarded explicitly for `with conn:` to commit as it normally would.
    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


class _DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "news.db")
        self.db = DatabaseManager(self.db_path, max_connections=3)

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass

    def _flags(self) -> Dict[tuple, int]:
        conn = self.db.get_connection()
        try:
            return {
                (str(row[0]), str(row[1])): int(row[2] or 0)
                for row in conn.execute(
                    "SELECT query_key, link, is_duplicate FROM news_keywords"
                )
            }
        finally:
            self.db.return_connection(conn)


class TestDeleteRestoreDuplicateFlags(_DatabaseTestCase):
    """ISSUE-001: single-article delete must stay scoped AND stay correct."""

    def test_delete_and_restore_keep_duplicate_flags_correct(self):
        self.db.upsert_news_detailed(
            [_item("https://a/1", "same title"), _item("https://a/2", "same title")],
            "kw",
            query_key="kw|",
        )
        self.assertEqual(self._flags()[("kw|", "https://a/1")], 1)
        self.assertEqual(self._flags()[("kw|", "https://a/2")], 1)

        self.db.delete_link("https://a/1")
        self.assertEqual(
            self._flags()[("kw|", "https://a/2")],
            0,
            "the surviving article is no longer a duplicate of anything",
        )

        # Before the fix this left a/2 at 0: the affected groups were collected
        # while the row was still soft-deleted, so nothing was recomputed.
        self.db.restore_deleted_link("https://a/1")
        flags = self._flags()
        self.assertEqual(flags[("kw|", "https://a/1")], 1)
        self.assertEqual(flags[("kw|", "https://a/2")], 1)

    def test_delete_does_not_touch_other_query_scopes(self):
        self.db.upsert_news_detailed(
            [_item("https://a/1", "same title"), _item("https://a/2", "same title")],
            "kwA",
            query_key="kwa|",
        )
        self.db.upsert_news_detailed(
            [_item("https://a/1", "same title"), _item("https://a/3", "same title")],
            "kwB",
            query_key="kwb|",
        )

        self.db.delete_link("https://a/2")

        flags = self._flags()
        self.assertEqual(flags[("kwa|", "https://a/1")], 0, "kwa| lost its only peer")
        self.assertEqual(flags[("kwb|", "https://a/1")], 1, "kwb| must be untouched")
        self.assertEqual(flags[("kwb|", "https://a/3")], 1, "kwb| must be untouched")

    def test_delete_cost_does_not_scale_with_the_archive(self):
        """The regression that made a single click O(whole archive)."""
        rows = 400
        self.db.upsert_news_detailed(
            [_item(f"https://a/{i}", f"title {i}") for i in range(rows)],
            "kw",
            query_key="kw|",
        )
        # Two articles share a title so the delete has a real group to fix.
        self.db.upsert_news_detailed(
            [_item("https://a/dup", "title 0")], "kw", query_key="kw|"
        )

        # Exercise the real delete_link path: hand it a counting connection so
        # the assertion guards production code, not a re-implementation.
        real_get = self.db.get_connection
        real_return = self.db.return_connection
        counters: List[_CountingConnection] = []

        def _counting_get(*args, **kwargs):
            wrapper = _CountingConnection(real_get(*args, **kwargs))
            counters.append(wrapper)
            return wrapper

        def _counting_return(conn):
            real_return(conn._conn if isinstance(conn, _CountingConnection) else conn)

        self.db.get_connection = _counting_get
        self.db.return_connection = _counting_return
        try:
            self.assertTrue(self.db.delete_link("https://a/dup"))
        finally:
            self.db.get_connection = real_get
            self.db.return_connection = real_return

        updated_rows = sum(c.updated_rows for c in counters)
        membership_rows = rows + 1
        self.assertLess(
            updated_rows,
            membership_rows // 4,
            f"delete_link() rewrote {updated_rows} rows out of {membership_rows} "
            f"membership rows; the duplicate recalculation is no longer scoped",
        )


class TestStartupRepairIsOneShot(unittest.TestCase):
    """ISSUE-002: startup must not rewrite every membership row each launch."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "news.db")

    def test_second_open_skips_the_o_archive_repair_pass(self):
        db = DatabaseManager(self.db_path, max_connections=2)
        db.upsert_news_detailed(
            [_item(f"https://a/{i}", f"title {i}") for i in range(50)],
            "kw",
            query_key="kw|",
        )
        db.close()

        statements: List[str] = []
        real_connect = sqlite3.connect

        class _RecordingConnection:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, params=()):
                statements.append(" ".join(str(sql).split()))
                return self._conn.execute(sql, params)

            def executemany(self, sql, seq):
                statements.append(" ".join(str(sql).split()))
                return self._conn.executemany(sql, seq)

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def __enter__(self):
                self._conn.__enter__()
                return self

            def __exit__(self, *exc):
                return self._conn.__exit__(*exc)

        def _patched(*args, **kwargs):
            return _RecordingConnection(real_connect(*args, **kwargs))

        sqlite3.connect = _patched
        try:
            db = DatabaseManager(self.db_path, max_connections=2)
            db.close()
        finally:
            sqlite3.connect = real_connect

        membership_rewrites = [
            sql
            for sql in statements
            if sql.startswith("UPDATE news_keywords SET is_duplicate")
        ]
        keyword_backfills = [
            sql for sql in statements if "INSERT OR IGNORE INTO news_keywords" in sql
        ]
        self.assertEqual(
            membership_rewrites,
            [],
            "a clean second startup must not recalculate duplicate flags",
        )
        self.assertEqual(
            keyword_backfills,
            [],
            "a clean second startup must not re-run the keyword membership backfill",
        )

    def test_repair_pass_runs_again_when_the_revision_changes(self):
        db = DatabaseManager(self.db_path, max_connections=2)
        db.upsert_news_detailed([_item("https://a/1", "t")], "kw", query_key="kw|")
        db.close()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE app_meta SET value = 'stale' WHERE key = ?",
            (DatabaseManager.SCHEMA_REPAIR_REVISION_KEY,),
        )
        conn.commit()
        conn.close()

        db = DatabaseManager(self.db_path, max_connections=2)
        try:
            conn = db.get_connection()
            try:
                stored = conn.execute(
                    "SELECT value FROM app_meta WHERE key = ?",
                    (DatabaseManager.SCHEMA_REPAIR_REVISION_KEY,),
                ).fetchone()
            finally:
                db.return_connection(conn)
        finally:
            db.close()
        self.assertEqual(str(stored[0]), DatabaseManager.SCHEMA_REPAIR_REVISION)


class TestShutdownStateMarker(unittest.TestCase):
    """ISSUE-002: integrity check level follows the previous shutdown."""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "news.db")

    def _marker(self):
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                (DatabaseManager.SHUTDOWN_STATE_KEY,),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def test_marker_tracks_open_and_clean_close(self):
        db = DatabaseManager(self.db_path, max_connections=2)
        self.assertEqual(self._marker(), DatabaseManager.SHUTDOWN_STATE_OPEN)
        db.close()
        self.assertEqual(self._marker(), DatabaseManager.SHUTDOWN_STATE_CLEAN)

    def test_clean_shutdown_uses_quick_check_and_a_crash_does_not(self):
        DatabaseManager(self.db_path, max_connections=2).close()

        used = []
        original = DatabaseManager._check_integrity

        def _spy(self, *, quick=False):
            used.append(quick)
            return original(self, quick=quick)

        DatabaseManager._check_integrity = _spy
        try:
            DatabaseManager(self.db_path, max_connections=2).close()
            self.assertEqual(used, [True], "clean shutdown should use quick_check")

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE app_meta SET value = ? WHERE key = ?",
                (
                    DatabaseManager.SHUTDOWN_STATE_OPEN,
                    DatabaseManager.SHUTDOWN_STATE_KEY,
                ),
            )
            conn.commit()
            conn.close()

            used.clear()
            DatabaseManager(self.db_path, max_connections=2).close()
            self.assertEqual(used, [False], "a crash should escalate to integrity_check")
        finally:
            DatabaseManager._check_integrity = original


class TestTombstoneReclamation(_DatabaseTestCase):
    """ISSUE-003: expired soft-deleted rows must actually be reclaimed."""

    def _age_tombstone(self, link: str, days: float) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE news SET delete_updated_at = ? WHERE link = ?",
                (time.time() - days * 86400, link),
            )
            conn.commit()
        finally:
            self.db.return_connection(conn)

    def _remaining(self) -> Dict[str, int]:
        conn = self.db.get_connection()
        try:
            return {
                "total": int(conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]),
                "tombstones": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM news WHERE COALESCE(is_deleted, 0) = 1"
                    ).fetchone()[0]
                ),
            }
        finally:
            self.db.return_connection(conn)

    def _seed(self):
        self.db.upsert_news_detailed(
            [_item(f"https://a/{i}", f"title {i}") for i in range(4)],
            "kw",
            query_key="kw|",
        )
        self.db.delete_link("https://a/1")  # fresh tombstone
        self.db.delete_link("https://a/2")  # aged below
        self._age_tombstone("https://a/2", days=200)

    def test_delete_all_reclaims_only_expired_tombstones(self):
        self._seed()
        self.db.delete_all_news_chunked(tombstone_retention_days=90)
        remaining = self._remaining()
        self.assertEqual(
            remaining["tombstones"], 1, "the fresh tombstone must survive for cloud sync"
        )
        self.assertEqual(remaining["total"], 1, "only the fresh tombstone should remain")

    def test_retention_boundary(self):
        self._seed()
        # 200-day-old tombstone is inside a 365-day window, so it must survive.
        self.db.delete_all_news_chunked(tombstone_retention_days=365)
        self.assertEqual(self._remaining()["tombstones"], 2)

    def test_zero_retention_keeps_tombstones_forever(self):
        self._seed()
        self.db.delete_all_news_chunked(tombstone_retention_days=0)
        self.assertEqual(
            self._remaining()["tombstones"],
            2,
            "retention 0 means 'never reclaim', not 'reclaim everything'",
        )

    def test_bookmarked_tombstone_is_never_reclaimed(self):
        self.db.upsert_news_detailed([_item("https://a/1", "t")], "kw", query_key="kw|")
        self.db.update_status("https://a/1", "is_bookmarked", 1)
        self.db.delete_link("https://a/1")
        self._age_tombstone("https://a/1", days=9999)

        self.db.delete_all_news_chunked(tombstone_retention_days=1)
        self.assertEqual(self._remaining()["tombstones"], 1)

    def test_old_news_cleanup_also_reclaims_expired_tombstones(self):
        self._seed()
        self.db.delete_old_news_chunked(30, tombstone_retention_days=90)
        self.assertEqual(self._remaining()["tombstones"], 1)

    def test_count_reclaimable_tombstones_reports_both_numbers(self):
        self._seed()
        reclaimable, total = self.db.count_reclaimable_tombstones(90)
        self.assertEqual((reclaimable, total), (1, 2))


class TestStorageMetrics(_DatabaseTestCase):
    """GAP-007: the numbers that explain archive growth."""

    def test_metrics_report_articles_tombstones_and_scopes(self):
        self.db.upsert_news_detailed(
            [_item(f"https://a/{i}", f"t{i}") for i in range(3)], "kwA", query_key="kwa|"
        )
        self.db.upsert_news_detailed(
            [_item("https://a/0", "t0")], "kwB", query_key="kwb|"
        )
        self.db.delete_link("https://a/2")

        metrics = self.db.get_storage_metrics()
        self.assertEqual(metrics["articles"], 2)
        self.assertEqual(metrics["tombstones"], 1)
        self.assertEqual(metrics["memberships"], 4)
        self.assertEqual(metrics["query_scopes"], 2)
        self.assertGreater(metrics["db_bytes"], 0)


if __name__ == "__main__":
    unittest.main()


class TestEmergencyConnectionCap(unittest.TestCase):
    """GAP-003: the cap must hold when several threads race for a connection."""

    def test_concurrent_exhaustion_never_exceeds_the_cap(self):
        import threading

        directory = tempfile.mkdtemp()
        db = DatabaseManager(
            os.path.join(directory, "news.db"),
            max_connections=2,
            max_emergency_connections=2,
        )
        try:
            held = [db.get_connection() for _ in range(2)]  # drain the pool
            peak = 0
            peak_lock = threading.Lock()
            results: List[str] = []
            results_lock = threading.Lock()
            # Only the 6 workers wait on this barrier; the main thread must not,
            # or it would block on a fresh barrier generation forever.
            start = threading.Barrier(6, timeout=15)

            def worker():
                nonlocal peak
                start.wait()
                try:
                    conn = db.get_connection(timeout=0.05)
                except Exception:
                    with results_lock:
                        results.append("rejected")
                    return
                with peak_lock:
                    peak = max(peak, len(db._emergency_connections))
                with results_lock:
                    results.append("granted")
                time.sleep(0.02)
                db.return_connection(conn)

            threads = [threading.Thread(target=worker, daemon=True) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
                self.assertFalse(t.is_alive(), "a worker thread did not finish")

            self.assertLessEqual(
                peak,
                2,
                f"emergency connections peaked at {peak}, above the cap of 2",
            )
            self.assertEqual(len(results), 6)
            self.assertIn("rejected", results, "some callers must be refused")
            for conn in held:
                db.return_connection(conn)
        finally:
            db.close()


class TestMarkdownExportEscaping(unittest.TestCase):
    """GAP-005: brackets and parentheses must not break the exported link."""

    def test_title_brackets_and_url_parentheses_are_escaped(self):
        from ui.main_window_io_support.exports import _export_item_markdown

        line = _export_item_markdown(
            {
                "title": "[단독] 삼성 (속보)",
                "link": "https://example.com/a(1)?q=b",
                "publisher": "p",
                "pubDate": "2026-01-01",
            }
        ).splitlines()[0]

        self.assertIn(r"\[단독\]", line)
        self.assertIn("(<https://example.com/a(1)?q=b>)", line)

    def test_missing_link_renders_a_plain_heading(self):
        from ui.main_window_io_support.exports import _export_item_markdown

        line = _export_item_markdown({"title": "제목", "link": ""}).splitlines()[0]
        self.assertEqual(line, "### 제목")


class TestBackupContainmentResolvesReparsePoints(unittest.TestCase):
    """GAP-006: a junction under the backup root must not redirect deletes."""

    def test_directory_reparse_point_is_rejected(self):
        import shutil
        import subprocess
        import sys

        from core.backup_support.fs import _safe_backup_child_dir

        if sys.platform != "win32":
            self.skipTest("directory junctions are a Windows concept")

        root = tempfile.mkdtemp()
        outside = tempfile.mkdtemp()
        link = os.path.join(root, "sneaky")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, outside],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            self.skipTest(f"could not create a junction: {created.stderr.strip()}")

        try:
            # os.path.islink() is False for junctions, so shutil.rmtree would
            # happily follow this into `outside` without the realpath check.
            self.assertFalse(os.path.islink(link))
            ok, _path, reason = _safe_backup_child_dir(root, "sneaky")
            self.assertFalse(ok, "a junction escaping the backup root must be rejected")
            self.assertTrue(reason)
        finally:
            try:
                os.rmdir(link)
            except OSError:
                pass
            shutil.rmtree(outside, ignore_errors=True)

    def test_ordinary_child_directory_is_still_allowed(self):
        from core.backup_support.fs import _safe_backup_child_dir

        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "backup_20260920"), exist_ok=True)
        ok, path, reason = _safe_backup_child_dir(root, "backup_20260920")
        self.assertTrue(ok, reason)
        self.assertTrue(path.endswith("backup_20260920"))


class TestFtsBackfillDisabledByDefault(unittest.TestCase):
    """GAP-001: no query consults news_fts, so the worker stays off."""

    def test_default_is_off_and_the_flag_turns_it_back_on(self):
        from ui.main_window_support.base_support.fts_backfill import (
            _MainWindowFtsBackfillMixin,
        )

        class _Dummy(_MainWindowFtsBackfillMixin):
            # Annotation only: no class attribute, so _fts_backfill_enabled()
            # falls through to the global default on a fresh instance.
            _fts_backfill_force_enabled: bool

        dummy = _Dummy()
        self.assertFalse(
            dummy._fts_backfill_enabled(),
            "the FTS index is never queried, so the backfill must be off by default",
        )

        dummy._fts_backfill_force_enabled = True
        self.assertTrue(dummy._fts_backfill_enabled())

    def test_fts_match_expression_is_still_disabled(self):
        directory = tempfile.mkdtemp()
        db = DatabaseManager(os.path.join(directory, "news.db"), max_connections=2)
        try:
            # The user-facing contract is token-AND LIKE matching; an FTS MATCH
            # prefilter would drop Korean compound-word results.
            self.assertEqual(db._fts_match_expression("삼성전자 실적"), "")
        finally:
            db.close()
