# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

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
        """북마크 탭 새로고침"""
        self.bm_tab.load_data_from_db()

    def on_database_maintenance_completed(
        self: MainApp,
        operation: str,
        affected_count: int = 0,
    ):
        """DB 직접 변경 후 열린 탭/배지/UI 상태를 동기화한다."""
        try:
            for _index, widget in self._iter_news_tabs():
                widget.load_data_from_db()
            self._schedule_badge_refresh(delay_ms=0)
            self.update_tray_tooltip()
            QTimer.singleShot(300, self.update_tray_tooltip)
            logger.info(f"DB 유지보수 후 UI 동기화 완료: op={operation}, count={affected_count}")
        except Exception as e:
            logger.warning(f"DB 유지보수 후 UI 동기화 오류: {e}")

    def export_data(self: MainApp):
        """데이터 내보내기"""
        cur_widget = self._current_news_tab()
        if cur_widget is None or not cur_widget.news_data_cache:
            QMessageBox.information(self, "알림", "저장할 뉴스가 없습니다.")
            return

        keyword = cur_widget.keyword
        default_name = f"{keyword}_뉴스_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        fname, _ = QFileDialog.getSaveFileName(
            self,
            "데이터 내보내기",
            default_name,
            "CSV Files (*.csv);;All Files (*)"
        )

        if fname:
            try:
                with open(fname, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복"])

                    for item in cur_widget.news_data_cache:
                        writer.writerow([
                            item["title"],
                            item["link"],
                            item["pubDate"],
                            item["publisher"],
                            item["description"],
                            "읽음" if item["is_read"] else "안읽음",
                            "⭐" if item["is_bookmarked"] else "",
                            item.get("notes", ""),
                            "유사" if item.get("is_duplicate", 0) else "",
                        ])

                self.show_success_toast(f"✓ {len(cur_widget.news_data_cache)}개 항목이 저장되었습니다")
                QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")

            except Exception as e:
                QMessageBox.warning(self, "오류", f"저장 중 오류 발생:\n{str(e)}")

    def export_settings(self: MainApp):
        """설정 JSON 내보내기 (API 키 제외)"""
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "설정 내보내기",
            f"news_scraper_settings_{datetime.now().strftime('%Y%m%d')}.json",
            "JSON Files (*.json);;All Files (*)"
        )

        if fname:
            export_data = {
                "export_version": "1.0",
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
                    "notify_on_refresh": self.notify_on_refresh,
                    "api_timeout": self.api_timeout,
                },
                "tabs": [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)],
                "keyword_groups": self.keyword_group_manager.groups,
            }

            try:
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=4, ensure_ascii=False)
                self.show_success_toast("✓ 설정이 내보내기되었습니다.")
                QMessageBox.information(self, "완료", f"설정이 저장되었습니다:\n{fname}\n\n(API 키는 보안상 제외됨)")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 내보내기 오류:\n{str(e)}")

    def import_settings(self: MainApp):
        """설정 JSON 가져오기"""
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "설정 가져오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )

        if fname:
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    import_data = json.load(f)

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
                    "notify_on_refresh": self.notify_on_refresh,
                    "api_timeout": self.api_timeout,
                }
                normalized_settings, import_warnings = normalize_import_settings(
                    settings, fallback_settings
                )

                self.theme_idx = normalized_settings["theme_index"]
                self.interval_idx = normalized_settings["refresh_interval_index"]
                self.notification_enabled = normalized_settings["notification_enabled"]
                self.alert_keywords = normalized_settings["alert_keywords"]
                self.sound_enabled = normalized_settings["sound_enabled"]
                self.minimize_to_tray = normalized_settings["minimize_to_tray"]
                self.close_to_tray = normalized_settings["close_to_tray"]
                self.start_minimized = normalized_settings["start_minimized"]
                self.notify_on_refresh = normalized_settings["notify_on_refresh"]
                self.api_timeout = normalized_settings["api_timeout"]

                self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
                for _index, widget in self._iter_news_tabs():
                    widget.theme = self.theme_idx
                    widget.render_html()

                imported_tabs = import_data.get("tabs", [])
                existing_keywords = {
                    tab.keyword
                    for _index, tab in self._iter_news_tabs(start_index=1)
                }

                new_tabs = 0
                skipped_invalid_tabs = 0
                for keyword in imported_tabs:
                    if isinstance(keyword, str):
                        keyword = self._normalize_tab_keyword(keyword.strip())
                    else:
                        keyword = None
                    if keyword and keyword not in existing_keywords:
                        self.add_news_tab(keyword)
                        existing_keywords.add(keyword)
                        new_tabs += 1
                    elif not keyword:
                        skipped_invalid_tabs += 1

                imported_groups = import_data.get("keyword_groups", {})
                if isinstance(imported_groups, dict):
                    self.keyword_group_manager.merge_groups(imported_groups, save=True)

                self.apply_refresh_interval()
                self.save_config()

                msg = "✓ 설정을 가져왔습니다."
                if new_tabs > 0:
                    msg += f" ({new_tabs}개 탭 추가됨)"
                if skipped_invalid_tabs > 0:
                    msg += f" / 유효하지 않은 탭 {skipped_invalid_tabs}개 건너뜀"
                if import_warnings:
                    logger.warning("설정 가져오기 보정 항목:\n- %s", "\n- ".join(import_warnings))
                    msg += f" / 설정값 {len(import_warnings)}개 보정"
                self.show_toast(msg)

            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 가져오기 오류:\n{str(e)}")

    def show_help(self: MainApp):
        """도움말 표시 (설정 창의 도움말 탭으로 열기)"""
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
        """설정 다이얼로그"""
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
        if dlg.exec():
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
                logger.warning("트레이 미지원 환경: start_minimized 설정을 해제합니다.")
                new_start_minimized = False
                self.show_warning_toast("트레이를 사용할 수 없어 '시작 시 최소화'가 해제되었습니다.")
            self.start_minimized = new_start_minimized
            self.notify_on_refresh = data.get("notify_on_refresh", False)

            new_auto_start = data.get("auto_start_enabled", False)
            auto_start_changed = (new_auto_start != self.auto_start_enabled)
            start_minimized_changed = (new_start_minimized != prev_start_minimized)

            if auto_start_changed or (new_auto_start and start_minimized_changed):
                if new_auto_start:
                    if StartupManager.enable_startup(new_start_minimized):
                        if auto_start_changed:
                            self.show_success_toast("✓ 윈도우 시작 시 자동 실행이 설정되었습니다.")
                        else:
                            self.show_success_toast("✓ 자동 시작 옵션이 업데이트되었습니다.")
                        self.auto_start_enabled = True
                    else:
                        self.show_error_toast("자동 시작 설정에 실패했습니다.")
                        logger.error("자동 시작 설정 실패: 레지스트리 반영 실패")
                else:
                    if StartupManager.disable_startup():
                        self.show_success_toast("✓ 자동 실행이 해제되었습니다.")
                        self.auto_start_enabled = False
                    else:
                        self.show_error_toast("자동 시작 해제에 실패했습니다.")
                        logger.error("자동 시작 해제 실패: 레지스트리 반영 실패")
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

            self.show_success_toast("✓ 설정이 저장되었습니다.")
