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
from core.validation import ValidationUtils
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

from ui.main_window_io_support.exports import (
    _dialogs_for,
    export_items_to_csv,
    export_items_to_markdown,
    export_scope_to_csv,
    export_scope_to_markdown,
    import_bookmarks_notes_from_csv,
)

class _MainWindowDataIOMixin:
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
                refresh_tags = getattr(widget, "_refresh_tag_filter_options", None)
                if callable(refresh_tags):
                    refresh_tags()
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
        """Export the current tab's rows as CSV or Markdown."""
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
        safe_keyword = ValidationUtils.safe_filename_component(keyword, fallback="news")
        default_name = f"{safe_keyword}_뉴스_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fname, _ = dialogs.get_save_file_name(
            self,
            "데이터 내보내기",
            default_name,
            "CSV Files (*.csv);;Markdown Digest (*.md);;All Files (*)",
        )
        if not fname:
            return
        export_format = "markdown" if str(fname).lower().endswith(".md") else "csv"

        scope_builder = getattr(cur_widget, "_build_query_scope", None)
        if callable(scope_builder):
            try:
                self._start_export_job(scope_builder(), keyword, fname, export_format=export_format)
            except TypeError as exc:
                if "export_format" not in str(exc):
                    raise
                self._start_export_job(scope_builder(), keyword, fname)
            return

        visible_items = list(getattr(cur_widget, "filtered_data_cache", []))
        if not visible_items:
            dialogs.information(self, "알림", "내보낼 뉴스가 없습니다.")
            return

        try:
            if export_format == "markdown":
                result = export_items_to_markdown(
                    visible_items,
                    fname,
                    keyword,
                    publisher_aliases=getattr(self, "publisher_aliases", {}),
                )
            else:
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
        *,
        export_format: str = "csv",
    ) -> None:
        self._export_target_path = str(output_path or "")
        self._export_cancel_requested = False
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.btn_save.setText("⏹ 내보내기 취소")
        self.btn_save.setEnabled(True)
        export_format = "markdown" if str(export_format).lower() == "markdown" else "csv"
        label = "Markdown" if export_format == "markdown" else "CSV"
        self._status_bar().showMessage(f"{label} 내보내기를 시작합니다...")

        job_fn = export_scope_to_markdown if export_format == "markdown" else export_scope_to_csv
        job_args = (
            self._require_db(),
            scope,
            output_path,
            keyword,
            EXPORT_CHUNK_SIZE,
        )
        worker = IterativeJobWorker(
            job_fn,
            *job_args,
            **(
                {"publisher_aliases": getattr(self, "publisher_aliases", {})}
                if export_format == "markdown"
                else {}
            ),
        )
        self._export_worker = worker
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_finished)
        worker.error.connect(self._on_export_error)
        worker.cancelled.connect(self._on_export_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()
    def _cancel_export_job(self: MainApp) -> None:
        worker = getattr(self, "_export_worker", None)
        if worker is None or not worker.isRunning():
            return
        self._export_cancel_requested = True
        self.btn_save.setEnabled(False)
        self.btn_save.setText("⏳ 취소 중...")
        self._status_bar().showMessage("내보내기 취소 요청 중...")
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
        fmt = str(result.get("format", "csv") or "csv")
        label = "Markdown" if fmt == "markdown" else "CSV"
        self._status_bar().showMessage(f"{label} 내보내기 완료 ({exported_count}개)", 4000)
        _dialogs_for(self).information(self, "완료", f"파일이 저장되었습니다:\n{target_path}")
    def _on_export_error(self: MainApp, error_msg: str) -> None:
        self._reset_export_ui()
        _dialogs_for(self).warning(self, "오류", f"내보내기 중 오류가 발생했습니다:\n{error_msg}")
    def _on_export_cancelled(self: MainApp) -> None:
        self._reset_export_ui()
        self._status_bar().showMessage("내보내기를 취소했습니다.", 3000)
        self.show_warning_toast("내보내기를 취소했습니다.")
    def import_csv_bookmarks_notes(self: MainApp) -> None:
        """Import bookmark/note state for existing article links only."""
        dialogs = _dialogs_for(self)
        csv_worker = getattr(self, "_csv_import_worker", None)
        if csv_worker is not None and csv_worker.isRunning():
            dialogs.information(self, "CSV 가져오기", "이미 CSV 가져오기가 진행 중입니다.")
            return
        export_worker = getattr(self, "_export_worker", None)
        if export_worker is not None and export_worker.isRunning():
            dialogs.warning(self, "CSV 가져오기", "CSV 내보내기가 끝난 뒤 다시 시도하세요.")
            return

        fname, _ = dialogs.get_open_file_name(
            self,
            "CSV 메모/북마크 가져오기",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return

        started = True
        reason = ""
        begin_maintenance = getattr(self, "begin_database_maintenance", None)
        if callable(begin_maintenance):
            try:
                started, reason = begin_maintenance("csv_import")
            except Exception as exc:
                started = False
                reason = str(exc)
        if not started:
            dialogs.warning(self, "CSV 가져오기", reason or "현재 DB 작업이 진행 중이라 CSV 가져오기를 시작할 수 없습니다.")
            return

        self._csv_import_maintenance_active = callable(begin_maintenance)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self._status_bar().showMessage("CSV 가져오기를 시작합니다...")

        worker = IterativeJobWorker(
            import_bookmarks_notes_from_csv,
            self._require_db(),
            fname,
            EXPORT_CHUNK_SIZE,
        )
        self._csv_import_worker = worker
        worker.progress.connect(self._on_csv_import_progress)
        worker.finished.connect(self._on_csv_import_finished)
        worker.error.connect(self._on_csv_import_error)
        worker.cancelled.connect(self._on_csv_import_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()
    def _finish_csv_import_ui(self: MainApp) -> None:
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._csv_import_worker = None
        if bool(getattr(self, "_csv_import_maintenance_active", False)):
            try:
                self.end_database_maintenance()
            except Exception:
                pass
        self._csv_import_maintenance_active = False
    def _on_csv_import_progress(self: MainApp, payload: Dict[str, Any]) -> None:
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
    def _on_csv_import_finished(self: MainApp, result: Dict[str, Any]) -> None:
        processed = int(result.get("processed", 0) or 0)
        updated = int(result.get("updated", 0) or 0)
        missing = int(result.get("missing", 0) or 0)
        truncated_notes = int(result.get("truncated_notes", 0) or 0)
        self._finish_csv_import_ui()
        suffix = f" / 긴 메모 잘림 {truncated_notes}개" if truncated_notes else ""
        self._status_bar().showMessage(f"CSV 가져오기 완료: 갱신 {updated}개 / 건너뜀 {missing}개{suffix}", 5000)
        self.show_success_toast(f"CSV 가져오기 완료: {updated}개 기사 갱신")
        self.on_database_maintenance_completed("csv_import", updated)
        _dialogs_for(self).information(
            self,
            "CSV 가져오기 완료",
            f"처리 행: {processed:,}개\n기존 기사 갱신: {updated:,}개\n건너뜀: {missing:,}개"
            + (f"\n10,000자를 넘겨 잘린 메모: {truncated_notes:,}개" if truncated_notes else ""),
        )
    def _on_csv_import_error(self: MainApp, error_msg: str) -> None:
        self._finish_csv_import_ui()
        self._status_bar().showMessage("CSV 가져오기에 실패했습니다.", 4000)
        _dialogs_for(self).warning(self, "CSV 가져오기 오류", f"CSV 가져오기 중 오류가 발생했습니다:\n{error_msg}")
    def _on_csv_import_cancelled(self: MainApp) -> None:
        self._finish_csv_import_ui()
        self._status_bar().showMessage("CSV 가져오기를 취소했습니다.", 3000)
        self.show_warning_toast("CSV 가져오기를 취소했습니다.")
