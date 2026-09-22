"""Regression tests for unused search scope cleanup (GAP-008 follow-up).

A closed tab leaves its ``news_keywords`` memberships behind. The cleanup must
delete exactly those dead-scope memberships while keeping live scopes, shared
articles, tombstones, and duplicate flags correct.
"""

import os
import tempfile
import unittest
from typing import Any, Dict, List

from core.database import DatabaseManager

LIVE_KEY = "scope-live"
DEAD_KEY = "scope-dead"
OTHER_DEAD_KEY = "scope-dead-other"


def _item(link: str, title: str) -> Dict[str, Any]:
    return {
        "link": link,
        "title": title,
        "description": "d",
        "pubDate": "Tue, 01 Jan 2030 00:00:00 +0900",
        "publisher": "pub",
    }


class _ScopeCleanupTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.db = DatabaseManager(os.path.join(self._dir, "news.db"), max_connections=3)
        self.db.upsert_news_detailed(
            [
                _item("https://news/live-1", "live article one"),
                _item("https://news/live-2", "live article two"),
                _item("https://news/shared-title-a", "shared title"),
                _item("https://news/shared-title-b", "shared title"),
                _item("https://news/shared-single", "only here and dead"),
            ],
            "AI",
            query_key=LIVE_KEY,
        )
        self.db.upsert_news_detailed(
            [
                _item("https://news/shared-title-a", "shared title"),
                _item("https://news/shared-title-b", "shared title"),
                _item("https://news/shared-single", "only here and dead"),
                _item("https://news/dead-only", "dead only article"),
            ],
            "dead-keyword",
            query_key=DEAD_KEY,
        )
        self.db.upsert_news_detailed(
            [_item("https://news/other-dead-only", "other dead article")],
            "other-dead-keyword",
            query_key=OTHER_DEAD_KEY,
        )

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass

    def _memberships(self) -> List[tuple]:
        conn = self.db.get_connection()
        try:
            return [
                (str(row[0]), str(row[1]))
                for row in conn.execute("SELECT link, query_key FROM news_keywords")
            ]
        finally:
            self.db.return_connection(conn)

    def _flags(self) -> Dict[tuple, int]:
        conn = self.db.get_connection()
        try:
            return {
                (str(row[0]), str(row[1])): int(row[2] or 0)
                for row in conn.execute("SELECT query_key, link, is_duplicate FROM news_keywords")
            }
        finally:
            self.db.return_connection(conn)

    def _mark_deleted(self, link: str) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("UPDATE news SET is_deleted = 1 WHERE link = ?", (link,))
        finally:
            self.db.return_connection(conn)


class TestScopeCleanupPreview(_ScopeCleanupTestCase):
    def test_preview_lists_only_dead_scopes_with_counts(self):
        preview = self.db.preview_scope_cleanup([LIVE_KEY])
        by_key = {scope.query_key: scope for scope in preview.dead_scopes}
        self.assertEqual(set(by_key), {DEAD_KEY, OTHER_DEAD_KEY})
        self.assertEqual(by_key[DEAD_KEY].membership_count, 4)
        self.assertEqual(by_key[OTHER_DEAD_KEY].membership_count, 1)
        self.assertEqual(by_key[DEAD_KEY].keyword_label, "dead-keyword")
        self.assertEqual(preview.removable_memberships, 5)
        # Dead-only articles lose their last membership; shared ones do not.
        self.assertEqual(preview.orphaned_articles, 2)

    def test_preview_refuses_empty_keep_set(self):
        with self.assertRaises(ValueError):
            self.db.preview_scope_cleanup([])

    def test_preview_with_nothing_dead_reports_zero(self):
        preview = self.db.preview_scope_cleanup([LIVE_KEY, DEAD_KEY, OTHER_DEAD_KEY])
        self.assertEqual(preview.dead_scopes, ())
        self.assertEqual(preview.removable_memberships, 0)
        self.assertEqual(preview.orphaned_articles, 0)


class TestScopeCleanupExecution(_ScopeCleanupTestCase):
    def test_cleanup_removes_only_dead_memberships(self):
        result = self.db.cleanup_unused_scopes([LIVE_KEY])
        self.assertEqual(result.removed_memberships, 5)
        self.assertEqual(result.remaining_scopes, 1)
        remaining = set(self._memberships())
        self.assertNotIn(("https://news/dead-only", DEAD_KEY), remaining)
        self.assertNotIn(("https://news/other-dead-only", OTHER_DEAD_KEY), remaining)
        self.assertIn(("https://news/live-1", LIVE_KEY), remaining)
        # Shared articles keep their live membership.
        self.assertIn(("https://news/shared-title-a", LIVE_KEY), remaining)
        self.assertIn(("https://news/shared-single", LIVE_KEY), remaining)

    def test_shared_article_stays_listed_with_same_state(self):
        before = {
            row["link"]: (row["is_read"], row["is_bookmarked"])
            for row in self.db.fetch_news("AI", query_key=LIVE_KEY)
        }
        self.assertIn("https://news/shared-single", before)
        self.db.cleanup_unused_scopes([LIVE_KEY])
        after = {
            row["link"]: (row["is_read"], row["is_bookmarked"])
            for row in self.db.fetch_news("AI", query_key=LIVE_KEY)
        }
        self.assertEqual(before, after)
        links = [row["link"] for row in self.db.fetch_news("dead-keyword", query_key=DEAD_KEY)]
        self.assertEqual(links, [])

    def test_orphaned_articles_are_reported_but_rows_are_kept(self):
        total_before = self.db.get_statistics()["total"]
        result = self.db.cleanup_unused_scopes([LIVE_KEY])
        self.assertEqual(result.orphaned_articles, 2)
        self.assertEqual(self.db.get_statistics()["total"], total_before)
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM news WHERE link = ?", ("https://news/dead-only",)
            ).fetchone()
        finally:
            self.db.return_connection(conn)
        self.assertEqual(int(row[0]), 1)

    def test_tombstone_memberships_are_untouched(self):
        self._mark_deleted("https://news/dead-only")
        result = self.db.cleanup_unused_scopes([LIVE_KEY])
        # Only the 4 live memberships of the dead scope are removed.
        self.assertEqual(result.removed_memberships, 4)
        remaining = set(self._memberships())
        self.assertIn(("https://news/dead-only", DEAD_KEY), remaining)

    def test_duplicate_flags_stay_correct_in_remaining_scopes(self):
        self.db.cleanup_unused_scopes([LIVE_KEY])
        flags = self._flags()
        # Live duplicate pair keeps its flags.
        self.assertEqual(flags[(LIVE_KEY, "https://news/shared-title-a")], 1)
        self.assertEqual(flags[(LIVE_KEY, "https://news/shared-title-b")], 1)
        # Singles are not duplicates.
        self.assertEqual(flags[(LIVE_KEY, "https://news/live-1")], 0)
        self.assertEqual(flags[(LIVE_KEY, "https://news/shared-single")], 0)

    def test_rerun_is_a_noop(self):
        first = self.db.cleanup_unused_scopes([LIVE_KEY])
        self.assertGreater(first.removed_memberships, 0)
        second = self.db.cleanup_unused_scopes([LIVE_KEY])
        self.assertEqual(second.removed_memberships, 0)
        self.assertEqual(second.remaining_scopes, first.remaining_scopes)

    def test_cleanup_refuses_empty_keep_set(self):
        with self.assertRaises(ValueError):
            self.db.cleanup_unused_scopes([])


if __name__ == "__main__":
    unittest.main()
