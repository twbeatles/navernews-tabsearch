# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTabWidget

from core.config_store import normalize_import_settings
from core.constants import VERSION
from core.startup import StartupManager
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)


class _MainWindowSettingsIOMixin:
    def refresh_bookmark_tab(self: MainApp):
        """Reload the bookmark tab."""
        self.bm_tab.load_data_from_db()

    def on_database_maintenance_completed(
        self: MainApp,
        operation: str,
        affected_count: int = 0,
    ):
        """Refresh open tabs and badges after direct DB maintenance."""
        try:
            for _index, widget in self._iter_news_tabs():
                widget.load_data_from_db()
            self._schedule_badge_refresh(delay_ms=0)
            self.update_tray_tooltip()
            QTimer.singleShot(300, self.update_tray_tooltip)
            logger.info(
                "UI sync completed after DB maintenance: op=%s, count=%s",
                operation,
                affected_count,
            )
        except Exception as e:
            logger.warning("UI sync after DB maintenance failed: %s", e)

    def export_data(self: MainApp):
        """Export the current tab's rows as CSV."""
        cur_widget = self._current_news_tab()
        export_items: List[Dict[str, Any]] = []
        if cur_widget is not None:
            if hasattr(cur_widget, "get_all_filtered_items"):
                try:
                    export_items = list(cur_widget.get_all_filtered_items())
                except Exception as e:
                    logger.warning("Falling back to loaded slice during export: %s", e)
                    export_items = list(cur_widget.filtered_data_cache)
            else:
                export_items = list(cur_widget.filtered_data_cache)
        if cur_widget is None or not export_items:
            QMessageBox.information(self, "알림", "내보낼 뉴스가 없습니다.")
            return

        keyword = cur_widget.keyword
        default_name = f"{keyword}_뉴스_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "데이터 내보내기",
            default_name,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return

        try:
            with open(fname, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복"])
                for item in export_items:
                    writer.writerow(
                        [
                            item["title"],
                            item["link"],
                            item["pubDate"],
                            item["publisher"],
                            item["description"],
                            "읽음" if item["is_read"] else "안읽음",
                            "북마크" if item["is_bookmarked"] else "",
                            item.get("notes", ""),
                            "중복" if item.get("is_duplicate", 0) else "",
                        ]
                    )

            self.show_success_toast(f"총 {len(export_items)}개 항목을 저장했습니다.")
            QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")
        except Exception as e:
            QMessageBox.warning(self, "오류", f"내보내기 중 오류가 발생했습니다:\n{e}")

    def _merge_search_history(
        self: MainApp,
        imported_history: Any,
    ) -> List[str]:
        merged: List[str] = []
        seen_identities = set()
        raw_items: List[str] = []
        if isinstance(imported_history, list):
            raw_items.extend(str(item).strip() for item in imported_history if isinstance(item, str))
        raw_items.extend(str(item).strip() for item in self.search_history if isinstance(item, str))
        for keyword in raw_items:
            if not keyword:
                continue
            identity = self._history_identity_for_keyword(keyword)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            merged.append(keyword)
        return merged[:10]

    def _merge_int_mapping_keep_max(
        self: MainApp,
        current: Dict[str, int],
        incoming: Any,
        minimum: int,
    ) -> Dict[str, int]:
        merged: Dict[str, int] = {
            str(key): int(value)
            for key, value in current.items()
            if isinstance(key, str) and key.strip() and isinstance(value, int) and value >= minimum
        }
        if not isinstance(incoming, dict):
            return merged

        for raw_key, raw_value in incoming.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            if not key:
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value < minimum:
                continue
            current_value = merged.get(key)
            if current_value is None or value > current_value:
                merged[key] = value
        return merged

    def _validated_import_window_geometry(
        self: MainApp,
        raw_geometry: Any,
    ) -> Optional[Dict[str, int]]:
        if not isinstance(raw_geometry, dict):
            return None

        try:
            parsed = {
                "x": int(raw_geometry.get("x")),
                "y": int(raw_geometry.get("y")),
                "width": int(raw_geometry.get("width")),
                "height": int(raw_geometry.get("height")),
            }
        except (TypeError, ValueError):
            return None

        normalized = self._normalize_window_geometry(parsed)
        if normalized != parsed:
            return None
        return parsed

    def export_settings(self: MainApp):
        """Export app settings without API credentials."""
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "설정 내보내기",
            f"news_scraper_settings_{datetime.now().strftime('%Y%m%d')}.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not fname:
            return

        export_data = {
            "export_version": "1.2",
            "app_version": VERSION,
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
                "api_timeout": self.api_timeout,
            },
            "tabs": [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)],
            "keyword_groups": self.keyword_group_manager.groups,
            "search_history": self.search_history,
            "pagination_state": self._fetch_cursor_by_key,
            "pagination_totals": self._fetch_total_by_key,
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
            QMessageBox.information(
                self,
                "완료",
                f"설정이 저장되었습니다:\n{fname}\n\n"
                "API 자격증명은 보안상 제외되며, 자동 시작 설정은 함께 저장됩니다.",
            )
        except Exception as e:
            QMessageBox.warning(self, "오류", f"설정 내보내기 오류:\n{e}")

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
                return
            normalized_settings["auto_start_enabled"] = StartupManager.is_startup_enabled()
            import_warnings.append("자동 시작 설정을 시스템에 적용하지 못해 현재 상태를 유지했습니다.")
            self.show_warning_toast("자동 시작 설정 적용에 실패해 시스템 상태를 유지했습니다.")
            return

        if StartupManager.disable_startup():
            return
        normalized_settings["auto_start_enabled"] = StartupManager.is_startup_enabled()
        import_warnings.append("자동 시작 해제를 시스템에 적용하지 못해 현재 상태를 유지했습니다.")
        self.show_warning_toast("자동 시작 해제에 실패해 시스템 상태를 유지했습니다.")

    def import_settings(self: MainApp):
        """Import settings JSON and merge user-state fields conservatively."""
        fname, _ = QFileDialog.getOpenFileName(
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

            settings = import_data.get("settings", {})
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
                "api_timeout": self.api_timeout,
            }
            normalized_settings, import_warnings = normalize_import_settings(
                settings,
                fallback_settings,
            )

            if normalized_settings["start_minimized"] and not getattr(self, "tray", None):
                normalized_settings["start_minimized"] = False
                import_warnings.append(
                    "트레이를 사용할 수 없어 start_minimized 값을 False로 강제했습니다."
                )
                self.show_warning_toast(
                    "트레이를 사용할 수 없어 '시작 시 최소화' 설정은 꺼진 상태로 가져왔습니다."
                )

            self._reconcile_startup_state_from_import(normalized_settings, import_warnings)

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
            self.api_timeout = normalized_settings["api_timeout"]

            self.search_history = self._merge_search_history(import_data.get("search_history", []))
            self._fetch_cursor_by_key = self._merge_int_mapping_keep_max(
                self._fetch_cursor_by_key,
                import_data.get("pagination_state", {}),
                minimum=1,
            )
            self._fetch_total_by_key = self._merge_int_mapping_keep_max(
                self._fetch_total_by_key,
                import_data.get("pagination_totals", {}),
                minimum=0,
            )

            imported_geometry = self._validated_import_window_geometry(
                import_data.get("window_geometry")
            )
            if imported_geometry is not None:
                self._saved_geometry = imported_geometry
                self.setGeometry(
                    imported_geometry["x"],
                    imported_geometry["y"],
                    imported_geometry["width"],
                    imported_geometry["height"],
                )
            elif "window_geometry" in import_data:
                import_warnings.append("window_geometry 값이 유효 범위를 벗어나 적용하지 않았습니다.")

            self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
            for _index, widget in self._iter_news_tabs():
                widget.theme = self.theme_idx
                widget.render_html()

            imported_tabs = import_data.get("tabs", [])
            existing_fetch_keys = {
                self._canonical_fetch_key_for_keyword(tab.keyword)
                for _index, tab in self._iter_news_tabs(start_index=1)
                if self._canonical_fetch_key_for_keyword(tab.keyword)
            }
            new_tabs = 0
            skipped_invalid_tabs = 0
            for keyword in imported_tabs:
                normalized_keyword = self._normalize_tab_keyword(keyword.strip()) if isinstance(keyword, str) else None
                normalized_fetch_key = (
                    self._canonical_fetch_key_for_keyword(normalized_keyword)
                    if normalized_keyword
                    else ""
                )
                if normalized_keyword and normalized_fetch_key and normalized_fetch_key not in existing_fetch_keys:
                    self.add_news_tab(normalized_keyword)
                    existing_fetch_keys.add(normalized_fetch_key)
                    new_tabs += 1
                elif not normalized_keyword:
                    skipped_invalid_tabs += 1

            imported_groups = import_data.get("keyword_groups", {})
            if isinstance(imported_groups, dict):
                self.keyword_group_manager.merge_groups(imported_groups, save=True)

            self.apply_refresh_interval()
            self.save_config()

            msg = "설정을 가져왔습니다."
            if new_tabs > 0:
                msg += f" ({new_tabs}개 탭 추가)"
            if skipped_invalid_tabs > 0:
                msg += f" / 유효하지 않은 탭 {skipped_invalid_tabs}개 건너뜀"
            if import_warnings:
                logger.warning("Import warnings:\n- %s", "\n- ".join(import_warnings))
                msg += f" / 보정 {len(import_warnings)}건"
            self.show_toast(msg)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"설정 가져오기 오류:\n{e}")

    def show_help(self: MainApp):
        """Open the Settings dialog directly on the help tab."""
        current_config = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "interval": self.interval_idx,
            "theme": self.theme_idx,
            "sound_enabled": self.sound_enabled,
            "api_timeout": self.api_timeout,
        }

        dlg = SettingsDialog(current_config, self)
        if hasattr(dlg, "findChild"):
            tab_widget = dlg.findChild(QTabWidget)
            if tab_widget:
                tab_widget.setCurrentIndex(1)
        dlg.exec()

    def open_settings(self: MainApp):
        """Open the main settings dialog."""
        current_config = {
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
            "api_timeout": self.api_timeout,
        }

        dlg = SettingsDialog(current_config, self)
        if not dlg.exec():
            return

        data = dlg.get_data()
        self.client_id = data["id"]
        self.client_secret = data["secret"]
        self.interval_idx = data["interval"]

        self.notification_enabled = data.get("notification_enabled", True)
        self.alert_keywords = data.get("alert_keywords", [])
        self.sound_enabled = data.get("sound_enabled", True)
        self.api_timeout = data.get("api_timeout", 15)

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
                    if auto_start_changed:
                        self.show_success_toast("자동 시작을 설정했습니다.")
                    else:
                        self.show_success_toast("자동 시작 옵션을 갱신했습니다.")
                    self.auto_start_enabled = True
                else:
                    self.show_error_toast("자동 시작 설정에 실패했습니다.")
                    logger.error("Failed to enable startup")
            else:
                if StartupManager.disable_startup():
                    self.show_success_toast("자동 시작을 해제했습니다.")
                    self.auto_start_enabled = False
                else:
                    self.show_error_toast("자동 시작 해제에 실패했습니다.")
                    logger.error("Failed to disable startup")
        else:
            self.auto_start_enabled = new_auto_start

        if self.theme_idx != data["theme"]:
            self.theme_idx = data["theme"]
            self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
            for _index, widget in self._iter_news_tabs():
                widget.theme = self.theme_idx
                widget.render_html()

        self.apply_refresh_interval()
        self.save_config()
        self.show_success_toast("설정을 저장했습니다.")
