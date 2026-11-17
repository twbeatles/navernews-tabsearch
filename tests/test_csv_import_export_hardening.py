import csv
import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager, DatabaseWriteError
from core.workers import JobCancelledError
from ui.main_window_io_support.exports import (
    _export_row,
    _spreadsheet_safe_csv_cell,
    import_bookmarks_notes_from_csv,
)


class _Context:
    def __init__(self):
        self.reports = []

    def check_cancelled(self):
        return None

    def report(self, **payload):
        self.reports.append(payload)


class _CancellingContext(_Context):
    def __init__(self):
        super().__init__()
        self.latest = {}
        self.checks = 0

    def check_cancelled(self):
        self.checks += 1
        if self.checks > 1:
            raise JobCancelledError("cancelled")

    def remember(self, payload):
        self.latest = dict(payload)


class TestCsvImportExportHardening(unittest.TestCase):
    def test_spreadsheet_formula_prefixes_are_neutralized_after_leading_whitespace(
        self,
    ):
        for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", " \t=HYPERLINK('x')"):
            with self.subTest(value=value):
                self.assertTrue(_spreadsheet_safe_csv_cell(value).startswith("'"))
        self.assertEqual(_spreadsheet_safe_csv_cell("ordinary text"), "ordinary text")

    def test_export_row_sanitizes_every_user_derived_cell(self):
        row = _export_row(
            {
                "title": "=title",
                "link": "+link",
                "pubDate": "-date",
                "publisher": "@publisher",
                "description": "\t=description",
                "notes": "=note",
                "tags": "+tag",
            }
        )
        for index in (0, 1, 2, 3, 4, 7, 9):
            self.assertTrue(row[index].startswith("'"))

    def test_atomic_article_state_import_distinguishes_all_non_error_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.db"))
            try:
                db.upsert_news(
                    [
                        {
                            "title": "one",
                            "link": "https://example.com/1",
                            "pubDate": "",
                            "description": "",
                        }
                    ],
                    "AI",
                    query_key="ai|",
                )
                changed = db.import_article_state(
                    "https://example.com/1", bookmark=1, note="memo"
                )
                unchanged = db.import_article_state(
                    "https://example.com/1", bookmark=1, note="memo"
                )
                missing = db.import_article_state(
                    "https://example.com/missing", bookmark=1, note="memo"
                )
                self.assertEqual(changed["status"], "updated")
                self.assertEqual(unchanged["status"], "unchanged")
                self.assertEqual(missing["status"], "missing")
            finally:
                db.close()

    def test_atomic_article_state_import_rolls_back_bookmark_when_note_update_fails(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.db"))
            try:
                db.upsert_news(
                    [
                        {
                            "title": "one",
                            "link": "https://example.com/1",
                            "pubDate": "",
                            "description": "",
                        }
                    ],
                    "AI",
                    query_key="ai|",
                )
                with db.connection() as conn:
                    conn.execute(
                        "CREATE TRIGGER reject_notes BEFORE UPDATE OF notes ON news "
                        "BEGIN SELECT RAISE(ABORT, 'reject note'); END"
                    )
                    conn.commit()
                with self.assertRaises(DatabaseWriteError):
                    db.import_article_state(
                        "https://example.com/1", bookmark=1, note="memo"
                    )
                row = db.fetch_news("AI", query_key="ai|")[0]
                self.assertEqual(int(row["is_bookmarked"]), 0)
                self.assertEqual(str(row["notes"] or ""), "")
            finally:
                db.close()

    def test_csv_import_returns_exact_structured_totals_and_progress_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = DatabaseManager(str(root / "news.db"))
            try:
                db.upsert_news(
                    [
                        {
                            "title": "one",
                            "link": "https://example.com/1",
                            "pubDate": "",
                            "description": "",
                        }
                    ],
                    "AI",
                    query_key="ai|",
                )
                path = root / "state.csv"
                with path.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["링크", "북마크", "메모"])
                    writer.writerow(["https://example.com/1", "북마크", "memo"])
                    writer.writerow(["https://example.com/1", "북마크", "memo"])
                    writer.writerow(["https://example.com/missing", "북마크", "memo"])
                context = _Context()
                result = import_bookmarks_notes_from_csv(
                    context, db, str(path), chunk_size=1
                )
                self.assertEqual(result["processed"], 3)
                self.assertEqual(result["updated"], 1)
                self.assertEqual(result["unchanged"], 1)
                self.assertEqual(result["missing"], 1)
                self.assertEqual(result["failed"], 0)
                self.assertEqual(result["last_row"], 4)
                self.assertEqual(
                    result["processed"],
                    result["updated"]
                    + result["unchanged"]
                    + result["missing"]
                    + result["failed"],
                )
                self.assertEqual(context.reports[-1]["payload"]["unchanged"], 1)
            finally:
                db.close()

    def test_csv_cancellation_retains_last_committed_row_result(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = DatabaseManager(str(root / "news.db"))
            try:
                db.upsert_news(
                    [
                        {
                            "title": "one",
                            "link": "https://example.com/1",
                            "pubDate": "",
                            "description": "",
                        }
                    ],
                    "AI",
                    query_key="ai|",
                )
                path = root / "state.csv"
                with path.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["링크", "북마크"])
                    writer.writerow(["https://example.com/1", "북마크"])
                    writer.writerow(["https://example.com/1", ""])
                context = _CancellingContext()
                with self.assertRaises(JobCancelledError):
                    import_bookmarks_notes_from_csv(
                        context, db, str(path), chunk_size=500
                    )
                self.assertEqual(context.latest["processed"], 1)
                self.assertEqual(context.latest["updated"], 1)
                self.assertEqual(context.latest["last_row"], 2)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
