import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest import mock

import news_scraper_pro as app
from core.query_parser import build_fetch_key


class TestDbQueries(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.db_path = Path(self._td.name) / "db.sqlite"
        self.mgr = app.DatabaseManager(str(self.db_path), max_connections=2)

    def tearDown(self):
        self.mgr.close()
        self._td.cleanup()

    def _make_item(self, idx: int, ts: str) -> dict:
        return {
            "title": f"title-{idx}",
            "description": f"desc-{idx}",
            "link": f"https://example.com/{idx}",
            "pubDate": ts,
            "publisher": "example.com",
        }

    def test_fetch_news_limit_offset_compatible_with_default(self):
        items = [
            self._make_item(1, "2026-01-01T09:00:00"),
            self._make_item(2, "2026-01-02T09:00:00"),
            self._make_item(3, "2026-01-03T09:00:00"),
            self._make_item(4, "2026-01-04T09:00:00"),
            self._make_item(5, "2026-01-05T09:00:00"),
        ]
        self.mgr.upsert_news(items, "AI")

        baseline = self.mgr.fetch_news("AI")
        paged = self.mgr.fetch_news("AI", limit=2, offset=1)

        self.assertEqual(len(baseline), 5)
        self.assertEqual(len(paged), 2)
        self.assertEqual([r["link"] for r in paged], [r["link"] for r in baseline[1:3]])

    def test_fetch_news_same_timestamp_pagination_is_deterministic(self):
        items = [
            self._make_item(910, "2026-01-01T09:00:00"),
            self._make_item(912, "2026-01-01T09:00:00"),
            self._make_item(911, "2026-01-01T09:00:00"),
        ]
        self.mgr.upsert_news(items, "AI")

        baseline = self.mgr.fetch_news("AI")
        page_1 = self.mgr.fetch_news("AI", limit=2, offset=0)
        page_2 = self.mgr.fetch_news("AI", limit=2, offset=2)
        baseline_links = [row["link"] for row in baseline]

        self.assertEqual(baseline_links, sorted(baseline_links, reverse=True))
        self.assertEqual(
            [row["link"] for row in page_1 + page_2],
            baseline_links,
        )
        self.assertEqual(len(set(baseline_links)), len(baseline_links))

    def test_get_unread_counts_by_keywords_matches_single_queries(self):
        self.mgr.upsert_news([self._make_item(10, "2026-01-10T09:00:00")], "AI")
        self.mgr.upsert_news([self._make_item(20, "2026-01-10T09:00:00")], "ECON")
        self.mgr.upsert_news([self._make_item(21, "2026-01-11T09:00:00")], "ECON")

        self.mgr.update_status("https://example.com/21", "is_read", 1)

        batch = self.mgr.get_unread_counts_by_keywords(["AI", "ECON"])
        self.assertEqual(batch["AI"], self.mgr.get_unread_count("AI"))
        self.assertEqual(batch["ECON"], self.mgr.get_unread_count("ECON"))

    def test_query_key_scopes_same_db_keyword_independently(self):
        q1 = build_fetch_key("AI finance", [])
        q2 = build_fetch_key("AI robotics", [])
        self.mgr.upsert_news(
            [self._make_item(110, "2026-01-10T09:00:00")],
            "AI",
            query_key=q1,
        )
        self.mgr.upsert_news(
            [self._make_item(120, "2026-01-11T09:00:00")],
            "AI",
            query_key=q2,
        )

        rows_q1 = self.mgr.fetch_news("AI", query_key=q1)
        rows_q2 = self.mgr.fetch_news("AI", query_key=q2)

        self.assertEqual([row["link"] for row in rows_q1], ["https://example.com/110"])
        self.assertEqual([row["link"] for row in rows_q2], ["https://example.com/120"])
        self.assertEqual(self.mgr.get_counts("AI", query_key=q1), 1)
        self.assertEqual(self.mgr.get_counts("AI", query_key=q2), 1)

    def test_same_link_can_exist_in_two_query_keys(self):
        shared = self._make_item(130, "2026-01-10T09:00:00")
        q1 = build_fetch_key("AI finance", [])
        q2 = build_fetch_key("AI robotics", [])

        self.mgr.upsert_news([shared], "AI", query_key=q1)
        self.mgr.upsert_news([shared], "AI", query_key=q2)

        self.assertEqual(self.mgr.count_news("AI", query_key=q1), 1)
        self.assertEqual(self.mgr.count_news("AI", query_key=q2), 1)

    def test_get_unread_counts_by_query_keys_matches_single_queries(self):
        q1 = build_fetch_key("AI finance", [])
        q2 = build_fetch_key("AI robotics", [])
        self.mgr.upsert_news([self._make_item(140, "2026-01-10T09:00:00")], "AI", query_key=q1)
        self.mgr.upsert_news([self._make_item(141, "2026-01-11T09:00:00")], "AI", query_key=q2)

        self.mgr.update_status("https://example.com/141", "is_read", 1)

        batch = self.mgr.get_unread_counts_by_query_keys([q1, q2])
        self.assertEqual(batch[q1], self.mgr.get_unread_count("AI", query_key=q1))
        self.assertEqual(batch[q2], self.mgr.get_unread_count("AI", query_key=q2))

    def test_fetch_news_exclude_words_matches_in_memory_filter(self):
        items = [
            {
                "title": "AI model launch",
                "description": "summary update",
                "link": "https://example.com/ai-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI ad market analysis",
                "description": "contains ad keyword",
                "link": "https://example.com/ai-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI coin outlook",
                "description": "contains coin keyword",
                "link": "https://example.com/ai-3",
                "pubDate": "2026-01-03T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")

        all_rows = self.mgr.fetch_news("AI")
        sql_filtered = self.mgr.fetch_news("AI", exclude_words=["ad", "coin"])

        expected = [
            row for row in all_rows
            if not any(ex in row.get("title", "") or ex in row.get("description", "") for ex in ["ad", "coin"])
        ]
        self.assertEqual([r["link"] for r in sql_filtered], [r["link"] for r in expected])

    def test_count_news_supports_only_unread_with_exclude_words(self):
        items = [
            {
                "title": "AI launch",
                "description": "general",
                "link": "https://example.com/cnt-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI coin outlook",
                "description": "coin keyword",
                "link": "https://example.com/cnt-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")
        self.mgr.update_status("https://example.com/cnt-1", "is_read", 1)

        unread_all = self.mgr.count_news("AI", only_unread=True)
        unread_excluding_coin = self.mgr.count_news(
            "AI",
            only_unread=True,
            exclude_words=["coin"],
        )

        self.assertEqual(unread_all, 1)
        self.assertEqual(unread_excluding_coin, 0)

    def test_count_news_states_matches_total_and_unread_scope(self):
        q1 = build_fetch_key("AI launch", ["coin"])
        items = [
            {
                "title": "AI launch",
                "description": "general",
                "link": "https://example.com/state-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI coin outlook",
                "description": "coin keyword",
                "link": "https://example.com/state-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI", query_key=q1)
        self.mgr.update_status("https://example.com/state-1", "is_read", 1)

        summary = self.mgr.count_news_states("AI", query_key=q1, exclude_words=["coin"])

        self.assertIsInstance(summary, app.NewsCountSummary)
        self.assertEqual(summary.total_count, self.mgr.count_news("AI", query_key=q1, exclude_words=["coin"]))
        self.assertEqual(
            summary.unread_count,
            self.mgr.count_news("AI", query_key=q1, exclude_words=["coin"], only_unread=True),
        )

    def test_init_db_creates_idx_nk_keyword_dup_idempotently(self):
        self.mgr.init_db()
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_nk_keyword_dup'"
            ).fetchone()
            self.assertIsNotNone(row)
        finally:
            conn.close()

    def test_upsert_news_raises_database_write_error_and_rolls_back(self):
        item = self._make_item(999, "2026-01-01T09:00:00")

        with mock.patch.object(
            self.mgr,
            "_recalculate_duplicate_flags_for_query_key_hashes",
            side_effect=sqlite3.Error("disk full"),
        ):
            with self.assertRaises(app.DatabaseWriteError):
                self.mgr.upsert_news([item], "AI")

        self.assertEqual(self.mgr.count_news("AI"), 0)

    def test_upsert_news_detailed_reports_new_links_and_duplicate_memberships_once(self):
        q1 = build_fetch_key("AI", [])
        self.mgr.upsert_news(
            [
                {
                    "title": "Same title",
                    "description": "seed",
                    "link": "https://example.com/existing",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                }
            ],
            "AI",
            query_key=q1,
        )

        result = self.mgr.upsert_news_detailed(
            [
                {
                    "title": "Same title",
                    "description": "updated existing",
                    "link": "https://example.com/existing",
                    "pubDate": "2026-01-02T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "Same title",
                    "description": "new duplicate",
                    "link": "https://example.com/new-dup",
                    "pubDate": "2026-01-03T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "temporary title",
                    "description": "first duplicate batch value",
                    "link": "https://example.com/new-unique",
                    "pubDate": "2026-01-04T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "Final unique title",
                    "description": "last duplicate batch value wins",
                    "link": "https://example.com/new-unique",
                    "pubDate": "2026-01-05T09:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
            query_key=q1,
        )

        self.assertIsInstance(result, app.NewsUpsertResult)
        self.assertEqual(result.added_count, 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(
            result.new_links,
            ("https://example.com/new-dup", "https://example.com/new-unique"),
        )
        rows = {row["link"]: row for row in self.mgr.fetch_news("AI", query_key=q1)}
        self.assertEqual(rows["https://example.com/new-unique"]["title"], "Final unique title")
        self.assertEqual(rows["https://example.com/new-unique"]["description"], "last duplicate batch value wins")

    def test_repeated_identical_upsert_does_not_recalculate_duplicates(self):
        q1 = build_fetch_key("AI", [])
        item = {
            "title": "Stable title",
            "description": "same payload",
            "link": "https://example.com/stable",
            "pubDate": "2026-01-01T09:00:00",
            "publisher": "example.com",
        }
        self.mgr.upsert_news([item], "AI", query_key=q1)

        with mock.patch.object(self.mgr, "_recalculate_duplicate_flags_for_query_key_hashes") as recalc:
            result = self.mgr.upsert_news_detailed([dict(item)], "AI", query_key=q1)

        self.assertEqual(result, app.NewsUpsertResult(0, 0, ()))
        recalc.assert_not_called()
        self.assertEqual(self.mgr.count_news("AI", query_key=q1), 1)

    def test_init_db_backfills_all_missing_fields_beyond_chunk_limits(self):
        self.mgr.close()
        self.db_path.unlink(missing_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                CREATE TABLE news (
                    link TEXT PRIMARY KEY,
                    keyword TEXT,
                    title TEXT,
                    description TEXT,
                    pubDate TEXT,
                    publisher TEXT,
                    is_read INTEGER DEFAULT 0,
                    is_bookmarked INTEGER DEFAULT 0,
                    pubDate_ts REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    notes TEXT,
                    title_hash TEXT,
                    is_duplicate INTEGER DEFAULT 0
                )
                """
            )
            rows = [
                (
                    f"https://example.com/legacy-{idx}",
                    "AI",
                    f"legacy-title-{idx}",
                    f"legacy-desc-{idx}",
                    f"2026-01-{(idx % 28) + 1:02d}T09:00:00",
                    "example.com",
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    0,
                )
                for idx in range(5005)
            ]
            conn.executemany(
                """
                INSERT INTO news (
                    link, keyword, title, description, pubDate, publisher,
                    is_read, is_bookmarked, pubDate_ts, created_at, notes, title_hash, is_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        self.mgr = app.DatabaseManager(str(self.db_path), max_connections=2)

        verify_conn = sqlite3.connect(str(self.db_path))
        try:
            title_hash_nulls = verify_conn.execute(
                "SELECT COUNT(*) FROM news WHERE title_hash IS NULL"
            ).fetchone()[0]
            pubdate_ts_nulls = verify_conn.execute(
                "SELECT COUNT(*) FROM news WHERE pubDate_ts IS NULL"
            ).fetchone()[0]
            sample_row = verify_conn.execute(
                "SELECT title_hash, pubDate_ts FROM news ORDER BY link LIMIT 1"
            ).fetchone()
        finally:
            verify_conn.close()

        self.assertEqual(title_hash_nulls, 0)
        self.assertEqual(pubdate_ts_nulls, 0)
        self.assertIsNotNone(sample_row)
        assert sample_row is not None
        self.assertTrue(sample_row[0])
        self.assertGreater(sample_row[1], 0)

    def test_get_statistics_duplicates_uses_news_keywords(self):
        same_title = "duplicate stats title"
        items = [
            {
                "title": same_title,
                "description": "desc-a",
                "link": "https://example.com/dup-a",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": same_title,
                "description": "desc-b",
                "link": "https://example.com/dup-b",
                "pubDate": "2026-01-01T10:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")

        stats = self.mgr.get_statistics()
        self.assertEqual(stats["duplicates"], 2)

    def test_same_link_reingest_is_not_counted_as_duplicate(self):
        item = self._make_item(77, "2026-01-07T09:00:00")

        first = self.mgr.upsert_news([item], "AI")
        second = self.mgr.upsert_news([item], "AI")

        self.assertEqual(first, (1, 0))
        self.assertEqual(second, (0, 0))

        rows = self.mgr.fetch_news("AI")
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["is_duplicate"]), 0)

        stats = self.mgr.get_statistics()
        self.assertEqual(stats["duplicates"], 0)

    def test_recalculate_duplicate_flags_repairs_wrong_values(self):
        same_title = "duplicate repair title"
        self.mgr.upsert_news(
            [
                {
                    "title": same_title,
                    "description": "desc-1",
                    "link": "https://example.com/fix-1",
                    "pubDate": "2026-01-01T10:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": same_title,
                    "description": "desc-2",
                    "link": "https://example.com/fix-2",
                    "pubDate": "2026-01-01T11:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
        )

        conn = self.mgr.get_connection()
        try:
            with conn:
                conn.execute("UPDATE news_keywords SET is_duplicate=0 WHERE keyword='AI'")
        finally:
            self.mgr.return_connection(conn)

        updated = self.mgr.recalculate_duplicate_flags()
        self.assertGreaterEqual(updated, 2)

        rows = self.mgr.fetch_news("AI")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(int(row["is_duplicate"]) == 1 for row in rows))

    def test_mark_links_as_read_updates_only_selected_links(self):
        items = [
            self._make_item(100, "2026-01-01T09:00:00"),
            self._make_item(101, "2026-01-02T09:00:00"),
            self._make_item(102, "2026-01-03T09:00:00"),
        ]
        self.mgr.upsert_news(items, "AI")

        updated = self.mgr.mark_links_as_read(
            ["https://example.com/100", "https://example.com/102"]
        )
        self.assertEqual(updated, 2)

        rows = self.mgr.fetch_news("AI")
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/100"], 1)
        self.assertEqual(read_by_link["https://example.com/101"], 0)
        self.assertEqual(read_by_link["https://example.com/102"], 1)

    def test_mark_query_as_read_respects_exclude_words(self):
        items = [
            {
                "title": "AI launch",
                "description": "plain item",
                "link": "https://example.com/mqr-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI ad market",
                "description": "contains ad keyword",
                "link": "https://example.com/mqr-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")

        updated = self.mgr.mark_query_as_read("AI", exclude_words=["ad"])
        self.assertEqual(updated, 1)

        rows = self.mgr.fetch_news("AI")
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/mqr-1"], 1)
        self.assertEqual(read_by_link["https://example.com/mqr-2"], 0)

    def test_mark_query_as_read_is_limited_to_query_key_membership(self):
        q1 = build_fetch_key("AI finance", [])
        q2 = build_fetch_key("AI robotics", [])
        self.mgr.upsert_news([self._make_item(201, "2026-01-01T09:00:00")], "AI", query_key=q1)
        self.mgr.upsert_news([self._make_item(202, "2026-01-02T09:00:00")], "AI", query_key=q2)

        updated = self.mgr.mark_query_as_read("AI", query_key=q1)
        self.assertEqual(updated, 1)

        rows_q1 = self.mgr.fetch_news("AI", query_key=q1)
        rows_q2 = self.mgr.fetch_news("AI", query_key=q2)
        self.assertEqual(int(rows_q1[0]["is_read"]), 1)
        self.assertEqual(int(rows_q2[0]["is_read"]), 0)

    def test_mark_query_as_read_respects_filter_text_hide_duplicates_and_dates(self):
        q1 = build_fetch_key("AI finance", [])
        same_title = "same-duplicate-title"
        items = [
            {
                "title": same_title,
                "description": "duplicate one",
                "link": "https://example.com/filter-dup-1",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": same_title,
                "description": "duplicate two",
                "link": "https://example.com/filter-dup-2",
                "pubDate": "2026-01-03T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "beta launch",
                "description": "visible january row",
                "link": "https://example.com/filter-keep",
                "pubDate": "2026-01-04T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "beta february",
                "description": "outside date range",
                "link": "https://example.com/filter-feb",
                "pubDate": "2026-02-04T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI", query_key=q1)

        updated = self.mgr.mark_query_as_read(
            "AI",
            filter_txt="beta",
            hide_duplicates=True,
            start_date="2026-01-01",
            end_date="2026-01-31",
            query_key=q1,
        )
        self.assertEqual(updated, 1)

        rows = self.mgr.fetch_news("AI", query_key=q1)
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/filter-keep"], 1)
        self.assertEqual(read_by_link["https://example.com/filter-feb"], 0)
        self.assertEqual(read_by_link["https://example.com/filter-dup-1"], 0)
        self.assertEqual(read_by_link["https://example.com/filter-dup-2"], 0)

    def test_mark_query_as_read_matches_fetch_news_multi_token_filter_scope(self):
        q1 = build_fetch_key("AI finance", [])
        items = [
            {
                "title": "AI quarterly update",
                "description": "Samsung launch roadmap",
                "link": "https://example.com/multi-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "launch only",
                "description": "without second token",
                "link": "https://example.com/multi-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI only",
                "description": "without matching token",
                "link": "https://example.com/multi-3",
                "pubDate": "2026-01-03T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI", query_key=q1)

        visible = self.mgr.fetch_news("AI", query_key=q1, filter_txt="launch AI")
        self.assertEqual([row["link"] for row in visible], ["https://example.com/multi-1"])

        updated = self.mgr.mark_query_as_read("AI", query_key=q1, filter_txt="launch AI")
        self.assertEqual(updated, 1)
        rows = self.mgr.fetch_news("AI", query_key=q1)
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/multi-1"], 1)
        self.assertEqual(read_by_link["https://example.com/multi-2"], 0)
        self.assertEqual(read_by_link["https://example.com/multi-3"], 0)

        self.assertTrue(self.mgr.update_status("https://example.com/multi-1", "is_read", 0))
        updated_chunked = self.mgr.mark_query_as_read_chunked(
            "AI",
            query_key=q1,
            filter_txt="launch AI",
            chunk_size=1,
        )
        self.assertEqual(updated_chunked, 1)

    def test_mark_query_as_read_only_bookmark_scope_respects_filter_text(self):
        items = [
            {
                "title": "bookmark launch",
                "description": "keep",
                "link": "https://example.com/bookmark-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "general launch",
                "description": "not bookmarked",
                "link": "https://example.com/bookmark-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")
        self.assertTrue(self.mgr.update_status("https://example.com/bookmark-1", "is_bookmarked", 1))

        updated = self.mgr.mark_query_as_read(
            "AI",
            only_bookmark=True,
            filter_txt="bookmark",
        )
        self.assertEqual(updated, 1)

        rows = self.mgr.fetch_news("AI")
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/bookmark-1"], 1)
        self.assertEqual(read_by_link["https://example.com/bookmark-2"], 0)

    def test_get_top_publishers_respects_exclude_words(self):
        items = [
            {
                "title": "AI launch",
                "description": "plain item",
                "link": "https://example.com/pub-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "alpha.com",
            },
            {
                "title": "AI ad market",
                "description": "contains ad keyword",
                "link": "https://example.com/pub-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "beta.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")

        publishers = self.mgr.get_top_publishers("AI", exclude_words=["ad"], limit=10)
        self.assertEqual(publishers, [("alpha.com", 1)])

    def test_get_top_publishers_is_limited_to_query_key(self):
        q1 = build_fetch_key("AI finance", [])
        q2 = build_fetch_key("AI robotics", [])
        self.mgr.upsert_news(
            [
                {
                    "title": "finance title",
                    "description": "finance",
                    "link": "https://example.com/pub-q1",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "finance.com",
                }
            ],
            "AI",
            query_key=q1,
        )
        self.mgr.upsert_news(
            [
                {
                    "title": "robotics title",
                    "description": "robotics",
                    "link": "https://example.com/pub-q2",
                    "pubDate": "2026-01-02T09:00:00",
                    "publisher": "robotics.com",
                }
            ],
            "AI",
            query_key=q2,
        )

        publishers = self.mgr.get_top_publishers("AI", query_key=q1, limit=10)
        self.assertEqual(publishers, [("finance.com", 1)])

    def test_get_existing_links_for_query_is_query_key_scoped(self):
        q1 = app.build_fetch_key("AI finance", [])
        q2 = app.build_fetch_key("AI robotics", [])
        shared = {
            "title": "shared title",
            "description": "shared",
            "link": "https://example.com/shared-scope",
            "pubDate": "2026-01-01T09:00:00",
            "publisher": "example.com",
        }
        other = {
            "title": "other title",
            "description": "other",
            "link": "https://example.com/other-scope",
            "pubDate": "2026-01-02T09:00:00",
            "publisher": "example.com",
        }

        self.mgr.upsert_news([shared], "AI", query_key=q1)
        self.mgr.upsert_news([other], "AI", query_key=q2)

        existing_q1 = self.mgr.get_existing_links_for_query(
            [shared["link"], other["link"]],
            keyword="AI",
            query_key=q1,
        )
        existing_q2 = self.mgr.get_existing_links_for_query(
            [shared["link"], other["link"]],
            keyword="AI",
            query_key=q2,
        )

        self.assertEqual(existing_q1, {shared["link"]})
        self.assertEqual(existing_q2, {other["link"]})

    def test_delete_link_recalculates_duplicate_flags(self):
        same_title = "delete-link-duplicate-title"
        self.mgr.upsert_news(
            [
                {
                    "title": same_title,
                    "description": "desc-1",
                    "link": "https://example.com/del-1",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": same_title,
                    "description": "desc-2",
                    "link": "https://example.com/del-2",
                    "pubDate": "2026-01-01T10:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
        )

        self.assertTrue(self.mgr.delete_link("https://example.com/del-1"))

        rows = self.mgr.fetch_news("AI")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["link"], "https://example.com/del-2")
        self.assertEqual(int(rows[0]["is_duplicate"]), 0)
        self.assertEqual(self.mgr.get_statistics()["duplicates"], 0)

    def test_delete_all_news_recalculates_duplicates_for_bookmark_survivor(self):
        same_title = "delete-all-duplicate-title"
        self.mgr.upsert_news(
            [
                {
                    "title": same_title,
                    "description": "desc-1",
                    "link": "https://example.com/all-1",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": same_title,
                    "description": "desc-2",
                    "link": "https://example.com/all-2",
                    "pubDate": "2026-01-01T10:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
        )
        self.assertTrue(self.mgr.update_status("https://example.com/all-1", "is_bookmarked", 1))

        deleted = self.mgr.delete_all_news()
        self.assertEqual(deleted, 1)

        rows = self.mgr.fetch_news("AI")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["link"], "https://example.com/all-1")
        self.assertEqual(int(rows[0]["is_duplicate"]), 0)
        self.assertEqual(self.mgr.get_statistics()["duplicates"], 0)

    def test_delete_old_news_raises_database_write_error_on_failure(self):
        with mock.patch.object(
            self.mgr,
            "_run_chunked_news_delete",
            side_effect=app.DatabaseWriteError("delete_old_news", "locked"),
        ):
            with self.assertRaises(app.DatabaseWriteError):
                self.mgr.delete_old_news(30)

    def test_delete_all_news_raises_database_write_error_on_failure(self):
        with mock.patch.object(
            self.mgr,
            "_run_chunked_news_delete",
            side_effect=app.DatabaseWriteError("delete_all_news", "locked"),
        ):
            with self.assertRaises(app.DatabaseWriteError):
                self.mgr.delete_all_news()

    def test_mark_query_as_read_chunked_matches_scope_rules(self):
        q1 = build_fetch_key("AI finance", [])
        items = [
            {
                "title": "AI launch",
                "description": "plain item",
                "link": "https://example.com/chunked-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI ad market",
                "description": "contains ad keyword",
                "link": "https://example.com/chunked-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI", query_key=q1)

        updated = self.mgr.mark_query_as_read_chunked("AI", exclude_words=["ad"], query_key=q1, chunk_size=1)
        self.assertEqual(updated, 1)

        rows = self.mgr.fetch_news("AI", query_key=q1)
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/chunked-1"], 1)
        self.assertEqual(read_by_link["https://example.com/chunked-2"], 0)

    def test_connection_context_manager_releases_connection(self):
        with self.mgr.connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
            self.assertEqual(int(row[0]), 1)

        conn = self.mgr.get_connection()
        try:
            row = conn.execute("SELECT 1").fetchone()
            self.assertEqual(int(row[0]), 1)
        finally:
            self.mgr.return_connection(conn)

    def test_mark_query_as_read_does_not_call_mark_links_as_read(self):
        self.mgr.upsert_news([self._make_item(300, "2026-01-03T09:00:00")], "AI")

        with mock.patch.object(
            self.mgr,
            "mark_links_as_read",
            side_effect=AssertionError("mark_links_as_read should not be called"),
        ):
            updated = self.mgr.mark_query_as_read("AI")
        self.assertEqual(updated, 1)

    def test_delete_old_news_skips_pubdate_parse_failure_rows(self):
        stale = {
            "title": "stale",
            "description": "old",
            "link": "https://example.com/stale",
            "pubDate": "2020-01-01T09:00:00",
            "publisher": "example.com",
        }
        bad_date = {
            "title": "bad-date",
            "description": "parse failed",
            "link": "https://example.com/bad-date",
            "pubDate": "invalid-date-value",
            "publisher": "example.com",
        }
        self.mgr.upsert_news([stale, bad_date], "AI")

        deleted = self.mgr.delete_old_news(30)
        self.assertEqual(deleted, 1)

        rows = self.mgr.fetch_news("AI")
        links = {row["link"] for row in rows}
        self.assertIn("https://example.com/bad-date", links)
        self.assertNotIn("https://example.com/stale", links)

    def test_get_total_unread_count_matches_read_updates(self):
        self.mgr.upsert_news([self._make_item(401, "2026-01-01T09:00:00")], "AI")
        self.mgr.upsert_news([self._make_item(402, "2026-01-02T09:00:00")], "ECON")
        self.assertEqual(self.mgr.get_total_unread_count(), 2)

        self.assertTrue(self.mgr.update_status("https://example.com/401", "is_read", 1))
        self.assertEqual(self.mgr.get_total_unread_count(), 1)

    def test_noop_state_and_tag_saves_do_not_update_timestamps(self):
        link = "https://example.com/noop"
        self.mgr.upsert_news(
            [
                {
                    "title": "noop state",
                    "description": "noop",
                    "link": link,
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                }
            ],
            "AI",
        )

        self.assertTrue(self.mgr.update_status(link, "is_read", 1))
        self.assertTrue(self.mgr.update_status(link, "is_bookmarked", 1))
        self.assertTrue(self.mgr.save_note(link, "same note"))
        self.assertTrue(self.mgr.set_tags(link, ["alpha", "beta"]))
        with self.mgr.connection() as conn:
            before = conn.execute(
                """
                SELECT read_updated_at, bookmark_updated_at, notes_updated_at
                FROM news
                WHERE link=?
                """,
                (link,),
            ).fetchone()
            tag_before = conn.execute(
                "SELECT tags_updated_at FROM news_tag_state WHERE link=?",
                (link,),
            ).fetchone()[0]

        self.assertFalse(self.mgr.update_status(link, "is_read", 1))
        self.assertFalse(self.mgr.update_status(link, "is_bookmarked", 1))
        self.assertFalse(self.mgr.save_note(link, "same note"))
        self.assertFalse(self.mgr.set_tags(link, ["beta", "alpha"]))
        with self.mgr.connection() as conn:
            after = conn.execute(
                """
                SELECT read_updated_at, bookmark_updated_at, notes_updated_at
                FROM news
                WHERE link=?
                """,
                (link,),
            ).fetchone()
            tag_after = conn.execute(
                "SELECT tags_updated_at FROM news_tag_state WHERE link=?",
                (link,),
            ).fetchone()[0]

        self.assertEqual(before, after)
        self.assertEqual(tag_before, tag_after)

    def test_explicit_delete_is_soft_hidden_and_restorable_but_cleanup_is_hard_delete(self):
        same_title = "soft-delete duplicate"
        self.mgr.upsert_news(
            [
                {
                    "title": same_title,
                    "description": "first",
                    "link": "https://example.com/soft-1",
                    "pubDate": "2026-01-01T09:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": same_title,
                    "description": "second",
                    "link": "https://example.com/soft-2",
                    "pubDate": "2026-01-01T10:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
        )

        self.assertTrue(self.mgr.delete_link("https://example.com/soft-1"))
        visible = self.mgr.fetch_news("AI")
        self.assertEqual([row["link"] for row in visible], ["https://example.com/soft-2"])
        self.assertEqual(int(visible[0]["is_duplicate"]), 0)
        self.assertEqual(self.mgr.count_archive(), 1)
        with_deleted = self.mgr.search_archive(include_deleted=True, limit=10)
        deleted_rows = [row for row in with_deleted if row["link"] == "https://example.com/soft-1"]
        self.assertEqual(len(deleted_rows), 1)
        self.assertEqual(int(deleted_rows[0]["is_deleted"]), 1)

        self.assertTrue(self.mgr.restore_deleted_link("https://example.com/soft-1"))
        self.assertEqual(self.mgr.count_news("AI"), 2)

        self.mgr.upsert_news(
            [
                {
                    "title": "old cleanup",
                    "description": "old",
                    "link": "https://example.com/hard-old",
                    "pubDate": "2020-01-01T09:00:00",
                    "publisher": "example.com",
                }
            ],
            "AI",
        )
        self.assertEqual(self.mgr.delete_old_news(365), 1)
        self.assertFalse(
            any(row["link"] == "https://example.com/hard-old" for row in self.mgr.search_archive(include_deleted=True, limit=20))
        )

    def test_like_filters_treat_percent_underscore_and_backslash_as_literals(self):
        q1 = build_fetch_key("AI literals", [])
        rows = [
            {
                "title": r"literal 100%_match \ path",
                "description": "keep",
                "link": "https://example.com/literal-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": r"literal 100Xmatch \ path",
                "description": "wildcard false positive",
                "link": "https://example.com/literal-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "code_% scope",
                "description": "literal mark read target",
                "link": "https://example.com/literal-3",
                "pubDate": "2026-01-03T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "codeAX scope",
                "description": "should stay unread",
                "link": "https://example.com/literal-4",
                "pubDate": "2026-01-04T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(rows, "AI", query_key=q1)
        self.assertTrue(self.mgr.save_note("https://example.com/literal-1", r"memo 10_% \ done"))
        self.assertTrue(self.mgr.save_note("https://example.com/literal-2", "memo 100x done"))

        filtered = self.mgr.fetch_news("AI", query_key=q1, filter_txt=r"100%_match \ path")
        self.assertEqual([row["link"] for row in filtered], ["https://example.com/literal-1"])
        excluded = self.mgr.fetch_news("AI", query_key=q1, exclude_words=["100%_match"])
        self.assertNotIn("https://example.com/literal-1", {row["link"] for row in excluded})
        self.assertIn("https://example.com/literal-2", {row["link"] for row in excluded})
        notes = self.mgr.search_archive(notes_txt=r"10_% \ done")
        self.assertEqual([row["link"] for row in notes], ["https://example.com/literal-1"])

        updated = self.mgr.mark_query_as_read("AI", query_key=q1, filter_txt="code_%")
        self.assertEqual(updated, 1)
        states = {row["link"]: int(row["is_read"]) for row in self.mgr.fetch_news("AI", query_key=q1)}
        self.assertEqual(states["https://example.com/literal-3"], 1)
        self.assertEqual(states["https://example.com/literal-4"], 0)


class TestDbSchemaMigration(unittest.TestCase):
    def test_init_db_migrates_legacy_news_keywords_to_query_key_schema(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.sqlite"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE news (
                        link TEXT PRIMARY KEY,
                        keyword TEXT,
                        title TEXT,
                        description TEXT,
                        pubDate TEXT,
                        publisher TEXT,
                        is_read INTEGER DEFAULT 0,
                        is_bookmarked INTEGER DEFAULT 0,
                        pubDate_ts REAL,
                        created_at REAL,
                        notes TEXT,
                        title_hash TEXT,
                        is_duplicate INTEGER DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE news_keywords (
                        link TEXT NOT NULL,
                        keyword TEXT NOT NULL,
                        is_duplicate INTEGER DEFAULT 0,
                        PRIMARY KEY (link, keyword)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO news (link, keyword, title, description, pubDate, publisher, title_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "https://example.com/legacy",
                        "AI",
                        "legacy-title",
                        "legacy-desc",
                        "2026-01-01T09:00:00",
                        "example.com",
                        "legacy-hash",
                    ),
                )
                conn.execute(
                    "INSERT INTO news_keywords (link, keyword, is_duplicate) VALUES (?, ?, ?)",
                    ("https://example.com/legacy", "AI", 0),
                )
                conn.commit()
            finally:
                conn.close()

            mgr = app.DatabaseManager(str(db_path), max_connections=2)
            try:
                conn = sqlite3.connect(str(db_path))
                try:
                    columns = {
                        row[1]: row
                        for row in conn.execute("PRAGMA table_info(news_keywords)").fetchall()
                    }
                    self.assertIn("query_key", columns)
                    self.assertEqual(int(columns["link"][5]), 1)
                    self.assertEqual(int(columns["query_key"][5]), 2)

                    row = conn.execute(
                        "SELECT keyword, query_key FROM news_keywords WHERE link = ?",
                        ("https://example.com/legacy",),
                    ).fetchone()
                    self.assertEqual(row, ("AI", "ai|"))

                    indexes = {
                        row[1]
                        for row in conn.execute("PRAGMA index_list(news_keywords)").fetchall()
                    }
                    self.assertIn("idx_nk_query_key_keyword", indexes)
                    self.assertIn("idx_nk_query_key_keyword_dup", indexes)

                    news_indexes = {
                        row[1]
                        for row in conn.execute("PRAGMA index_list(news)").fetchall()
                    }
                    self.assertIn("idx_bookmarked_read_ts", news_indexes)
                finally:
                    conn.close()
            finally:
                mgr.close()

