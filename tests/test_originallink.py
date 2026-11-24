import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager


def _item(link: str, **overrides):
    item = {
        "title": f"Title {link}",
        "description": f"Description {link}",
        "link": link,
        "pubDate": "Mon, 01 Jan 2024 00:00:00 +0000",
        "publisher": "example.com",
    }
    item.update(overrides)
    return item


class TestOriginallinkStorage(unittest.TestCase):
    def _db(self, path: Path) -> DatabaseManager:
        return DatabaseManager(str(path), max_connections=2)

    def test_upsert_stores_and_returns_originallink(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "news.db")
            try:
                db.upsert_news(
                    [
                        _item(
                            "https://n.news.naver.com/article/001",
                            originallink="https://example.com/original/1",
                        )
                    ],
                    "AI",
                    query_key="ai|",
                )
                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    rows[0]["originallink"], "https://example.com/original/1"
                )
            finally:
                db.close()

    def test_upsert_without_originallink_keeps_working(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "news.db")
            try:
                db.upsert_news([_item("https://example.com/legacy")], "AI", query_key="ai|")
                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["originallink"], "")
                # A later fetch carrying the original link backfills it.
                db.upsert_news(
                    [
                        _item(
                            "https://example.com/legacy",
                            originallink="https://example.com/original/legacy",
                        )
                    ],
                    "AI",
                    query_key="ai|",
                )
                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(
                    rows[0]["originallink"], "https://example.com/original/legacy"
                )
            finally:
                db.close()

    def test_existing_value_is_not_cleared_by_empty_update(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(Path(td) / "news.db")
            try:
                db.upsert_news(
                    [
                        _item(
                            "https://example.com/keep",
                            originallink="https://example.com/original/keep",
                        )
                    ],
                    "AI",
                    query_key="ai|",
                )
                db.upsert_news(
                    [_item("https://example.com/keep")], "AI", query_key="ai|"
                )
                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(
                    rows[0]["originallink"], "https://example.com/original/keep"
                )
            finally:
                db.close()

    def test_legacy_database_is_migrated_with_originallink_column(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.db"
            conn = sqlite3.connect(str(db_path))
            try:
                # originallink 도입 이전 실제 DB 형태: 나머지 컬럼은 존재한다.
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
                conn.execute(
                    "INSERT INTO news (link, title, title_hash) VALUES (?, ?, ?)",
                    ("https://example.com/old", "old title", "old-hash"),
                )
                conn.commit()
            finally:
                conn.close()
            db = self._db(db_path)
            try:
                check_conn = sqlite3.connect(str(db_path))
                try:
                    columns = {
                        row[1]
                        for row in check_conn.execute("PRAGMA table_info(news)")
                    }
                finally:
                    check_conn.close()
                self.assertIn("originallink", columns)
                db.upsert_news(
                    [
                        _item(
                            "https://example.com/old",
                            originallink="https://example.com/original/old",
                        )
                    ],
                    "AI",
                    query_key="ai|",
                )
                rows = db.fetch_news("AI", query_key="ai|")
                self.assertEqual(
                    rows[0]["originallink"], "https://example.com/original/old"
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
