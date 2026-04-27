import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import core.backup as backup_module
from core.backup import apply_pending_restore_if_any
from core.config_store import default_config, load_config_file, save_config_file_atomic
from core.database import DatabaseManager
from core.workers import ApiWorker, DBQueryScope, JobCancelledError
from ui._main_window_settings_io import export_scope_to_csv
from ui.news_tab import NewsTab


def _item(index: int, publisher: str) -> dict:
    return {
        "title": f"title {index}",
        "description": f"description {index}",
        "link": f"https://example.com/{index}",
        "originallink": f"https://origin.example.com/{index}",
        "pubDate": "2026-04-27T10:00:00",
        "publisher": publisher,
    }


class TestImplementationBatchDbFeatures(unittest.TestCase):
    def test_update_missing_link_returns_false_and_tags_filter_visibility(self):
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(str(Path(td) / "news.sqlite"), max_connections=2)
            try:
                db.upsert_news([_item(1, "alpha.com"), _item(2, "beta.com")], "AI")
                self.assertFalse(db.update_status("https://example.com/missing", "is_read", 1))
                self.assertTrue(db.set_tags("https://example.com/1", ["Important", "AI", "ai"]))

                all_rows = db.fetch_news("AI")
                self.assertEqual(len(all_rows), 2)
                self.assertEqual(
                    [row["link"] for row in db.fetch_news("AI", blocked_publishers=["beta.com"])],
                    ["https://example.com/1"],
                )
                self.assertEqual(
                    [row["link"] for row in db.fetch_news("AI", preferred_publishers=["beta.com"], only_preferred_publishers=True)],
                    ["https://example.com/2"],
                )
                tagged_rows = db.fetch_news("AI", tag_filter="important")
                self.assertEqual([row["link"] for row in tagged_rows], ["https://example.com/1"])
                self.assertIn("Important", tagged_rows[0]["tags"])

                self.assertTrue(db.delete_link("https://example.com/1"))
                self.assertEqual(db.get_tags("https://example.com/1"), [])
            finally:
                db.close()

    def test_config_roundtrip_includes_new_schema_fields(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            payload = default_config()
            payload["app_settings"]["blocked_publishers"] = ["Alpha.com", "alpha.com"]
            payload["app_settings"]["preferred_publishers"] = ["Beta.com"]
            payload["saved_searches"] = {"AI": {"keyword": "AI", "tag_filter": "Important"}}
            payload["tab_refresh_policies"] = {"AI": "30", "경제": "off"}
            save_config_file_atomic(str(cfg_path), payload)

            loaded = load_config_file(str(cfg_path))

        self.assertEqual(loaded["app_settings"]["blocked_publishers"], ["Alpha.com"])
        self.assertEqual(loaded["app_settings"]["preferred_publishers"], ["Beta.com"])
        self.assertEqual(loaded["saved_searches"]["AI"]["tag_filter"], "Important")
        self.assertEqual(loaded["tab_refresh_policies"], {"AI": "30", "경제": "off"})


class _DummyActionTab:
    _open_article_url = NewsTab._open_article_url
    _render_single_item = NewsTab._render_single_item
    _item_render_cache_key = NewsTab._item_render_cache_key

    def __init__(self):
        self.failures = []
        self.theme = 0
        self.keyword = "AI"
        self.is_bookmark_tab = False
        self._item_html_cache = {}

    def _emit_local_action_failure(self, message):
        self.failures.append(message)


class TestImplementationBatchUiSafety(unittest.TestCase):
    def test_article_open_allows_only_http_schemes(self):
        tab = _DummyActionTab()
        with mock.patch("ui.news_tab.QDesktopServices.openUrl", return_value=True) as open_url:
            self.assertFalse(
                NewsTab._open_article_url(
                    cast(Any, tab),
                    "file:///C:/secret.txt",
                    failure_message="blocked",
                )
            )
            self.assertTrue(
                NewsTab._open_article_url(
                    cast(Any, tab),
                    "https://example.com/news",
                    failure_message="blocked",
                )
            )

        self.assertEqual(open_url.call_count, 1)
        self.assertEqual(open_url.call_args.args[0].scheme(), "https")
        self.assertEqual(tab.failures, ["blocked"])

    def test_render_escapes_publisher_date_and_tags(self):
        tab = _DummyActionTab()
        html = NewsTab._render_single_item(
            cast(Any, tab),
            {
                "link": "https://example.com/1",
                "title": "plain",
                "description": "desc",
                "publisher": "<b>bad</b>",
                "pubDate": "<i>date</i>",
                "tags": "<tag>, ok",
            },
            "",
            "",
        )

        self.assertNotIn("<b>bad</b>", html)
        self.assertNotIn("<i>date</i>", html)
        self.assertNotIn("<tag>", html)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", html)
        self.assertIn("#ok", html)


class _FakeResponse:
    def __init__(self, status_code: int, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return {"errorMessage": "limited", "errorCode": "E429"}


class _FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, *_args, **_kwargs):
        return self.response


class _FakeDb:
    def upsert_news(self, *_args, **_kwargs):
        return 0, 0


class TestImplementationBatchStability(unittest.TestCase):
    def test_large_retry_after_uses_cooldown_without_inline_sleep(self):
        worker = ApiWorker(
            "id",
            "secret",
            "AI",
            "AI",
            [],
            _FakeDb(),
            session=_FakeSession(_FakeResponse(429, headers={"Retry-After": "45"})),
        )
        worker.max_retries = 2
        errors = []
        worker.error.connect(lambda msg: errors.append(msg))

        with mock.patch("core.workers.time.sleep") as sleep_mock:
            worker.run()

        self.assertEqual(sleep_mock.call_count, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.last_error_meta["kind"], "rate_limit")
        self.assertEqual(worker.last_error_meta["cooldown_seconds"], 45)

    def test_pending_restore_rename_prevents_repeat_when_delete_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pending = root / "pending_restore.json"
            backup_dir = root / "backups"
            backup_name = "backup_1"
            (backup_dir / backup_name).mkdir(parents=True)
            pending.write_text(
                json.dumps({"backup_name": backup_name, "backup_dir": str(backup_dir), "restore_db": True}),
                encoding="utf-8",
            )

            with mock.patch.object(backup_module, "_apply_restore_from_backup", return_value=True):
                with mock.patch("core.backup.os.remove", side_effect=OSError("locked")):
                    ok = apply_pending_restore_if_any(
                        pending_file=str(pending),
                        config_file=str(root / "config.json"),
                        db_file=str(root / "news.sqlite"),
                    )

            self.assertTrue(ok)
            self.assertFalse(pending.exists())
            self.assertTrue(Path(f"{pending}.applied").exists())

    def test_export_closes_snapshot_iterator_when_cancelled_before_iteration(self):
        class _Context:
            def report(self, **_kwargs):
                pass

            def check_cancelled(self):
                raise JobCancelledError()

        class _Iterator:
            def __init__(self):
                self.closed = False

            def __iter__(self):
                return iter([])

            def close(self):
                self.closed = True

        class _Db:
            def __init__(self):
                self.iterator = _Iterator()

            def iter_news_snapshot_batches(self, *_args, **_kwargs):
                return 1, self.iterator

        db = _Db()
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(JobCancelledError):
                export_scope_to_csv(_Context(), db, DBQueryScope(keyword="AI"), str(Path(td) / "x.csv"), "AI")

        self.assertTrue(db.iterator.closed)


if __name__ == "__main__":
    unittest.main()
