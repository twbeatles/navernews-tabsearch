import unittest

from core.query_parser import build_fetch_key
from core.workers import DBQueryScope, DBWorker


class _FakeDb:
    def __init__(self):
        self.calls = []
        self.interrupts = 0

    def count_news(self, **kwargs):
        self.calls.append(("count_news", kwargs))
        return 45 if kwargs.get("only_unread") else 123

    def fetch_news(self, **kwargs):
        self.calls.append(("fetch_news", kwargs))
        return [{"link": "https://example.com/1", "title": "row"}]

    def open_read_connection(self, timeout=0):
        self.calls.append(("open_read_connection", {"timeout": timeout}))
        return _FakeConn()

    def close_read_connection(self, _conn):
        self.calls.append(("close_read_connection", {}))

    def interrupt_connection(self, _conn):
        self.interrupts += 1


class _FakeConn:
    def execute(self, _sql):
        return None


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

        self.assertEqual(
            [call[0] for call in db.calls],
            ["open_read_connection", "count_news", "count_news", "fetch_news", "close_read_connection"],
        )

        count_kwargs = db.calls[1][1]
        unread_count_kwargs = db.calls[2][1]
        fetch_kwargs = db.calls[3][1]
        self.assertEqual(count_kwargs["keyword"], "AI")
        self.assertEqual(count_kwargs["filter_txt"], "launch")
        self.assertEqual(count_kwargs["hide_duplicates"], True)
        self.assertEqual(count_kwargs["start_date"], "2026-01-01")
        self.assertEqual(count_kwargs["end_date"], "2026-01-31")
        self.assertEqual(count_kwargs["query_key"], build_fetch_key("AI finance", ["coin"]))
        self.assertIn("conn", count_kwargs)
        self.assertEqual(unread_count_kwargs["only_unread"], True)
        self.assertEqual(fetch_kwargs["limit"], 50)
        self.assertEqual(fetch_kwargs["offset"], 100)
        self.assertEqual(worker.last_unread_count, 45)

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

        self.assertEqual(
            [call[0] for call in db.calls],
            ["open_read_connection", "count_news", "fetch_news", "close_read_connection"],
        )
        self.assertEqual(db.calls[1][1]["only_unread"], True)
        self.assertEqual(db.calls[2][1]["offset"], 50)
        self.assertEqual(worker.last_unread_count, 45)
        self.assertEqual(
            finished_payloads,
            [([{"link": "https://example.com/1", "title": "row"}], 321)],
        )

    def test_dbworker_stop_interrupts_dedicated_read_connection(self):
        db = _FakeDb()
        worker = DBWorker(
            db,
            scope=self._make_scope(),
            limit=50,
            offset=0,
            include_total=False,
            known_total_count=0,
        )
        worker._conn = _FakeConn()

        worker.stop()

        self.assertEqual(db.interrupts, 1)


if __name__ == "__main__":
    unittest.main()
