import inspect
import tempfile
import unittest
from pathlib import Path

from core.config_store import default_config, load_config_file, save_config_file_atomic
from ui.main_window import MainApp


class TestPaginationStatePersistence(unittest.TestCase):
    def test_pagination_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            payload = default_config()
            payload["pagination_state"] = {
                "ai|coin": 301,
                "economy|ad": 901,
            }
            payload["pagination_totals"] = {
                "ai|coin": 542,
                "economy|ad": 0,
            }
            save_config_file_atomic(str(cfg_path), payload)

            loaded = load_config_file(str(cfg_path))
            self.assertEqual(loaded["pagination_state"]["ai|coin"], 301)
            self.assertEqual(loaded["pagination_state"]["economy|ad"], 901)
            self.assertEqual(loaded["pagination_totals"]["ai|coin"], 542)
            self.assertEqual(loaded["pagination_totals"]["economy|ad"], 0)

    def test_fetch_more_uses_cursor_or_default_without_db_count_fallback(self):
        block = inspect.getsource(MainApp.fetch_news)

        self.assertIn("self._fetch_cursor_by_key.get(fetch_key, 0)", block)
        self.assertIn("start_idx = 101", block)
        self.assertNotIn("self.db.get_counts(", block)

    def test_main_window_persists_pagination_state_field(self):
        load_src = inspect.getsource(MainApp.load_config)
        save_src = inspect.getsource(MainApp.save_config)
        self.assertIn('"pagination_state": loaded_cfg.get("pagination_state", {})', load_src)
        self.assertIn('"pagination_totals": loaded_cfg.get("pagination_totals", {})', load_src)
        self.assertIn('"pagination_state": {', save_src)
        self.assertIn('"pagination_totals": {', save_src)
