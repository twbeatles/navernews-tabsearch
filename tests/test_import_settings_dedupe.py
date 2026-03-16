import inspect
import unittest

from ui.main_window import MainApp


class TestImportSettingsDedupe(unittest.TestCase):
    def test_import_dedupes_tabs_by_canonical_fetch_key(self):
        block = inspect.getsource(MainApp.import_settings)

        self.assertIn("existing_fetch_keys = {", block)
        self.assertIn("self._canonical_fetch_key_for_keyword(tab.keyword)", block)
        self.assertIn("existing_fetch_keys.add(normalized_fetch_key)", block)
        self.assertIn("if normalized_keyword and normalized_fetch_key and normalized_fetch_key not in existing_fetch_keys", block)

    def test_import_normalizes_settings_and_merges_groups(self):
        block = inspect.getsource(MainApp.import_settings)

        self.assertIn("normalize_import_settings(", block)
        self.assertIn("self.keyword_group_manager.merge_groups(imported_groups, save=True)", block)
        self.assertIn("self._merge_search_history(", block)
        self.assertIn("self._merge_int_mapping_keep_max(", block)

    def test_search_history_merge_uses_canonical_identity(self):
        block = inspect.getsource(MainApp._merge_search_history)

        self.assertIn("seen_identities = set()", block)
        self.assertIn("identity = self._history_identity_for_keyword(keyword)", block)
        self.assertIn("if identity in seen_identities:", block)

