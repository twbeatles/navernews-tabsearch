import unittest

from core.query_parser import parse_search_query, parse_tab_query


class TestQueryParserSearchPolicy(unittest.TestCase):
    def test_parse_search_query_case_table(self):
        cases = [
            ("", ("", [])),
            ("AI", ("AI", [])),
            ("인공지능 AI -광고 -코인", ("인공지능 AI", ["광고", "코인"])),
            ("-광고 AI ML", ("AI ML", ["광고"])),
            ("AI - 광고", ("AI 광고", [])),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_search_query(raw), expected)

    def test_tab_query_keeps_first_positive_keyword_only(self):
        db_keyword, excludes = parse_tab_query("인공지능 AI -광고 -코인")
        self.assertEqual(db_keyword, "인공지능")
        self.assertEqual(excludes, ["광고", "코인"])

