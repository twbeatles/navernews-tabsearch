import unittest

from core.query_parser import build_fetch_key
from core.workers import DBQueryScope, DBWorker


class _FakeDb:
    def __init__(self):
        self.calls = []

    def count_news(self, **kwargs):
        self.calls.append(("count_news", kwargs))
        return 123

    def fetch_news(self, **kwargs):
        self.calls.append(("fetch_news", kwargs))
        return [{"link": "https://example.com/1", "title": "row"}]


class TestDbWorkerPagination(unittest.TestCase):
    def _make_scope(self) -> DBQueryScope:
        return DBQueryScope(
            keyword="AI",
            filter_txt="launch",
            sort_mode="최신순",
            hide_duplicates=True,
            exclude_words=("coin",),
            start_date="2026-01-01",
            end_date="2026-01-31",
            query_key=build_fetch_key("AI finance", ["coin"]),
        )

    def test_dbworker_uses_count_and_paged_fetch_contract_for_full_reload(self):
        db = _FakeDb()
        worker = DBWorker(
            db,
            scope=self._make_scope(),
            limit=50,
            offset=100,
            include_total=True,
        )

        finished_payloads = []
        worker.finished.connect(lambda data, total_count: finished_payloads.append((data, total_count)))
        worker.run()

        self.assertEqual([call[0] for call in db.calls], ["count_news", "fetch_news"])

        count_kwargs = db.calls[0][1]
        fetch_kwargs = db.calls[1][1]
        self.assertEqual(count_kwargs["keyword"], "AI")
        self.assertEqual(count_kwargs["filter_txt"], "launch")
        self.assertEqual(count_kwargs["hide_duplicates"], True)
        self.assertEqual(count_kwargs["start_date"], "2026-01-01")
        self.assertEqual(count_kwargs["end_date"], "2026-01-31")
        self.assertEqual(count_kwargs["query_key"], build_fetch_key("AI finance", ["coin"]))
        self.assertEqual(fetch_kwargs["limit"], 50)
        self.assertEqual(fetch_kwargs["offset"], 100)

        self.assertEqual(
            finished_payloads,
            [([{"link": "https://example.com/1", "title": "row"}], 123)],
        )

    def test_dbworker_skips_count_news_for_append_when_total_is_known(self):
        db = _FakeDb()
        worker = DBWorker(
            db,
            scope=self._make_scope(),
            limit=50,
            offset=50,
            include_total=False,
            known_total_count=321,
        )

        finished_payloads = []
        worker.finished.connect(lambda data, total_count: finished_payloads.append((data, total_count)))
        worker.run()

        self.assertEqual([call[0] for call in db.calls], ["fetch_news"])
        self.assertEqual(db.calls[0][1]["offset"], 50)
        self.assertEqual(
            finished_payloads,
            [([{"link": "https://example.com/1", "title": "row"}], 321)],
        )


if __name__ == "__main__":
    unittest.main()
