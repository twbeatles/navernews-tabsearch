import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.query_parser import build_fetch_key


class TestFtsSearchAcceleration(unittest.TestCase):
    def _make_manager(self):
        td = tempfile.TemporaryDirectory()
        db_path = Path(td.name) / "news.sqlite"
        mgr = DatabaseManager(str(db_path))
        self.addCleanup(td.cleanup)
        self.addCleanup(mgr.close)
        return mgr

    def _seed_rows(self, mgr: DatabaseManager) -> str:
        query_key = build_fetch_key("AI launch", [])
        mgr.upsert_news(
            [
                {
                    "title": "AI launch roadmap",
                    "description": "platform release plan",
                    "link": "https://example.com/1",
                    "pubDate": "2026-04-09T10:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "AI launchpad beta",
                    "description": "single token substring fallback",
                    "link": "https://example.com/2",
                    "pubDate": "2026-04-09T11:00:00",
                    "publisher": "example.com",
                },
                {
                    "title": "Other update",
                    "description": "unrelated",
                    "link": "https://example.com/3",
                    "pubDate": "2026-04-09T12:00:00",
                    "publisher": "example.com",
                },
            ],
            "AI",
            query_key=query_key,
        )
        return query_key

    def test_backfill_completes_and_multi_token_filter_matches_existing_semantics(self):
        mgr = self._make_manager()
        query_key = self._seed_rows(mgr)

        while True:
            result = mgr.backfill_news_fts_chunk(limit=1)
            if result["done"]:
                break

        self.assertTrue(mgr.is_news_fts_backfill_complete())
        self.assertEqual(
            mgr.count_news(keyword="AI", query_key=query_key, filter_txt="AI launch"),
            1,
        )
        rows = mgr.fetch_news(keyword="AI", query_key=query_key, filter_txt="AI launch")
        self.assertEqual([row["link"] for row in rows], ["https://example.com/1"])

    def test_single_token_filter_falls_back_to_like_semantics(self):
        mgr = self._make_manager()
        query_key = self._seed_rows(mgr)

        while True:
            result = mgr.backfill_news_fts_chunk(limit=10)
            if result["done"]:
                break

        rows = mgr.fetch_news(keyword="AI", query_key=query_key, filter_txt="launch")
        self.assertEqual(
            {row["link"] for row in rows},
            {"https://example.com/1", "https://example.com/2"},
        )


if __name__ == "__main__":
    unittest.main()
