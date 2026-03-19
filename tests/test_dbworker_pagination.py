import unittest

from core.query_parser import build_fetch_key
from core.workers import DBWorker


class _FakeDb:
    def __init__(self):
        self.calls = []

    def count_news(self, keyword, **kwargs):
        self.calls.append(("count_news", keyword, kwargs))
        return 123

    def fetch_news(self, keyword, **kwargs):
        self.calls.append(("fetch_news", keyword, kwargs))
        return [{"link": "https://example.com/1", "title": "row"}]


class TestDbWorkerPagination(unittest.TestCase):
    def test_dbworker_uses_count_and_paged_fetch_contract(self):
        db = _FakeDb()
        worker = DBWorker(
            db,
            keyword="AI finance -coin",
            filter_txt="launch",
            hide_duplicates=True,
            start_date="2026-01-01",
            end_date="2026-01-31",
            limit=50,
            offset=100,
        )

        finished_payloads = []
        worker.finished.connect(lambda data, total_count: finished_payloads.append((data, total_count)))
        worker.run()

        self.assertEqual(len(db.calls), 2)
        self.assertEqual(db.calls[0][0], "count_news")
        self.assertEqual(db.calls[1][0], "fetch_news")

        expected_query_key = build_fetch_key("AI finance", ["coin"])
        for method_name, keyword, kwargs in db.calls:
            self.assertEqual(keyword, "AI")
            self.assertEqual(kwargs["filter_txt"], "launch")
            self.assertEqual(kwargs["hide_duplicates"], True)
            self.assertEqual(kwargs["start_date"], "2026-01-01")
            self.assertEqual(kwargs["end_date"], "2026-01-31")
            self.assertEqual(kwargs["query_key"], expected_query_key)
            if method_name == "fetch_news":
                self.assertEqual(kwargs["limit"], 50)
                self.assertEqual(kwargs["offset"], 100)

        self.assertEqual(
            finished_payloads,
            [([{"link": "https://example.com/1", "title": "row"}], 123)],
        )


if __name__ == "__main__":
    unittest.main()
