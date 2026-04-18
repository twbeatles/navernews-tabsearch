import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional, cast
from unittest import mock

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
    def __init__(self, config_file: str):
        self.groups = {}
        self.config_file = config_file
        self.last_error = ""


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

    def _config_path_for_persistence(self):
        return cast(Any, _MainWindowSettingsIOMixin)._config_path_for_persistence(cast(Any, self))

    def _build_runtime_config_payload(self, **kwargs):
        return cast(Any, _MainWindowSettingsIOMixin)._build_runtime_config_payload(
            cast(Any, self),
            **kwargs,
        )

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

    def _compute_imported_new_tabs(self, imported_tabs):
        return cast(Any, _MainWindowSettingsIOMixin)._compute_imported_new_tabs(
            cast(Any, self),
            imported_tabs,
        )

    def _merge_imported_keyword_groups(self, imported_groups):
        return cast(Any, _MainWindowSettingsIOMixin)._merge_imported_keyword_groups(
            cast(Any, self),
            imported_groups,
        )

    def _snapshot_runtime_state_for_import(self):
        return cast(Any, _MainWindowSettingsIOMixin)._snapshot_runtime_state_for_import(cast(Any, self))

    def _remove_imported_tab_for_rollback(self, keyword):
        return cast(Any, _MainWindowSettingsIOMixin)._remove_imported_tab_for_rollback(
            cast(Any, self),
            keyword,
        )

    def _rollback_import_runtime_state(self, runtime_snapshot, added_keywords):
        return cast(Any, _MainWindowSettingsIOMixin)._rollback_import_runtime_state(
            cast(Any, self),
            runtime_snapshot,
            added_keywords,
        )

    def _apply_import_runtime_stage(self, stage):
        return cast(Any, _MainWindowSettingsIOMixin)._apply_import_runtime_stage(cast(Any, self), stage)

    def _stage_settings_import(self, import_data):
        return cast(Any, _MainWindowSettingsIOMixin)._stage_settings_import(cast(Any, self), import_data)

    def _normalize_tab_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._normalize_tab_keyword(cast(Any, self), raw_keyword)

    def _canonical_fetch_key_for_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._canonical_fetch_key_for_keyword(cast(Any, self), raw_keyword)

    def _history_identity_for_keyword(self, raw_keyword):
        return cast(Any, _MainWindowTabsMixin)._history_identity_for_keyword(cast(Any, self), raw_keyword)

    def __init__(self, dialog_adapter):
        self._tempdir = tempfile.TemporaryDirectory()
        self._dialog_adapter = dialog_adapter
        self.client_id = ""
        self.client_secret = ""
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
        self._tab_fetch_state = {}
        self._saved_geometry = None
        self.tray = object()
        self.keyword_group_manager = _FakeKeywordGroupManager(
            str(Path(self._tempdir.name) / "config.json")
        )
        self._tabs = [_FakeTab("북마크")]
        self.refresh_requests = []
        self.toast_messages = []
        self.warning_toasts = []
        self.apply_refresh_calls = 0
        self.fail_on_add_keyword: Optional[str] = None
        self.reconcile_auto_start_result: Optional[bool] = None

    def __del__(self):
        try:
            self._tempdir.cleanup()
        except Exception:
            pass

    def _iter_news_tabs(self, start_index=0):
        for index, tab in enumerate(self._tabs[start_index:], start_index):
            yield index, tab

    def _find_news_tab(self, keyword):
        for index, tab in enumerate(self._tabs[1:], 1):
            if tab.keyword == keyword:
                return index, tab
        return None

    def add_news_tab(self, keyword):
        if self.fail_on_add_keyword and keyword == self.fail_on_add_keyword:
            raise RuntimeError("tab add failure")
        self._tabs.append(_FakeTab(keyword))

    def _normalize_window_geometry(self, raw_geometry):
        return raw_geometry

    def _reconcile_startup_state_from_import(self, normalized_settings, import_warnings):
        if self.reconcile_auto_start_result is not None:
            normalized_settings["auto_start_enabled"] = bool(self.reconcile_auto_start_result)
        return None

    def setStyleSheet(self, _style):
        return None

    def setGeometry(self, *_args):
        return None

    def apply_refresh_interval(self):
        self.apply_refresh_calls += 1

    def show_toast(self, message):
        self.toast_messages.append(str(message))

    def show_warning_toast(self, message):
        self.warning_toasts.append(str(message))

    def refresh_selected_tabs(self, keywords):
        self.refresh_requests.append(list(keywords))
        return True

    def x(self):
        return 100

    def y(self):
        return 120

    def width(self):
        return 1100

    def height(self):
        return 850


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
        config_payload = json.loads(Path(dummy.keyword_group_manager.config_file).read_text(encoding="utf-8"))
        self.assertEqual(config_payload["tabs"], ["AI", "경제"])

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
        config_payload = json.loads(Path(dummy.keyword_group_manager.config_file).read_text(encoding="utf-8"))
        self.assertEqual(config_payload["tabs"], ["AI", "경제"])

    def test_import_settings_rolls_back_runtime_and_config_when_add_tab_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import_file = self._write_import_file(
                root,
                {
                    "settings": {"theme_index": 1},
                    "tabs": ["AI", "경제"],
                    "keyword_groups": {"기본": ["AI"]},
                },
            )
            dialogs = _FakeDialogAdapter(open_result=(str(import_file), "JSON"))
            dummy = _DummyImportMain(dialogs)
            dummy.fail_on_add_keyword = "경제"

            dummy.import_settings()

        self.assertEqual(len(dialogs.warning_calls), 1)
        self.assertEqual(dummy.theme_idx, 0)
        self.assertEqual([tab.keyword for tab in dummy._tabs[1:]], [])
        self.assertEqual(dummy.keyword_group_manager.groups, {})
        config_payload = json.loads(Path(dummy.keyword_group_manager.config_file).read_text(encoding="utf-8"))
        self.assertEqual(config_payload["tabs"], [])
        self.assertEqual(config_payload["app_settings"]["theme_index"], 0)

    def test_import_settings_does_not_apply_runtime_when_config_persist_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import_file = self._write_import_file(
                root,
                {
                    "settings": {"theme_index": 1},
                    "tabs": ["AI"],
                    "keyword_groups": {"기본": ["AI"]},
                },
            )
            dialogs = _FakeDialogAdapter(open_result=(str(import_file), "JSON"))
            dummy = _DummyImportMain(dialogs)

            with mock.patch(
                "ui._main_window_settings_io.save_primary_config_file",
                side_effect=OSError("disk full"),
            ):
                dummy.import_settings()

        self.assertEqual(len(dialogs.warning_calls), 1)
        self.assertEqual(dummy.theme_idx, 0)
        self.assertEqual(dummy.apply_refresh_calls, 0)
        self.assertEqual([tab.keyword for tab in dummy._tabs[1:]], [])

    def test_import_settings_rewrites_config_after_startup_reconcile_changes_auto_start(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import_file = self._write_import_file(
                root,
                {
                    "settings": {"auto_start_enabled": True},
                    "tabs": [],
                    "keyword_groups": {},
                },
            )
            dialogs = _FakeDialogAdapter(open_result=(str(import_file), "JSON"))
            dummy = _DummyImportMain(dialogs)
            dummy.reconcile_auto_start_result = False

            dummy.import_settings()

        self.assertFalse(dummy.auto_start_enabled)
        config_payload = json.loads(Path(dummy.keyword_group_manager.config_file).read_text(encoding="utf-8"))
        self.assertFalse(config_payload["app_settings"]["auto_start_enabled"])


if __name__ == "__main__":
    unittest.main()
