import tempfile
import unittest
import sqlite3
from pathlib import Path

import news_scraper_pro as app


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

        baseline = self.mgr.fetch_news("AI", sort_mode="최신순")
        paged = self.mgr.fetch_news("AI", sort_mode="최신순", limit=2, offset=1)

        self.assertEqual(len(baseline), 5)
        self.assertEqual(len(paged), 2)
        self.assertEqual([r["link"] for r in paged], [r["link"] for r in baseline[1:3]])

    def test_get_unread_counts_by_keywords_matches_single_queries(self):
        self.mgr.upsert_news([self._make_item(10, "2026-01-10T09:00:00")], "AI")
        self.mgr.upsert_news([self._make_item(20, "2026-01-10T09:00:00")], "ECON")
        self.mgr.upsert_news([self._make_item(21, "2026-01-11T09:00:00")], "ECON")

        self.mgr.update_status("https://example.com/21", "is_read", 1)

        batch = self.mgr.get_unread_counts_by_keywords(["AI", "ECON"])
        self.assertEqual(batch["AI"], self.mgr.get_unread_count("AI"))
        self.assertEqual(batch["ECON"], self.mgr.get_unread_count("ECON"))

    def test_fetch_news_exclude_words_matches_in_memory_filter(self):
        items = [
            {
                "title": "AI 신기술 발표",
                "description": "핵심 내용 요약",
                "link": "https://example.com/ai-1",
                "pubDate": "2026-01-01T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI 광고 시장 분석",
                "description": "광고 키워드 포함",
                "link": "https://example.com/ai-2",
                "pubDate": "2026-01-02T09:00:00",
                "publisher": "example.com",
            },
            {
                "title": "AI 트렌드",
                "description": "코인 관련 언급",
                "link": "https://example.com/ai-3",
                "pubDate": "2026-01-03T09:00:00",
                "publisher": "example.com",
            },
        ]
        self.mgr.upsert_news(items, "AI")

        all_rows = self.mgr.fetch_news("AI", sort_mode="최신순")
        sql_filtered = self.mgr.fetch_news("AI", sort_mode="최신순", exclude_words=["광고", "코인"])

        expected = [
            row for row in all_rows
            if not any(ex in row.get("title", "") or ex in row.get("description", "") for ex in ["광고", "코인"])
        ]
        self.assertEqual([r["link"] for r in sql_filtered], [r["link"] for r in expected])

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

    def test_get_statistics_duplicates_uses_news_keywords(self):
        same_title = "중복 기준 제목"
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

        rows = self.mgr.fetch_news("AI", sort_mode="최신순")
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["is_duplicate"]), 0)

        stats = self.mgr.get_statistics()
        self.assertEqual(stats["duplicates"], 0)

    def test_recalculate_duplicate_flags_repairs_wrong_values(self):
        same_title = "재계산 검증 제목"
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

        rows = self.mgr.fetch_news("AI", sort_mode="최신순")
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

        rows = self.mgr.fetch_news("AI", sort_mode="최신순")
        read_by_link = {row["link"]: int(row["is_read"]) for row in rows}
        self.assertEqual(read_by_link["https://example.com/100"], 1)
        self.assertEqual(read_by_link["https://example.com/101"], 0)
        self.assertEqual(read_by_link["https://example.com/102"], 1)
