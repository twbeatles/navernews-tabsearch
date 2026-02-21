import json
import tempfile
import unittest
from pathlib import Path

from core.config_store import default_config, load_config_file, save_config_file_atomic
from core.keyword_groups import KeywordGroupManager


class TestKeywordGroupStorage(unittest.TestCase):
    def test_groups_are_saved_inside_config_file(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            save_config_file_atomic(str(cfg), default_config())

            mgr = KeywordGroupManager(config_file=str(cfg), legacy_file=str(Path(td) / "legacy_groups.json"))
            self.assertTrue(mgr.create_group("시장"))
            self.assertTrue(mgr.add_keyword_to_group("시장", "AI"))

            loaded = load_config_file(str(cfg))
            self.assertEqual(loaded["keyword_groups"].get("시장"), ["AI"])

    def test_legacy_group_file_migrates_to_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            legacy = Path(td) / "keyword_groups.json"
            save_config_file_atomic(str(cfg), default_config())
            legacy.write_text(
                json.dumps({"legacy_group": ["경제", "증시"]}, ensure_ascii=False),
                encoding="utf-8",
            )

            mgr = KeywordGroupManager(config_file=str(cfg), legacy_file=str(legacy))
            self.assertEqual(mgr.groups.get("legacy_group"), ["경제", "증시"])

            loaded = load_config_file(str(cfg))
            self.assertEqual(loaded["keyword_groups"].get("legacy_group"), ["경제", "증시"])

    def test_merge_groups_preserves_existing_order_and_appends_new(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            save_config_file_atomic(str(cfg), default_config())

            mgr = KeywordGroupManager(config_file=str(cfg), legacy_file=str(Path(td) / "legacy_groups.json"))
            mgr.groups = {"시장": ["AI", "경제"], "기술": ["클라우드"]}
            mgr.save_groups()

            merged = mgr.merge_groups(
                {
                    "시장": ["경제", "증시", "AI"],
                    "신규": ["반도체", "AI"],
                },
                save=True,
            )

            self.assertEqual(merged["시장"], ["AI", "경제", "증시"])
            self.assertEqual(merged["기술"], ["클라우드"])
            self.assertEqual(merged["신규"], ["반도체", "AI"])

            loaded = load_config_file(str(cfg))
            self.assertEqual(loaded["keyword_groups"]["시장"], ["AI", "경제", "증시"])

