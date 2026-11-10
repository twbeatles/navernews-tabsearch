from __future__ import annotations

import json


from core.workers import DBQueryScope
from ui.main_window_io_support.exports import export_items_to_json, export_scope_to_json


class FakeExportDB:
    def __init__(self, items):
        self.items = list(items)

    def count_news(self, **_kwargs):
        return len(self.items)

    def fetch_news(self, limit=50, offset=0, **_kwargs):
        return list(self.items[offset : offset + limit])

    def iter_news_snapshot_batches(self, _scope, chunk_size=200):
        total = len(self.items)

        def _iter():
            for offset in range(0, total, chunk_size):
                yield list(self.items[offset : offset + chunk_size])

        return total, _iter()


class ImmediateExportContext:
    def __init__(self):
        self.reports = []

    def report(self, **kwargs):
        self.reports.append(kwargs)

    def check_cancelled(self):
        pass


def test_export_items_to_json(tmp_path):
    output_file = str(tmp_path / "news_export.json")
    items = [
        {
            "title": "테스트 기사 1",
            "link": "https://example.com/1",
            "pubDate": "2026-08-14 10:00",
            "publisher": "연합뉴스",
            "description": "본문 요약 1",
            "is_read": 1,
            "is_bookmarked": 0,
            "notes": "메모 1",
            "tags": "IT, AI",
        },
        {
            "title": "테스트 기사 2",
            "link": "https://example.com/2",
            "pubDate": "2026-08-14 11:00",
            "publisher": "조선일보",
            "description": "본문 요약 2",
            "is_read": 0,
            "is_bookmarked": 1,
            "notes": "",
            "tags": "",
        },
    ]

    result = export_items_to_json(items, output_file, "테스트")
    assert result["count"] == 2
    assert result["format"] == "json"

    with open(output_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["keyword"] == "테스트"
    assert loaded["count"] == 2
    assert len(loaded["items"]) == 2
    assert loaded["items"][0]["title"] == "테스트 기사 1"


def test_export_scope_to_json(tmp_path):
    output_file = str(tmp_path / "scope_export.json")
    context = ImmediateExportContext()
    sample_items = [
        {"title": "스쿱 기사 1", "link": "https://example.com/s1"},
        {"title": "스쿱 기사 2", "link": "https://example.com/s2"},
    ]
    db = FakeExportDB(sample_items)
    scope = DBQueryScope(keyword="스쿱")

    result = export_scope_to_json(context, db, scope, output_file, "스쿱")

    assert result["count"] == 2
    assert result["format"] == "json"

    with open(output_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    assert loaded["count"] == 2
    assert loaded["keyword"] == "스쿱"
    assert len(loaded["items"]) == 2
    assert len(context.reports) >= 1
