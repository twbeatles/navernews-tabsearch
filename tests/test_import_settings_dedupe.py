import inspect
import re
import unittest

from ui.main_window import MainApp


def _norm(text):
    # Format-tolerant source matching: ruff format may reflow code
    # lines and add/remove grouping parentheses. Compare the token
    # stream, ignoring grouping brackets.
    toks = re.findall(r"\w+|[^\w\s]", text)
    return " ".join(t for t in toks if t not in "()[]{}")


class TestImportSettingsDedupe(unittest.TestCase):
    def test_import_dedupes_tabs_by_canonical_fetch_key(self):
        block = inspect.getsource(MainApp._compute_imported_new_tabs)

        self.assertIn("existing_fetch_keys = {", block)
        self.assertIn("self._canonical_fetch_key_for_keyword(tab.keyword)", block)
        self.assertIn("existing_fetch_keys.add(normalized_fetch_key)", block)
        self.assertIn(
            _norm(
                "if normalized_keyword and normalized_fetch_key and normalized_fetch_key not in existing_fetch_keys"
            ),
            _norm(block),
        )

    def test_import_normalizes_settings_and_merges_groups(self):
        block = inspect.getsource(MainApp._stage_settings_import)
        merge_block = inspect.getsource(MainApp._merge_imported_keyword_groups)

        self.assertIn("normalize_import_settings(", block)
        self.assertIn("self._merge_search_history(", block)
        self.assertIn("self._merge_int_mapping_keep_max(", block)
        self.assertIn("merge_keyword_groups(", merge_block)

    def test_search_history_merge_uses_canonical_identity(self):
        block = inspect.getsource(MainApp._merge_search_history)

        self.assertIn("seen_identities = set()", block)
        self.assertIn("identity = self._history_identity_for_keyword(keyword)", block)
        self.assertIn("if identity in seen_identities:", block)
