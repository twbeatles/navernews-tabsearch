import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.database import DatabaseManager


def article(link, title):
    return {"link": link, "title": title, "description": "d", "publisher": "p",
            "pubDate": "Thu, 22 Oct 2026 10:00:00 +0900"}


class TestSharedTitleUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.tmp.name) / "news.db"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_title_change_repairs_all_memberships_without_full_recalculation(self):
        for joining in (False, True):
            for new_title, expected in (("different", 2), ("same", 0)):
                with self.subTest(joining=joining, new_title=new_title):
                    self.db.upsert_news([article("L1", "same"), article("L2", "same")], "A")
                    if not joining:
                        self.db.upsert_news([article("L1", "same")], "B")
                    self.db.upsert_news([article("L3", "unrelated")], "C")
                    with mock.patch.object(self.db, "_recalculate_duplicate_flags_for_entire_database",
                                           side_effect=AssertionError("scope only")):
                        self.db.upsert_news([article("L1", new_title)], "B")
                    rows = self.db.fetch_news("A", hide_duplicates=True)
                    self.assertEqual(len(rows), expected)
                    self.assertEqual(self.db.count_news("A", hide_duplicates=True), expected)
                    self.assertEqual(len(self.db.fetch_news("C", hide_duplicates=True)), 1)
                    # Reset B membership so the next scenario also tests first membership.
                    with self.db.connection() as conn:
                        with conn:
                            conn.execute("DELETE FROM news_keywords WHERE keyword='B'")

    def test_different_titles_becoming_equal_are_hidden_in_other_scope(self):
        self.db.upsert_news([article("L1", "one"), article("L2", "two")], "A")
        self.db.upsert_news([article("L1", "two")], "B")
        self.assertEqual(self.db.fetch_news("A", hide_duplicates=True), [])

    def test_failed_recalculation_rolls_back_title_and_flags(self):
        self.db.upsert_news([article("L1", "same"), article("L2", "same")], "A")
        with mock.patch.object(self.db, "_recalculate_duplicate_flags_for_query_key_hashes",
                               side_effect=RuntimeError("injected")):
            with self.assertRaises(Exception):
                self.db.upsert_news([article("L1", "new")], "B")
        self.assertEqual({row["title"] for row in self.db.fetch_news("A")}, {"same"})
        self.assertEqual(self.db.fetch_news("B"), [])
