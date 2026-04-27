# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTimer

from core.config_store import AppConfig, encode_client_secret_for_storage, normalize_import_settings, save_primary_config_file
from core.constants import CONFIG_FILE, RUNTIME_PATHS, VERSION
from core.content_filters import normalize_name_list
from core.keyword_groups import merge_keyword_groups
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
        str(item.get("tags", "") or ""),
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
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복", "태그"])
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
    try:
        context.report(current=0, total=total_count, message="내보내기 준비 중...", payload={"stage": "count"})
        context.check_cancelled()

        if total_count <= 0:
            raise ValueError("내보낼 뉴스가 없습니다.")
    except Exception:
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
        raise

    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복", "태그"])

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
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
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
            "blocked_publishers": getattr(self, "blocked_publishers", []),
            "preferred_publishers": getattr(self, "preferred_publishers", []),
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
                if widget.needs_initial_hydration():
                    self._enqueue_tab_hydration(widget.keyword, prioritize=False)
                    continue
                widget.load_data_from_db()
            self._schedule_badge_refresh(delay_ms=0)
            self.update_tray_tooltip()
            QTimer.singleShot(300, self.update_tray_tooltip)
            self._schedule_tab_hydration(25)
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
                "blocked_publishers": normalize_name_list(
                    app_settings_overrides.get("blocked_publishers", getattr(self, "blocked_publishers", []))
                ),
                "preferred_publishers": normalize_name_list(
                    app_settings_overrides.get("preferred_publishers", getattr(self, "preferred_publishers", []))
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
            "tab_refresh_policies": dict(
                tab_refresh_policies
                if tab_refresh_policies is not None
                else getattr(self, "tab_refresh_policies", {})
            ),
        }

    def _compute_imported_new_tabs(
        self: MainApp,
        imported_tabs: Any,
    ) -> Tuple[List[str], int]:
        existing_fetch_keys = {
            self._canonical_fetch_key_for_keyword(tab.keyword)
            for _index, tab in self._iter_news_tabs(start_index=1)
            if self._canonical_fetch_key_for_keyword(tab.keyword)
        }
        imported_new_keywords: List[str] = []
        skipped_invalid_tabs = 0
        for keyword in imported_tabs if isinstance(imported_tabs, list) else []:
            normalized_keyword = self._normalize_tab_keyword(keyword.strip()) if isinstance(keyword, str) else None
            normalized_fetch_key = (
                self._canonical_fetch_key_for_keyword(normalized_keyword)
                if normalized_keyword
                else ""
            )
            if normalized_keyword and normalized_fetch_key and normalized_fetch_key not in existing_fetch_keys:
                existing_fetch_keys.add(normalized_fetch_key)
                imported_new_keywords.append(normalized_keyword)
            elif not normalized_keyword:
                skipped_invalid_tabs += 1
        return imported_new_keywords, skipped_invalid_tabs

    def _merge_imported_keyword_groups(
        self: MainApp,
        imported_groups: Any,
    ) -> Dict[str, List[str]]:
        group_manager = self.keyword_group_manager
        normalize_groups = getattr(group_manager, "_normalize_groups", None)
        existing_groups = dict(getattr(group_manager, "groups", {}))
        if callable(normalize_groups):
            normalized_existing = normalize_groups(existing_groups)
            normalized_incoming = normalize_groups(imported_groups if isinstance(imported_groups, dict) else {})
        else:
            normalized_existing = existing_groups
            normalized_incoming = imported_groups if isinstance(imported_groups, dict) else {}
        return merge_keyword_groups(normalized_existing, normalized_incoming)

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
            "api_timeout": self.api_timeout,
            "blocked_publishers": list(getattr(self, "blocked_publishers", [])),
            "preferred_publishers": list(getattr(self, "preferred_publishers", [])),
            "saved_searches": dict(getattr(self, "saved_searches", {})),
            "tab_refresh_policies": dict(getattr(self, "tab_refresh_policies", {})),
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
        self.api_timeout = int(runtime_snapshot["api_timeout"])
        self.blocked_publishers = list(runtime_snapshot["blocked_publishers"])
        self.preferred_publishers = list(runtime_snapshot["preferred_publishers"])
        self.saved_searches = dict(runtime_snapshot["saved_searches"])
        self.tab_refresh_policies = dict(runtime_snapshot["tab_refresh_policies"])
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
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        for _index, widget in self._iter_news_tabs():
            widget.theme = self.theme_idx
            widget.render_html()
        self.apply_refresh_interval()

    def _apply_import_runtime_stage(
        self: MainApp,
        stage: Dict[str, Any],
    ) -> List[str]:
        normalized_settings = dict(stage["normalized_settings"])
        imported_geometry = stage.get("imported_geometry")
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
        self.blocked_publishers = normalize_name_list(normalized_settings["blocked_publishers"])
        self.preferred_publishers = normalize_name_list(normalized_settings["preferred_publishers"])
        self.saved_searches = dict(stage["staged_config"].get("saved_searches", {}))
        self.tab_refresh_policies = dict(stage["staged_config"].get("tab_refresh_policies", {}))
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
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        for _index, widget in self._iter_news_tabs():
            widget.theme = self.theme_idx
            widget.render_html()
        added_keywords = stage.setdefault("applied_new_keywords", [])
        added_keywords.clear()
        for keyword in stage["imported_new_keywords"]:
            self.add_news_tab(keyword)
            added_keywords.append(keyword)
        self.keyword_group_manager.groups = dict(stage["merged_keyword_groups"])
        self.keyword_group_manager.last_error = ""
        self.apply_refresh_interval()
        return added_keywords

    def _stage_settings_import(
        self: MainApp,
        import_data: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            "blocked_publishers": getattr(self, "blocked_publishers", []),
            "preferred_publishers": getattr(self, "preferred_publishers", []),
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
        merged_keyword_groups = self._merge_imported_keyword_groups(import_data.get("keyword_groups", {}))
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
                "api_timeout": normalized_settings["api_timeout"],
                "blocked_publishers": normalized_settings["blocked_publishers"],
                "preferred_publishers": normalized_settings["preferred_publishers"],
            },
            tab_keywords=[
                tab.keyword
                for _index, tab in self._iter_news_tabs(start_index=1)
            ] + imported_new_keywords,
            search_history=merged_search_history,
            keyword_groups=merged_keyword_groups,
            pagination_state=merged_pagination_state,
            pagination_totals=merged_pagination_totals,
            saved_searches=import_data.get("saved_searches", getattr(self, "saved_searches", {})),
            tab_refresh_policies=import_data.get(
                "tab_refresh_policies",
                getattr(self, "tab_refresh_policies", {}),
            ),
            window_geometry=imported_geometry,
        )
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
        }

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
                "blocked_publishers": getattr(self, "blocked_publishers", []),
                "preferred_publishers": getattr(self, "preferred_publishers", []),
            },
            "tabs": [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)],
            "keyword_groups": self.keyword_group_manager.groups,
            "search_history": self.search_history,
            "pagination_state": self._fetch_cursor_by_key,
            "pagination_totals": self._fetch_total_by_key,
            "saved_searches": getattr(self, "saved_searches", {}),
            "tab_refresh_policies": getattr(self, "tab_refresh_policies", {}),
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
        self.blocked_publishers = normalize_name_list(data.get("blocked_publishers", []))
        self.preferred_publishers = normalize_name_list(data.get("preferred_publishers", []))

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
        for _index, widget in self._iter_news_tabs():
            widget.load_data_from_db()
        self.show_success_toast("설정을 저장했습니다.")
