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
from core.automation_rules import dedupe_automation_rules
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


class _ImportStageApplyMixin:
    def _stage_settings_import(
        self: MainApp,
        import_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        settings = import_data.get("settings", {})
        auto_start_forced_by_machine = False
        if isinstance(settings, dict):
            settings = dict(settings)
            source_machine_id = str(import_data.get("export_machine_id", "") or "").strip()
            if (
                bool(settings.get("auto_start_enabled", False))
                and source_machine_id
                and source_machine_id != get_machine_identity()
            ):
                settings["auto_start_enabled"] = False
                auto_start_forced_by_machine = True
                self.show_warning_toast("다른 PC에서 내보낸 설정이라 자동 시작은 꺼진 상태로 가져왔습니다.")
        else:
            settings = {}
        fallback_settings = {
            "theme_index": self.theme_idx,
            "refresh_interval_index": self.interval_idx,
            "notification_enabled": self.notification_enabled,
            "alert_keywords": self.alert_keywords,
            "sound_enabled": self.sound_enabled,
            "minimize_to_tray": self.minimize_to_tray,
            "close_to_tray": self.close_to_tray,
            "start_minimized": self.start_minimized,
            "auto_start_enabled": self.auto_start_enabled,
            "notify_on_refresh": self.notify_on_refresh,
            "auto_backup_minutes": getattr(self, "auto_backup_minutes", 60),
            "api_timeout": self.api_timeout,
            "blocked_publishers": getattr(self, "blocked_publishers", []),
            "preferred_publishers": getattr(self, "preferred_publishers", []),
            "cloud_sync_enabled": bool(getattr(self, "cloud_sync_enabled", True)),
            "cloud_sync_interval_minutes": int(getattr(self, "cloud_sync_interval_minutes", 30) or 30),
        }
        normalized_settings, import_warnings = normalize_import_settings(
            settings,
            fallback_settings,
        )
        if auto_start_forced_by_machine:
            import_warnings.append("다른 PC에서 내보낸 설정이라 auto_start_enabled 값을 False로 강제했습니다.")

        if normalized_settings["start_minimized"] and not getattr(self, "tray", None):
            normalized_settings["start_minimized"] = False
            import_warnings.append(
                "트레이를 사용할 수 없어 start_minimized 값을 False로 강제했습니다."
            )
            self.show_warning_toast(
                "트레이를 사용할 수 없어 '시작 시 최소화' 설정은 꺼진 상태로 가져왔습니다."
            )

        merged_search_history = self._merge_search_history(import_data.get("search_history", []))
        merged_pagination_state = self._merge_int_mapping_keep_max(
            self._fetch_cursor_by_key,
            import_data.get("pagination_state", {}),
            minimum=1,
        )
        merged_pagination_totals = self._merge_int_mapping_keep_max(
            self._fetch_total_by_key,
            import_data.get("pagination_totals", {}),
            minimum=0,
        )

        imported_geometry = self._validated_import_window_geometry(import_data.get("window_geometry"))
        if imported_geometry is None and "window_geometry" in import_data:
            import_warnings.append("window_geometry 값이 유효 범위를 벗어나 적용하지 않았습니다.")

        imported_new_keywords, skipped_invalid_tabs = self._compute_imported_new_tabs(import_data.get("tabs", []))
        incoming_keyword_groups = import_data.get("keyword_groups", {})
        if isinstance(incoming_keyword_groups, dict):
            empty_group_count = sum(
                1
                for value in incoming_keyword_groups.values()
                if isinstance(value, list) and len([item for item in value if str(item or "").strip()]) == 0
            )
            if empty_group_count > 0:
                import_warnings.append(f"빈 키워드 그룹 {empty_group_count}개를 건너뛰었습니다.")
        merged_keyword_groups = self._merge_imported_keyword_groups(incoming_keyword_groups)
        incoming_saved_searches = import_data.get("saved_searches", {})
        merged_saved_searches = dict(getattr(self, "saved_searches", {}))
        if isinstance(incoming_saved_searches, dict):
            merged_saved_searches.update(incoming_saved_searches)
            if len(merged_saved_searches) > 100:
                import_warnings.append("저장 검색은 최대 100개까지만 유지되어 초과 항목을 잘랐습니다.")

        incoming_tab_refresh_policies = import_data.get("tab_refresh_policies", {})
        merged_tab_refresh_policies = self._canonicalize_tab_refresh_policies(
            getattr(self, "tab_refresh_policies", {}),
            known_keywords=[tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)],
        )
        if isinstance(incoming_tab_refresh_policies, dict):
            merged_tab_refresh_policies.update(
                self._canonicalize_tab_refresh_policies(
                    incoming_tab_refresh_policies,
                    known_keywords=[
                        tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)
                    ] + imported_new_keywords,
                )
            )

        incoming_automation_rules = import_data.get("automation_rules", [])
        merged_automation_rules = dedupe_automation_rules(
            list(getattr(self, "automation_rules", []))
            + (incoming_automation_rules if isinstance(incoming_automation_rules, list) else [])
        )
        incoming_publisher_aliases = import_data.get("publisher_aliases", {})
        merged_publisher_aliases = normalize_publisher_aliases(getattr(self, "publisher_aliases", {}))
        if isinstance(incoming_publisher_aliases, dict):
            merged_publisher_aliases.update(normalize_publisher_aliases(incoming_publisher_aliases))

        staged_config = self._build_runtime_config_payload(
            app_settings_overrides={
                "theme_index": normalized_settings["theme_index"],
                "refresh_interval_index": normalized_settings["refresh_interval_index"],
                "notification_enabled": normalized_settings["notification_enabled"],
                "alert_keywords": normalized_settings["alert_keywords"],
                "sound_enabled": normalized_settings["sound_enabled"],
                "minimize_to_tray": normalized_settings["minimize_to_tray"],
                "close_to_tray": normalized_settings["close_to_tray"],
                "start_minimized": normalized_settings["start_minimized"],
                "auto_start_enabled": normalized_settings["auto_start_enabled"],
                "notify_on_refresh": normalized_settings["notify_on_refresh"],
                "auto_backup_minutes": normalized_settings.get("auto_backup_minutes", 60),
                "api_timeout": normalized_settings["api_timeout"],
                "blocked_publishers": normalized_settings["blocked_publishers"],
                "preferred_publishers": normalized_settings["preferred_publishers"],
                "cloud_sync_enabled": normalized_settings.get("cloud_sync_enabled", True),
                "cloud_sync_dir": getattr(self, "cloud_sync_dir", ""),
                "cloud_sync_interval_minutes": normalized_settings.get("cloud_sync_interval_minutes", 30),
            },
            tab_keywords=[
                tab.keyword
                for _index, tab in self._iter_news_tabs(start_index=1)
            ] + imported_new_keywords,
            search_history=merged_search_history,
            keyword_groups=merged_keyword_groups,
            pagination_state=merged_pagination_state,
            pagination_totals=merged_pagination_totals,
            saved_searches=merged_saved_searches,
            tab_refresh_policies=merged_tab_refresh_policies,
            automation_rules=merged_automation_rules,
            publisher_aliases=merged_publisher_aliases,
            window_geometry=imported_geometry,
        )
        staged_config = normalize_loaded_config(staged_config)
        return {
            "normalized_settings": normalized_settings,
            "import_warnings": import_warnings,
            "merged_search_history": merged_search_history,
            "merged_pagination_state": merged_pagination_state,
            "merged_pagination_totals": merged_pagination_totals,
            "imported_geometry": imported_geometry,
            "imported_new_keywords": imported_new_keywords,
            "skipped_invalid_tabs": skipped_invalid_tabs,
            "merged_keyword_groups": merged_keyword_groups,
            "staged_config": staged_config,
            "saved_search_import_count": len(incoming_saved_searches) if isinstance(incoming_saved_searches, dict) else 0,
            "tab_policy_import_count": len(incoming_tab_refresh_policies) if isinstance(incoming_tab_refresh_policies, dict) else 0,
            "automation_rule_import_count": len(incoming_automation_rules) if isinstance(incoming_automation_rules, list) else 0,
            "publisher_alias_import_count": len(incoming_publisher_aliases) if isinstance(incoming_publisher_aliases, dict) else 0,
        }
