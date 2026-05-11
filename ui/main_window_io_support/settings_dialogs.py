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

from ui.main_window_io_support.exports import _dialogs_for

class _MainWindowSettingsDialogsMixin:
    def _build_current_settings_dialog_config(self: MainApp) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "interval": self.interval_idx,
            "theme": self.theme_idx,
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
            "cloud_sync_dir": str(getattr(self, "cloud_sync_dir", "") or ""),
            "cloud_sync_interval_minutes": int(getattr(self, "cloud_sync_interval_minutes", 30) or 30),
            "cloud_sync_last_status": str(getattr(self, "_cloud_sync_last_status", "") or ""),
        }
    def refresh_bookmark_tab(self: MainApp):
        """Reload the bookmark tab."""
        should_block_db_action = getattr(self, "should_block_db_action", None)
        if callable(should_block_db_action) and should_block_db_action(
            "북마크 DB 새로고침",
            notify=False,
        ):
            return
        self.bm_tab.load_data_from_db()
    def _import_refresh_block_reason(
        self: MainApp,
    ) -> str:
        refresh_block_reason = getattr(self, "_refresh_block_reason", None)
        if callable(refresh_block_reason):
            return str(refresh_block_reason("가져온 탭 새로고침") or "")
        return ""
    def _maybe_refresh_imported_tabs(
        self: MainApp,
        imported_keywords: List[str],
    ) -> None:
        if not imported_keywords:
            return

        block_reason = self._import_refresh_block_reason()
        if block_reason:
            self._status_bar().showMessage(block_reason, 5000)
            self.show_warning_toast(block_reason)
            _dialogs_for(self).warning(self, "새로고침 불가", block_reason)
            return

        if self._prompt_refresh_imported_tabs(imported_keywords):
            self.refresh_selected_tabs(imported_keywords)
    def export_settings(self: MainApp):
        """Export app settings without API credentials."""
        dialogs = _dialogs_for(self)
        fname, _ = dialogs.get_save_file_name(
            self,
            "설정 내보내기",
            f"news_scraper_settings_{datetime.now().strftime('%Y%m%d')}.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not fname:
            return

        export_data = {
            "export_version": "1.3",
            "app_version": VERSION,
            "export_machine_id": get_machine_identity(),
            "settings": {
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
            },
            "tabs": [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)],
            "keyword_groups": self.keyword_group_manager.groups,
            "search_history": self.search_history,
            "pagination_state": self._fetch_cursor_by_key,
            "pagination_totals": self._fetch_total_by_key,
            "saved_searches": getattr(self, "saved_searches", {}),
            "tab_refresh_policies": getattr(self, "tab_refresh_policies", {}),
            "automation_rules": normalize_automation_rules(getattr(self, "automation_rules", [])),
            "publisher_aliases": normalize_publisher_aliases(getattr(self, "publisher_aliases", {})),
            "window_geometry": {
                "x": self.x(),
                "y": self.y(),
                "width": self.width(),
                "height": self.height(),
            },
        }

        try:
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=4, ensure_ascii=False)
            self.show_success_toast("설정을 내보냈습니다.")
            dialogs.information(
                self,
                "완료",
                f"설정이 저장되었습니다:\n{fname}\n\n"
                "API 자격증명은 보안상 제외되며, 자동 시작 설정은 함께 저장됩니다.",
            )
        except Exception as e:
            dialogs.warning(self, "오류", f"설정 내보내기 오류:\n{e}")
    def _prompt_refresh_imported_tabs(
        self: MainApp,
        imported_keywords: List[str],
    ) -> bool:
        if not imported_keywords:
            return False
        count = len(imported_keywords)
        label = f"{count}개 새 탭" if count > 1 else f"'{imported_keywords[0]}' 탭"
        return _dialogs_for(self).ask_yes_no(
            self,
            "새 탭 새로고침",
            f"설정 가져오기로 {label}이 추가되었습니다.\n지금 새로고침할까요?",
        )
    def _reconcile_startup_state_from_import(
        self: MainApp,
        normalized_settings: Dict[str, Any],
        import_warnings: List[str],
    ) -> None:
        requested_auto_start = bool(normalized_settings.get("auto_start_enabled", False))
        requested_start_minimized = bool(normalized_settings.get("start_minimized", False))

        if requested_auto_start and not StartupManager.is_available():
            normalized_settings["auto_start_enabled"] = False
            requested_auto_start = False
            import_warnings.append(
                "시작프로그램 기능을 사용할 수 없어 auto_start_enabled 값을 False로 강제했습니다."
            )
            self.show_warning_toast(
                "시작프로그램 기능을 사용할 수 없어 자동 시작 설정은 꺼진 상태로 가져왔습니다."
            )

        if not StartupManager.is_available():
            return

        if requested_auto_start:
            if StartupManager.enable_startup(requested_start_minimized):
                status = StartupManager.get_startup_status(requested_start_minimized)
                normalized_settings["auto_start_enabled"] = bool(status.get("is_healthy", False))
                if normalized_settings["auto_start_enabled"]:
                    return
                import_warnings.append("자동 시작 등록은 되었지만 현재 상태가 비정상이라 수리가 필요합니다.")
                self.show_warning_toast("자동 시작 등록 상태가 비정상입니다. 설정에서 수리해 주세요.")
                return
            normalized_settings["auto_start_enabled"] = StartupManager.get_startup_status(
                requested_start_minimized
            ).get("is_healthy", False)
            import_warnings.append("자동 시작 설정을 시스템에 적용하지 못해 현재 상태를 유지했습니다.")
            self.show_warning_toast("자동 시작 설정 적용에 실패해 시스템 상태를 유지했습니다.")
            return

        if StartupManager.disable_startup():
            status = StartupManager.get_startup_status(False)
            normalized_settings["auto_start_enabled"] = bool(status.get("is_healthy", False))
            if not status.get("has_registry_value", False):
                return
            import_warnings.append("자동 시작 항목이 남아 있어 완전히 해제되지 않았습니다.")
            self.show_warning_toast("자동 시작 항목이 남아 있습니다. 설정에서 다시 확인해 주세요.")
            return

        normalized_settings["auto_start_enabled"] = bool(
            StartupManager.get_startup_status(False).get("is_healthy", False)
        )
        import_warnings.append("자동 시작 해제를 시스템에 적용하지 못해 현재 상태를 유지했습니다.")
        self.show_warning_toast("자동 시작 해제에 실패해 시스템 상태를 유지했습니다.")
    def import_settings(self: MainApp):
        """Import settings JSON and merge user-state fields conservatively."""
        dialogs = _dialogs_for(self)
        fname, _ = dialogs.get_open_file_name(
            self,
            "설정 가져오기",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if not fname:
            return

        try:
            with open(fname, "r", encoding="utf-8") as f:
                import_data = json.load(f)
            if not isinstance(import_data, dict):
                raise ValueError("설정 파일 루트가 JSON object가 아닙니다.")
            runtime_snapshot = self._snapshot_runtime_state_for_import()
            config_path = self._config_path_for_persistence()
            stage = self._stage_settings_import(import_data)
            normalized_settings = stage["normalized_settings"]
            import_warnings = stage["import_warnings"]
            imported_new_keywords = list(stage["imported_new_keywords"])
            skipped_invalid_tabs = int(stage["skipped_invalid_tabs"])

            save_primary_config_file(config_path, stage["staged_config"])

            added_keywords: List[str] = []
            try:
                added_keywords = self._apply_import_runtime_stage(stage)
            except Exception:
                added_keywords = list(stage.get("applied_new_keywords", added_keywords))
                try:
                    save_primary_config_file(config_path, runtime_snapshot["config_payload"])
                except Exception as rollback_save_error:
                    logger.error("Import config rollback failed: %s", rollback_save_error)
                self._rollback_import_runtime_state(runtime_snapshot, added_keywords)
                raise

            self._reconcile_startup_state_from_import(normalized_settings, import_warnings)
            corrected_auto_start = bool(normalized_settings.get("auto_start_enabled", self.auto_start_enabled))
            if self.auto_start_enabled != corrected_auto_start:
                self.auto_start_enabled = corrected_auto_start
                corrected_config = self._build_runtime_config_payload(
                    app_settings_overrides={"auto_start_enabled": corrected_auto_start}
                )
                save_primary_config_file(config_path, corrected_config)

            msg = "설정을 가져왔습니다."
            if imported_new_keywords:
                msg += f" ({len(imported_new_keywords)}개 탭 추가)"
            saved_search_import_count = int(stage.get("saved_search_import_count", 0) or 0)
            tab_policy_import_count = int(stage.get("tab_policy_import_count", 0) or 0)
            if saved_search_import_count > 0:
                msg += f" / 저장 검색 {saved_search_import_count}개 병합"
            if tab_policy_import_count > 0:
                msg += f" / 탭 정책 {tab_policy_import_count}개 병합"
            if skipped_invalid_tabs > 0:
                msg += f" / 유효하지 않은 탭 {skipped_invalid_tabs}개 건너뜀"
            if import_warnings:
                logger.warning("Import warnings:\n- %s", "\n- ".join(import_warnings))
                msg += f" / 보정 {len(import_warnings)}건"
            self.show_toast(msg)

            maybe_refresh_imported_tabs = getattr(self, "_maybe_refresh_imported_tabs", None)
            if callable(maybe_refresh_imported_tabs):
                maybe_refresh_imported_tabs(imported_new_keywords)
            elif self._prompt_refresh_imported_tabs(imported_new_keywords):
                self.refresh_selected_tabs(imported_new_keywords)
        except Exception as e:
            dialogs.warning(self, "오류", f"설정 가져오기 오류:\n{e}")
    def show_help(self: MainApp):
        """Open the Settings dialog directly on the help tab."""
        dlg = SettingsDialog(
            self._build_current_settings_dialog_config(),
            self,
            initial_tab=0,
            help_mode=True,
        )
        dlg.exec()
    def open_settings(self: MainApp):
        """Open the main settings dialog."""
        dlg = SettingsDialog(self._build_current_settings_dialog_config(), self)
        if not dlg.exec():
            return

        data = dlg.get_data()
        self.client_id = data["id"]
        self.client_secret = data["secret"]
        self.interval_idx = data["interval"]
        self.auto_backup_minutes = int(data.get("auto_backup_minutes", 60) or 0)

        self.notification_enabled = data.get("notification_enabled", True)
        self.alert_keywords = data.get("alert_keywords", [])
        self.sound_enabled = data.get("sound_enabled", True)
        self.api_timeout = data.get("api_timeout", 15)
        self.cloud_sync_enabled = bool(data.get("cloud_sync_enabled", True))
        self.cloud_sync_dir = str(data.get("cloud_sync_dir", "") or "")
        self.cloud_sync_interval_minutes = int(data.get("cloud_sync_interval_minutes", 30) or 30)
        self.blocked_publishers, self.preferred_publishers = normalize_publisher_filter_lists(
            data.get("blocked_publishers", []),
            data.get("preferred_publishers", []),
        )

        self.minimize_to_tray = data.get("minimize_to_tray", True)
        self.close_to_tray = data.get("close_to_tray", True)
        prev_start_minimized = self.start_minimized
        new_start_minimized = data.get("start_minimized", False)
        if new_start_minimized and not getattr(self, "tray", None):
            logger.warning("start_minimized requested without tray support; forcing False")
            new_start_minimized = False
            self.show_warning_toast(
                "트레이를 사용할 수 없어 '시작 시 최소화' 옵션은 해제되었습니다."
            )
        self.start_minimized = new_start_minimized
        self.notify_on_refresh = data.get("notify_on_refresh", False)

        new_auto_start = data.get("auto_start_enabled", False)
        auto_start_changed = new_auto_start != self.auto_start_enabled
        start_minimized_changed = new_start_minimized != prev_start_minimized

        if auto_start_changed or (new_auto_start and start_minimized_changed):
            if new_auto_start:
                if StartupManager.enable_startup(new_start_minimized):
                    status = StartupManager.get_startup_status(new_start_minimized)
                    self.auto_start_enabled = bool(status.get("is_healthy", False))
                    if self.auto_start_enabled:
                        if auto_start_changed:
                            self.show_success_toast("자동 시작을 설정했습니다.")
                        else:
                            self.show_success_toast("자동 시작 옵션을 갱신했습니다.")
                    else:
                        self.show_warning_toast("자동 시작 등록은 되었지만 상태가 비정상입니다. 설정에서 수리해 주세요.")
                else:
                    self.auto_start_enabled = bool(
                        StartupManager.get_startup_status(new_start_minimized).get("is_healthy", False)
                    )
                    self.show_error_toast("자동 시작 설정에 실패했습니다.")
                    logger.error("Failed to enable startup")
            else:
                if StartupManager.disable_startup():
                    status = StartupManager.get_startup_status(False)
                    self.auto_start_enabled = bool(status.get("is_healthy", False))
                    if not status.get("has_registry_value", False):
                        self.show_success_toast("자동 시작을 해제했습니다.")
                    else:
                        self.show_warning_toast("자동 시작 항목이 남아 있습니다. 설정에서 다시 확인해 주세요.")
                else:
                    self.auto_start_enabled = bool(
                        StartupManager.get_startup_status(False).get("is_healthy", False)
                    )
                    self.show_error_toast("자동 시작 해제에 실패했습니다.")
                    logger.error("Failed to disable startup")
        else:
            if new_auto_start:
                self.auto_start_enabled = bool(
                    StartupManager.get_startup_status(new_start_minimized).get("is_healthy", False)
                )
            else:
                self.auto_start_enabled = False

        if self.theme_idx != data["theme"]:
            self.theme_idx = data["theme"]
            self.setStyleSheet(self._active_app_stylesheet() if hasattr(self, "_active_app_stylesheet") else (AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT))
            for _index, widget in self._iter_news_tabs():
                widget.theme = self._effective_theme_idx() if hasattr(self, "_effective_theme_idx") else self.theme_idx
                widget.render_html()

        self.apply_refresh_interval()
        if hasattr(self, "apply_auto_backup_interval"):
            self.apply_auto_backup_interval()
        if hasattr(self, "apply_cloud_sync_settings"):
            self.apply_cloud_sync_settings()
        self.save_config()
        for _index, widget in self._iter_news_tabs():
            widget.load_data_from_db()
        self.show_success_toast("설정을 저장했습니다.")
