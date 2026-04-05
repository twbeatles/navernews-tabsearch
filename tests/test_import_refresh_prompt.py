import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from ui._main_window_settings_io import _MainWindowSettingsIOMixin
from ui._main_window_tabs import _MainWindowTabsMixin


class _FakeDialogAdapter:
    def __init__(self, *, open_result=("", ""), ask_yes_no_result=False):
        self.open_result = open_result
        self.ask_yes_no_result = ask_yes_no_result
        self.open_calls = []
        self.question_calls = []
        self.warning_calls = []

    def get_open_file_name(self, parent, title, directory, filters):
        self.open_calls.append((parent, title, directory, filters))
        return self.open_result

    def ask_yes_no(self, parent, title, message, default=None):
        self.question_calls.append((parent, title, message, default))
        return self.ask_yes_no_result

    def warning(self, parent, title, message):
        self.warning_calls.append((parent, title, message))

    def information(self, parent, title, message):
        return None

    def get_save_file_name(self, parent, title, default_name, filters):
        return "", ""

    def critical(self, parent, title, message):
        return None

    def ask_corrupt_backup_action(self, parent, backup_name, corrupt_error):
        return "ignore"


class _FakeKeywordGroupManager:
    def __init__(self):
        self.groups = {}
        self.merge_calls = []

    def merge_groups(self, incoming_groups, save=True):
        self.merge_calls.append((dict(incoming_groups), bool(save)))
        self.groups.update(incoming_groups)
        return self.groups


class _FakeTab:
    def __init__(self, keyword):
        self.keyword = keyword
        self.theme = 0
        self.render_calls = 0

    def render_html(self):
        self.render_calls += 1


class _DummyImportMain:
    def import_settings(self):
        return cast(Any, _MainWindowSettingsIOMixin).import_settings(cast(Any, self))

    def _merge_search_history(self, imported_history):
        return cast(Any, _MainWindowSettingsIOMixin)._merge_search_history(cast(Any, self), imported_history)

    def _merge_int_mapping_keep_max(self, current, incoming, minimum):
        return cast(Any, _MainWindowSettingsIOMixin)._merge_int_mapping_keep_max(
            cast(Any, self),
            current,
            incoming,
            minimum,
        )

    def _validated_import_window_geometry(self, raw_geometry):
        return cast(Any, _MainWindowSettingsIOMixin)._validated_import_window_geometry(
            cast(Any, self),
            raw_geometry,
        )

    def _prompt_refresh_imported_tabs(self, imported_keywords):
        return cast(Any, _MainWindowSettingsIOMixin)._prompt_refresh_imported_tabs(
            cast(Any, self),
            imported_keywords,
        )

    def _normalize_tab_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._normalize_tab_keyword(cast(Any, self), raw_keyword)

    def _canonical_fetch_key_for_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._canonical_fetch_key_for_keyword(cast(Any, self), raw_keyword)

    def _history_identity_for_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._history_identity_for_keyword(cast(Any, self), raw_keyword)

    def __init__(self, dialog_adapter):
        self._dialog_adapter = dialog_adapter
        self.theme_idx = 0
        self.interval_idx = 2
        self.notification_enabled = True
        self.alert_keywords = []
        self.sound_enabled = True
        self.minimize_to_tray = True
        self.close_to_tray = True
        self.start_minimized = False
        self.auto_start_enabled = False
        self.notify_on_refresh = False
        self.api_timeout = 15
        self.search_history = []
        self._fetch_cursor_by_key = {}
        self._fetch_total_by_key = {}
        self._saved_geometry = None
        self.tray = object()
        self.keyword_group_manager = _FakeKeywordGroupManager()
        self._tabs = [_FakeTab("북마크")]
        self.refresh_requests = []
        self.toast_messages = []
        self.warning_toasts = []
        self.apply_refresh_calls = 0
        self.save_config_calls = 0

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._tabs[start_index:], start_index):
            yield index, tab

    def add_news_tab(self, keyword):
        self._tabs.append(_FakeTab(keyword))

    def _normalize_window_geometry(self, raw_geometry):
        return raw_geometry

    def _reconcile_startup_state_from_import(self, normalized_settings, import_warnings):
        return None

    def setStyleSheet(self, _style):
        return None

    def setGeometry(self, *_args):
        return None

    def apply_refresh_interval(self):
        self.apply_refresh_calls += 1

    def save_config(self):
        self.save_config_calls += 1

    def show_toast(self, message):
        self.toast_messages.append(str(message))

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def refresh_selected_tabs(self, keywords):
        self.refresh_requests.append(list(keywords))
        return True


class TestImportRefreshPrompt(unittest.TestCase):
    def _write_import_file(self, root: Path, payload: dict) -> Path:
        path = root / "import.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_import_settings_refreshes_new_tabs_when_user_accepts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import_file = self._write_import_file(
                root,
                {
                    "settings": {},
                    "tabs": ["AI", "경제"],
                    "keyword_groups": {},
                },
            )
            dialogs = _FakeDialogAdapter(
                open_result=(str(import_file), "JSON"),
                ask_yes_no_result=True,
            )
            dummy = _DummyImportMain(dialogs)

            dummy.import_settings()

        self.assertEqual(dummy.refresh_requests, [["AI", "경제"]])
        self.assertEqual(len(dialogs.question_calls), 1)
        self.assertEqual(dummy.apply_refresh_calls, 1)
        self.assertEqual(dummy.save_config_calls, 1)

    def test_import_settings_skips_refresh_when_user_declines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import_file = self._write_import_file(
                root,
                {
                    "settings": {},
                    "tabs": ["AI", "경제"],
                    "keyword_groups": {},
                },
            )
            dialogs = _FakeDialogAdapter(
                open_result=(str(import_file), "JSON"),
                ask_yes_no_result=False,
            )
            dummy = _DummyImportMain(dialogs)

            dummy.import_settings()

        self.assertEqual(dummy.refresh_requests, [])
        self.assertEqual(len(dialogs.question_calls), 1)
        self.assertEqual(dummy.apply_refresh_calls, 1)
        self.assertEqual(dummy.save_config_calls, 1)


if __name__ == "__main__":
    unittest.main()
