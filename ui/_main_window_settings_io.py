# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import QTimer

from core.config_store import normalize_import_settings
from core.constants import VERSION
from core.startup import StartupManager
from core.workers import DBQueryScope, IterativeJobWorker
from ui.dialog_adapters import get_dialog_adapter
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)

EXPORT_CHUNK_SIZE = 200


def _dialogs_for(target: Any):
    return get_dialog_adapter(target)


def _export_row(item: Dict[str, Any]) -> List[str]:
    return [
        str(item.get("title", "") or ""),
        str(item.get("link", "") or ""),
        str(item.get("pubDate", "") or ""),
        str(item.get("publisher", "") or ""),
        str(item.get("description", "") or ""),
        "읽음" if item.get("is_read") else "안읽음",
        "북마크" if item.get("is_bookmarked") else "",
        str(item.get("notes", "") or ""),
        "중복" if item.get("is_duplicate", 0) else "",
    ]


def export_items_to_csv(
    items: List[Dict[str, Any]],
    output_path: str,
    keyword: str,
) -> Dict[str, Any]:
    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복"])
            for item in items:
                writer.writerow(_export_row(item))
                written += 1
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword}
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def export_scope_to_csv(
    context,
    db_manager,
    scope: DBQueryScope,
    output_path: str,
    keyword: str,
    chunk_size: int = EXPORT_CHUNK_SIZE,
) -> Dict[str, Any]:
    if hasattr(db_manager, "iter_news_snapshot_batches"):
        total_count, batch_iter = db_manager.iter_news_snapshot_batches(
            scope,
            chunk_size=max(1, int(chunk_size)),
        )
    else:
        total_count = int(db_manager.count_news(**scope.count_kwargs()))
        batch_iter = None
    context.report(current=0, total=total_count, message="내보내기 준비 중...", payload={"stage": "count"})
    context.check_cancelled()

    if total_count <= 0:
        raise ValueError("내보낼 뉴스가 없습니다.")

    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복"])

            if batch_iter is None:
                def _fallback_iter():
                    offset = 0
                    while written < total_count:
                        rows = db_manager.fetch_news(
                            limit=max(1, int(chunk_size)),
                            offset=max(0, int(offset)),
                            **scope.fetch_kwargs(),
                        )
                        if not rows:
                            break
                        offset += len(rows)
                        yield rows

                batch_iter = _fallback_iter()

            for rows in batch_iter:
                context.check_cancelled()
                if not rows:
                    break

                for item in rows:
                    context.check_cancelled()
                    writer.writerow(_export_row(item))
                    written += 1

                f.flush()
                os.fsync(f.fileno())
                context.report(
                    current=written,
                    total=total_count,
                    message=f"CSV 내보내는 중... ({written}/{total_count})",
                    payload={"stage": "write", "written": written, "path": output_path},
                )

        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword}
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


class _MainWindowSettingsIOMixin:
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
            "api_timeout": self.api_timeout,
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

    def on_database_maintenance_completed(
        self: MainApp,
        operation: str,
        affected_count: int = 0,
    ):
        """Refresh open tabs and badges after direct DB maintenance."""
        if self.is_maintenance_mode_active():
            logger.info(
                "Skipping UI sync while maintenance mode is still active: op=%s, count=%s",
                operation,
                affected_count,
            )
            return
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
        dialogs = _dialogs_for(self)
        export_worker = getattr(self, "_export_worker", None)
        if export_worker is not None and export_worker.isRunning():
            self._cancel_export_job()
            return

        should_block_db_action = getattr(self, "should_block_db_action", None)
        if callable(should_block_db_action) and should_block_db_action("CSV 내보내기"):
            return

        cur_widget = self._current_news_tab()
        if cur_widget is None:
            dialogs.information(self, "알림", "내보낼 뉴스가 없습니다.")
            return

        known_total = int(getattr(cur_widget, "_total_filtered_count", 0) or 0)
        loaded_count = len(getattr(cur_widget, "filtered_data_cache", []))
        if max(known_total, loaded_count) <= 0:
            dialogs.information(self, "알림", "내보낼 뉴스가 없습니다.")
            return

        keyword = cur_widget.keyword
        default_name = f"{keyword}_뉴스_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fname, _ = dialogs.get_save_file_name(
            self,
            "데이터 내보내기",
            default_name,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return

        scope_builder = getattr(cur_widget, "_build_query_scope", None)
        if callable(scope_builder):
            self._start_export_job(scope_builder(), keyword, fname)
            return

        visible_items = list(getattr(cur_widget, "filtered_data_cache", []))
        if not visible_items:
            dialogs.information(self, "알림", "내보낼 뉴스가 없습니다.")
            return

        try:
            result = export_items_to_csv(visible_items, fname, keyword)
        except Exception as e:
            dialogs.warning(self, "오류", f"내보내기 중 오류가 발생했습니다:\n{e}")
            return

        self.show_success_toast(f"총 {int(result.get('count', 0) or 0)}개 항목을 저장했습니다.")
        dialogs.information(self, "완료", f"파일이 저장되었습니다:\n{result['path']}")

    def _start_export_job(
        self: MainApp,
        scope: DBQueryScope,
        keyword: str,
        output_path: str,
    ) -> None:
        self._export_target_path = str(output_path or "")
        self._export_cancel_requested = False
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.btn_save.setText("⏹ 내보내기 취소")
        self.btn_save.setEnabled(True)
        self._status_bar().showMessage("CSV 내보내기를 시작합니다...")

        worker = IterativeJobWorker(
            export_scope_to_csv,
            self._require_db(),
            scope,
            output_path,
            keyword,
            EXPORT_CHUNK_SIZE,
        )
        self._export_worker = worker
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_finished)
        worker.error.connect(self._on_export_error)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        worker.start()

    def _cancel_export_job(self: MainApp) -> None:
        worker = getattr(self, "_export_worker", None)
        if worker is None or not worker.isRunning():
            return
        self._export_cancel_requested = True
        self.btn_save.setEnabled(False)
        self.btn_save.setText("⏳ 취소 중...")
        self._status_bar().showMessage("CSV 내보내기 취소 요청 중...")
        worker.requestInterruption()

    def _reset_export_ui(self: MainApp) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_save.setText("💾 내보내기")
        self.btn_save.setEnabled(True)
        self._export_worker = None
        self._export_target_path = ""
        self._export_cancel_requested = False

    def _on_export_progress(self: MainApp, payload: Dict[str, Any]) -> None:
        current = int(payload.get("current", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        message = str(payload.get("message", "") or "")
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(min(current, total))
        else:
            self.progress.setRange(0, 0)
        if message:
            self._status_bar().showMessage(message)

    def _on_export_finished(self: MainApp, result: Dict[str, Any]) -> None:
        exported_count = int(result.get("count", 0) or 0)
        target_path = str(result.get("path", "") or self._export_target_path)
        self._reset_export_ui()
        self.show_success_toast(f"총 {exported_count}개 항목을 저장했습니다.")
        self._status_bar().showMessage(f"CSV 내보내기 완료 ({exported_count}개)", 4000)
        _dialogs_for(self).information(self, "완료", f"파일이 저장되었습니다:\n{target_path}")

    def _on_export_error(self: MainApp, error_msg: str) -> None:
        self._reset_export_ui()
        _dialogs_for(self).warning(self, "오류", f"내보내기 중 오류가 발생했습니다:\n{error_msg}")

    def _on_export_cancelled(self: MainApp) -> None:
        self._reset_export_ui()
        self._status_bar().showMessage("CSV 내보내기를 취소했습니다.", 3000)
        self.show_warning_toast("CSV 내보내기를 취소했습니다.")

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
            imported_new_keywords: List[str] = []
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
                    imported_new_keywords.append(normalized_keyword)
                    new_tabs += 1
                elif not normalized_keyword:
                    skipped_invalid_tabs += 1

            imported_groups = import_data.get("keyword_groups", {})
            if isinstance(imported_groups, dict):
                previous_groups = dict(getattr(self.keyword_group_manager, "groups", {}))
                merged_groups = self.keyword_group_manager.merge_groups(imported_groups, save=True)
                group_manager = self.keyword_group_manager
                group_manager_error = str(getattr(group_manager, "last_error", "") or "")
                if (
                    group_manager_error
                    and merged_groups == previous_groups
                ):
                    group_warning = (
                        "키워드 그룹을 저장하지 못해 가져온 그룹 설정을 적용하지 못했습니다.\n\n"
                        f"{group_manager_error}"
                    )
                    import_warnings.append(group_warning)
                    dialogs.warning(self, "그룹 저장 실패", group_warning)

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
            self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
            for _index, widget in self._iter_news_tabs():
                widget.theme = self.theme_idx
                widget.render_html()

        self.apply_refresh_interval()
        self.save_config()
        self.show_success_toast("설정을 저장했습니다.")
