import inspect
import unittest

from ui.main_window import MainApp


class TestImportSettingsDedupe(unittest.TestCase):
    def test_import_uses_set_and_updates_seen_keywords(self):
        block = inspect.getsource(MainApp.import_settings)

        self.assertIn("existing_keywords = {", block)
        self.assertIn("existing_keywords.add(normalized_keyword)", block)
        self.assertIn("if normalized_keyword and normalized_keyword not in existing_keywords", block)

    def test_import_normalizes_settings_and_merges_groups(self):
        block = inspect.getsource(MainApp.import_settings)

        self.assertIn("normalize_import_settings(", block)
        self.assertIn("self.keyword_group_manager.merge_groups(imported_groups, save=True)", block)
        self.assertIn("self._merge_search_history(", block)
        self.assertIn("self._merge_int_mapping_keep_max(", block)

