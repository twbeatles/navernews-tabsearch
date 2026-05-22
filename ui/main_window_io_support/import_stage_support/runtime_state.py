# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTimer

from core.config_store import (
    AppConfig,
    encode_client_secret_for_storage,
    normalize_import_settings,
    normalize_loaded_config,
    save_primary_config_file,
)
from core.cloud_sync import (
    cleanup_old_snapshots,
    cloud_sync_path_conflicts_with_runtime,
    create_cloud_snapshot,
    import_cloud_snapshot,
    run_cloud_sync_cycle,
    runtime_storage_is_probably_cloud,
    select_cloud_snapshots_for_import,
)
from core.constants import CONFIG_FILE, RUNTIME_PATHS, VERSION
from core.content_filters import normalize_publisher_filter_lists
from core.keyword_groups import merge_keyword_groups
from core.machine_identity import get_machine_identity
from core.automation_rules import normalize_automation_rules
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases
from core.startup import StartupManager
from core.workers import DBQueryScope, IterativeJobWorker, delete_qthread_when_finished
from ui.dialog_adapters import get_dialog_adapter
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle

if TYPE_CHECKING:
    from ui.main_window import MainApp

logger = logging.getLogger(__name__)
EXPORT_CHUNK_SIZE = 500


class _ImportStageRuntimeStateMixin:
    def _config_path_for_persistence(self: MainApp) -> str:
        group_manager = getattr(self, "keyword_group_manager", None)
        config_path = getattr(group_manager, "config_file", None)
        if isinstance(config_path, str) and config_path.strip():
            return config_path
        runtime_paths = getattr(self, "runtime_paths", None) or RUNTIME_PATHS
        return getattr(runtime_paths, "config_file", CONFIG_FILE)

    def _build_runtime_config_payload(
        self: MainApp,
        *,
        app_settings_overrides: Optional[Dict[str, Any]] = None,
        tab_keywords: Optional[List[str]] = None,
        search_history: Optional[List[str]] = None,
        keyword_groups: Optional[Dict[str, List[str]]] = None,
        pagination_state: Optional[Dict[str, int]] = None,
        pagination_totals: Optional[Dict[str, int]] = None,
        saved_searches: Optional[Dict[str, Dict[str, Any]]] = None,
        tab_refresh_policies: Optional[Dict[str, str]] = None,
        automation_rules: Optional[List[Dict[str, Any]]] = None,
        publisher_aliases: Optional[Dict[str, str]] = None,
        window_geometry: Optional[Dict[str, int]] = None,
    ) -> AppConfig:
        app_settings_overrides = dict(app_settings_overrides or {})
        client_id = str(getattr(self, "client_id", "") or "")
        client_secret = str(getattr(self, "client_secret", "") or "")

        def _safe_int_attr(attr_name: str, fallback: int) -> int:
            value = getattr(self, attr_name, None)
            if callable(value):
                try:
                    return int(value())
                except Exception:
                    return fallback
            try:
                return int(value)
            except Exception:
                return fallback

        geometry = window_geometry or {
            "x": _safe_int_attr("x", 100),
            "y": _safe_int_attr("y", 100),
            "width": _safe_int_attr("width", 1100),
            "height": _safe_int_attr("height", 850),
        }
        secret_payload = encode_client_secret_for_storage(client_secret)
        tabs_payload = (
            list(tab_keywords)
            if tab_keywords is not None
            else [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)]
        )
        history_payload = (
            list(search_history)
            if search_history is not None
            else [str(item) for item in self.search_history if isinstance(item, str)]
        )
        groups_payload = (
            dict(keyword_groups)
            if keyword_groups is not None
            else dict(getattr(self.keyword_group_manager, "groups", {}))
        )
        raw_tab_refresh_policies = dict(
            tab_refresh_policies
            if tab_refresh_policies is not None
            else getattr(self, "tab_refresh_policies", {})
        )
        tab_refresh_policies_payload = self._canonicalize_tab_refresh_policies(
            raw_tab_refresh_policies,
            known_keywords=tabs_payload,
        )
        pagination_state_payload = (
            {
                str(fetch_key): max(1, min(1000, int(start_idx)))
                for fetch_key, start_idx in pagination_state.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
            }
            if pagination_state is not None
            else {
                str(fetch_key): max(1, min(1000, int(start_idx)))
                for fetch_key, start_idx in self._fetch_cursor_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
            }
        )
        pagination_totals_payload = (
            {
                str(fetch_key): int(total)
                for fetch_key, total in pagination_totals.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
            }
            if pagination_totals is not None
            else {
                str(fetch_key): int(total)
                for fetch_key, total in self._fetch_total_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
            }
        )
        blocked_publishers, preferred_publishers = normalize_publisher_filter_lists(
            app_settings_overrides.get("blocked_publishers", getattr(self, "blocked_publishers", [])),
            app_settings_overrides.get("preferred_publishers", getattr(self, "preferred_publishers", [])),
        )
        return {
            "app_settings": {
                "client_id": str(app_settings_overrides.get("client_id", client_id)),
                "client_secret": str(
                    app_settings_overrides.get("client_secret", secret_payload.get("client_secret", ""))
                ),
                "client_secret_enc": str(
                    app_settings_overrides.get("client_secret_enc", secret_payload.get("client_secret_enc", ""))
                ),
                "client_secret_storage": str(
                    app_settings_overrides.get(
                        "client_secret_storage",
                        secret_payload.get("client_secret_storage", "plain"),
                    )
                ),
                "theme_index": int(app_settings_overrides.get("theme_index", self.theme_idx)),
                "refresh_interval_index": int(
                    app_settings_overrides.get("refresh_interval_index", self.interval_idx)
                ),
                "auto_backup_minutes": int(
                    app_settings_overrides.get(
                        "auto_backup_minutes",
                        getattr(self, "auto_backup_minutes", 60),
                    )
                ),
                "notification_enabled": bool(
                    app_settings_overrides.get("notification_enabled", self.notification_enabled)
                ),
                "alert_keywords": list(app_settings_overrides.get("alert_keywords", self.alert_keywords)),
                "sound_enabled": bool(app_settings_overrides.get("sound_enabled", self.sound_enabled)),
                "minimize_to_tray": bool(
                    app_settings_overrides.get("minimize_to_tray", self.minimize_to_tray)
                ),
                "close_to_tray": bool(app_settings_overrides.get("close_to_tray", self.close_to_tray)),
                "start_minimized": bool(
                    app_settings_overrides.get("start_minimized", self.start_minimized)
                ),
                "auto_start_enabled": bool(
                    app_settings_overrides.get("auto_start_enabled", self.auto_start_enabled)
                ),
                "notify_on_refresh": bool(
                    app_settings_overrides.get("notify_on_refresh", self.notify_on_refresh)
                ),
                "api_timeout": int(app_settings_overrides.get("api_timeout", self.api_timeout)),
                "blocked_publishers": blocked_publishers,
                "preferred_publishers": preferred_publishers,
                "cloud_sync_enabled": bool(
                    app_settings_overrides.get(
                        "cloud_sync_enabled",
                        getattr(self, "cloud_sync_enabled", True),
                    )
                ),
                "cloud_sync_dir": str(
                    app_settings_overrides.get(
                        "cloud_sync_dir",
                        getattr(self, "cloud_sync_dir", ""),
                    )
                    or ""
                ),
                "cloud_sync_interval_minutes": int(
                    app_settings_overrides.get(
                        "cloud_sync_interval_minutes",
                        getattr(self, "cloud_sync_interval_minutes", 30),
                    )
                    or 30
                ),
                "window_geometry": {
                    "x": int(geometry["x"]),
                    "y": int(geometry["y"]),
                    "width": int(geometry["width"]),
                    "height": int(geometry["height"]),
                },
            },
            "tabs": tabs_payload,
            "search_history": history_payload,
            "keyword_groups": groups_payload,
            "pagination_state": pagination_state_payload,
            "pagination_totals": pagination_totals_payload,
            "saved_searches": dict(
                saved_searches if saved_searches is not None else getattr(self, "saved_searches", {})
            ),
            "tab_refresh_policies": tab_refresh_policies_payload,
            "automation_rules": normalize_automation_rules(
                automation_rules if automation_rules is not None else getattr(self, "automation_rules", [])
            ),
            "publisher_aliases": normalize_publisher_aliases(
                publisher_aliases if publisher_aliases is not None else getattr(self, "publisher_aliases", {})
            ),
        }

    def _snapshot_runtime_state_for_import(self: MainApp) -> Dict[str, Any]:
        config_payload = self._build_runtime_config_payload()
        return {
            "theme_idx": self.theme_idx,
            "interval_idx": self.interval_idx,
            "notification_enabled": self.notification_enabled,
            "alert_keywords": list(self.alert_keywords),
            "sound_enabled": self.sound_enabled,
            "minimize_to_tray": self.minimize_to_tray,
            "close_to_tray": self.close_to_tray,
            "start_minimized": self.start_minimized,
            "auto_start_enabled": self.auto_start_enabled,
            "notify_on_refresh": self.notify_on_refresh,
            "auto_backup_minutes": getattr(self, "auto_backup_minutes", 60),
            "api_timeout": self.api_timeout,
            "blocked_publishers": list(getattr(self, "blocked_publishers", [])),
            "preferred_publishers": list(getattr(self, "preferred_publishers", [])),
            "cloud_sync_enabled": bool(getattr(self, "cloud_sync_enabled", True)),
            "cloud_sync_dir": str(getattr(self, "cloud_sync_dir", "") or ""),
            "cloud_sync_interval_minutes": int(getattr(self, "cloud_sync_interval_minutes", 30) or 30),
            "saved_searches": dict(getattr(self, "saved_searches", {})),
            "tab_refresh_policies": dict(getattr(self, "tab_refresh_policies", {})),
            "automation_rules": list(getattr(self, "automation_rules", [])),
            "publisher_aliases": dict(getattr(self, "publisher_aliases", {})),
            "search_history": list(self.search_history),
            "fetch_cursor_by_key": dict(self._fetch_cursor_by_key),
            "fetch_total_by_key": dict(self._fetch_total_by_key),
            "saved_geometry": self._saved_geometry,
            "window_geometry": dict(config_payload["app_settings"]["window_geometry"]),
            "keyword_groups": dict(getattr(self.keyword_group_manager, "groups", {})),
            "config_payload": config_payload,
        }

    def _remove_imported_tab_for_rollback(self: MainApp, keyword: str) -> None:
        locate_tab = getattr(self, "_find_news_tab", None)
        located_tab = locate_tab(str(keyword or "").strip()) if callable(locate_tab) else None
        if located_tab is None:
            tabs_list = getattr(self, "_tabs", None)
            if isinstance(tabs_list, list):
                setattr(
                    self,
                    "_tabs",
                    [tab for tab in tabs_list if str(getattr(tab, "keyword", "")) != str(keyword or "").strip()],
                )
            return
        index, widget = located_tab
        try:
            widget.cleanup()
        except Exception:
            pass
        try:
            widget.deleteLater()
        except Exception:
            pass
        tabs_widget = getattr(self, "tabs", None)
        if tabs_widget is not None and hasattr(tabs_widget, "removeTab"):
            tabs_widget.removeTab(index)
        else:
            tabs_list = getattr(self, "_tabs", None)
            if isinstance(tabs_list, list) and 0 <= index < len(tabs_list):
                tabs_list.pop(index)
        remove_tab_hydration = getattr(self, "_remove_tab_hydration", None)
        if callable(remove_tab_hydration):
            remove_tab_hydration(keyword)
        tab_fetch_state = getattr(self, "_tab_fetch_state", None)
        if isinstance(tab_fetch_state, dict):
            tab_fetch_state.pop(keyword, None)
        removed_fetch_key = self._canonical_fetch_key_for_keyword(keyword)
        prune_fetch_key_state = getattr(self, "_prune_fetch_key_state", None)
        if callable(prune_fetch_key_state):
            prune_fetch_key_state(removed_fetch_key)

    def _rollback_import_runtime_state(
        self: MainApp,
        runtime_snapshot: Dict[str, Any],
        added_keywords: List[str],
    ) -> None:
        for keyword in reversed(added_keywords):
            self._remove_imported_tab_for_rollback(keyword)
        self.theme_idx = int(runtime_snapshot["theme_idx"])
        self.interval_idx = int(runtime_snapshot["interval_idx"])
        self.notification_enabled = bool(runtime_snapshot["notification_enabled"])
        self.alert_keywords = list(runtime_snapshot["alert_keywords"])
        self.sound_enabled = bool(runtime_snapshot["sound_enabled"])
        self.minimize_to_tray = bool(runtime_snapshot["minimize_to_tray"])
        self.close_to_tray = bool(runtime_snapshot["close_to_tray"])
        self.start_minimized = bool(runtime_snapshot["start_minimized"])
        self.auto_start_enabled = bool(runtime_snapshot["auto_start_enabled"])
        self.notify_on_refresh = bool(runtime_snapshot["notify_on_refresh"])
        self.auto_backup_minutes = int(runtime_snapshot.get("auto_backup_minutes", 60) or 0)
        self.api_timeout = int(runtime_snapshot["api_timeout"])
        self.blocked_publishers = list(runtime_snapshot["blocked_publishers"])
        self.preferred_publishers = list(runtime_snapshot["preferred_publishers"])
        self.cloud_sync_enabled = bool(runtime_snapshot.get("cloud_sync_enabled", True))
        self.cloud_sync_dir = str(runtime_snapshot.get("cloud_sync_dir", "") or "")
        self.cloud_sync_interval_minutes = int(runtime_snapshot.get("cloud_sync_interval_minutes", 30) or 30)
        self.saved_searches = dict(runtime_snapshot["saved_searches"])
        self.tab_refresh_policies = dict(runtime_snapshot["tab_refresh_policies"])
        self.automation_rules = normalize_automation_rules(runtime_snapshot.get("automation_rules", []))
        self.publisher_aliases = normalize_publisher_aliases(runtime_snapshot.get("publisher_aliases", {}))
        self.search_history = list(runtime_snapshot["search_history"])
        self._fetch_cursor_by_key = dict(runtime_snapshot["fetch_cursor_by_key"])
        self._fetch_total_by_key = dict(runtime_snapshot["fetch_total_by_key"])
        self._saved_geometry = runtime_snapshot["saved_geometry"]
        previous_geometry = dict(runtime_snapshot["window_geometry"])
        self.setGeometry(
            previous_geometry["x"],
            previous_geometry["y"],
            previous_geometry["width"],
            previous_geometry["height"],
        )
        self.keyword_group_manager.groups = dict(runtime_snapshot["keyword_groups"])
        self.keyword_group_manager.last_error = ""
        self.setStyleSheet(self._active_app_stylesheet() if hasattr(self, "_active_app_stylesheet") else (AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT))
        for _index, widget in self._iter_news_tabs():
            widget.theme = self._effective_theme_idx() if hasattr(self, "_effective_theme_idx") else self.theme_idx
            widget.render_html()
        self.apply_refresh_interval()
        if hasattr(self, "apply_auto_backup_interval"):
            self.apply_auto_backup_interval()

    def _apply_import_runtime_stage(
        self: MainApp,
        stage: Dict[str, Any],
    ) -> List[str]:
        normalized_settings = dict(stage["normalized_settings"])
        imported_geometry = stage.get("imported_geometry")
        previous_visibility = (
            tuple(getattr(self, "blocked_publishers", [])),
            tuple(getattr(self, "preferred_publishers", [])),
        )
        self.theme_idx = normalized_settings["theme_index"]
        self.interval_idx = normalized_settings["refresh_interval_index"]
        self.notification_enabled = normalized_settings["notification_enabled"]
        self.alert_keywords = normalized_settings["alert_keywords"]
        self.sound_enabled = normalized_settings["sound_enabled"]
        self.minimize_to_tray = normalized_settings["minimize_to_tray"]
        self.close_to_tray = normalized_settings["close_to_tray"]
        self.start_minimized = normalized_settings["start_minimized"]
        self.auto_start_enabled = normalized_settings["auto_start_enabled"]
        self.notify_on_refresh = normalized_settings["notify_on_refresh"]
        self.auto_backup_minutes = int(normalized_settings.get("auto_backup_minutes", 60) or 0)
        self.api_timeout = normalized_settings["api_timeout"]
        self.cloud_sync_enabled = bool(normalized_settings.get("cloud_sync_enabled", True))
        self.cloud_sync_interval_minutes = int(normalized_settings.get("cloud_sync_interval_minutes", 30) or 30)
        self.blocked_publishers, self.preferred_publishers = normalize_publisher_filter_lists(
            normalized_settings["blocked_publishers"],
            normalized_settings["preferred_publishers"],
        )
        self.saved_searches = dict(stage["staged_config"].get("saved_searches", {}))
        self.tab_refresh_policies = dict(stage["staged_config"].get("tab_refresh_policies", {}))
        self.automation_rules = normalize_automation_rules(stage["staged_config"].get("automation_rules", []))
        self.publisher_aliases = normalize_publisher_aliases(stage["staged_config"].get("publisher_aliases", {}))
        self.search_history = list(stage["merged_search_history"])
        self._fetch_cursor_by_key = dict(stage["merged_pagination_state"])
        self._fetch_total_by_key = dict(stage["merged_pagination_totals"])
        if imported_geometry is not None:
            self._saved_geometry = imported_geometry
            self.setGeometry(
                imported_geometry["x"],
                imported_geometry["y"],
                imported_geometry["width"],
                imported_geometry["height"],
            )
        self.setStyleSheet(self._active_app_stylesheet() if hasattr(self, "_active_app_stylesheet") else (AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT))
        for _index, widget in self._iter_news_tabs():
            widget.theme = self._effective_theme_idx() if hasattr(self, "_effective_theme_idx") else self.theme_idx
            widget.render_html()
        added_keywords = stage.setdefault("applied_new_keywords", [])
        added_keywords.clear()
        for keyword in stage["imported_new_keywords"]:
            self.add_news_tab(keyword)
            added_keywords.append(keyword)
        self.keyword_group_manager.groups = dict(stage["merged_keyword_groups"])
        self.keyword_group_manager.last_error = ""
        self.apply_refresh_interval()
        if hasattr(self, "apply_auto_backup_interval"):
            self.apply_auto_backup_interval()
        if hasattr(self, "apply_cloud_sync_settings"):
            self.apply_cloud_sync_settings()
        refresh_saved_searches = getattr(self, "_refresh_saved_search_combos", None)
        if callable(refresh_saved_searches):
            refresh_saved_searches()
        current_visibility = (
            tuple(getattr(self, "blocked_publishers", [])),
            tuple(getattr(self, "preferred_publishers", [])),
        )
        if current_visibility != previous_visibility:
            reload_visibility = getattr(self, "_reload_tabs_for_visibility_filters", None)
            if callable(reload_visibility):
                reload_visibility()
            else:
                for _index, widget in self._iter_news_tabs():
                    load_data = getattr(widget, "load_data_from_db", None)
                    if callable(load_data):
                        load_data()
        return added_keywords
