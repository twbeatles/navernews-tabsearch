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

class _MainWindowCloudSyncMixin:
    def _cloud_sync_block_reason(
        self: MainApp,
        *,
        require_folder: bool = True,
        sync_dir_override: Optional[str] = None,
        enabled_override: Optional[bool] = None,
    ) -> str:
        enabled = bool(getattr(self, "cloud_sync_enabled", True)) if enabled_override is None else bool(enabled_override)
        if not enabled:
            return "클라우드 동기화가 꺼져 있습니다."
        sync_dir = (
            str(getattr(self, "cloud_sync_dir", "") or "").strip()
            if sync_dir_override is None
            else str(sync_dir_override or "").strip()
        )
        if require_folder and not sync_dir:
            return "클라우드 동기화 폴더가 선택되지 않았습니다."
        if runtime_storage_is_probably_cloud(self.runtime_paths):
            return "실시간 DATA_DIR/DB가 클라우드 동기화 폴더 안에 있는 것으로 보입니다. 먼저 로컬 폴더로 옮겨 주세요."
        if sync_dir and cloud_sync_path_conflicts_with_runtime(sync_dir, self.runtime_paths):
            return "클라우드 동기화 폴더가 실시간 런타임 데이터 폴더와 겹칩니다."
        if self.is_maintenance_mode_active():
            return "데이터베이스 유지보수 작업이 이미 실행 중입니다."
        if getattr(self, "_refresh_in_progress", False) or getattr(self, "_sequential_refresh_active", False):
            return "새로고침이 실행 중이라 이번 클라우드 동기화는 건너뜁니다."
        if getattr(self, "_cloud_sync_worker", None) is not None:
            return "클라우드 동기화가 이미 실행 중입니다."
        return ""
    def apply_cloud_sync_settings(self: MainApp) -> None:
        timer = getattr(self, "_cloud_sync_timer", None)
        if timer is None:
            return
        timer.stop()
        interval_minutes = int(getattr(self, "cloud_sync_interval_minutes", 30) or 30)
        interval_minutes = interval_minutes if interval_minutes in {10, 30, 60, 120, 360} else 30
        self.cloud_sync_interval_minutes = interval_minutes
        if self._cloud_sync_block_reason(require_folder=True):
            return
        timer.setInterval(interval_minutes * 60 * 1000)
        timer.start()
    def run_cloud_sync_now(
        self: MainApp,
        *,
        sync_dir_override: Optional[str] = None,
        enabled_override: Optional[bool] = None,
        interval_override: Optional[int] = None,
    ) -> None:
        self._run_cloud_sync_once(
            manual=True,
            mode="full",
            sync_dir_override=sync_dir_override,
            enabled_override=enabled_override,
            interval_override=interval_override,
        )
    def run_cloud_sync_export_now(
        self: MainApp,
        *,
        sync_dir_override: Optional[str] = None,
        enabled_override: Optional[bool] = None,
        interval_override: Optional[int] = None,
    ) -> None:
        self._run_cloud_sync_once(
            manual=True,
            mode="export",
            sync_dir_override=sync_dir_override,
            enabled_override=enabled_override,
            interval_override=interval_override,
        )
    def run_cloud_sync_import_now(
        self: MainApp,
        *,
        sync_dir_override: Optional[str] = None,
        enabled_override: Optional[bool] = None,
        interval_override: Optional[int] = None,
    ) -> None:
        self._run_cloud_sync_once(
            manual=True,
            mode="import",
            sync_dir_override=sync_dir_override,
            enabled_override=enabled_override,
            interval_override=interval_override,
        )
    def _run_cloud_sync_once(
        self: MainApp,
        *,
        manual: bool = False,
        mode: str = "full",
        sync_dir_override: Optional[str] = None,
        enabled_override: Optional[bool] = None,
        interval_override: Optional[int] = None,
    ) -> None:
        mode = str(mode or "full").strip().lower()
        if mode not in {"full", "export", "import"}:
            mode = "full"
        block_reason = self._cloud_sync_block_reason(
            require_folder=True,
            sync_dir_override=sync_dir_override,
            enabled_override=enabled_override,
        )
        if block_reason:
            self._cloud_sync_last_status = block_reason
            if manual:
                self.show_warning_toast(block_reason)
                _dialogs_for(self).warning(self, "클라우드 동기화", block_reason)
            return

        ok, reason = self.begin_database_maintenance("cloud_sync")
        if not ok:
            self._cloud_sync_last_status = reason
            if manual:
                self.show_warning_toast(reason)
            return

        sync_dir = (
            str(getattr(self, "cloud_sync_dir", "") or "").strip()
            if sync_dir_override is None
            else str(sync_dir_override or "").strip()
        )
        config_payload = self._build_runtime_config_payload()
        db_file = self.runtime_paths.db_file
        machine_id = get_machine_identity()
        app_version = VERSION
        interval_minutes = (
            int(getattr(self, "cloud_sync_interval_minutes", 30) or 30)
            if interval_override is None
            else int(interval_override or 30)
        )

        def _job(context):
            context.report(current=0, total=0, message="클라우드 동기화 시작")
            if mode == "export":
                snapshot = create_cloud_snapshot(
                    sync_dir=sync_dir,
                    config=config_payload,
                    db_file=db_file,
                    machine_id=machine_id,
                    app_version=app_version,
                )
                self._require_db().mark_cloud_sync_snapshot_seen(snapshot.snapshot_id)
                cleanup_old_snapshots(sync_dir, keep=100)
                return {"mode": mode, "exported": snapshot, "imported": [], "errors": []}
            if mode == "import":
                imported = []
                errors = []
                selection = select_cloud_snapshots_for_import(
                    db_manager=self._require_db(),
                    sync_dir=sync_dir,
                    max_imports=20,
                )
                errors.extend(selection["errors"])
                invalid_count = len(selection["errors"])
                for zip_path in selection["paths"]:
                    context.check_cancelled()
                    try:
                        imported.append(
                            import_cloud_snapshot(
                                db_manager=self._require_db(),
                                zip_path=zip_path,
                                local_machine_id=machine_id,
                            )
                        )
                    except Exception as exc:
                        errors.append(f"{os.path.basename(zip_path)}: {exc}")
                        invalid_count += 1
                cleanup_old_snapshots(sync_dir, keep=100)
                return {
                    "mode": mode,
                    "exported": None,
                    "imported": imported,
                    "errors": errors,
                    "invalid_count": invalid_count,
                    "pending_unseen": selection.get("pending_unseen", 0),
                    "skipped_seen": selection.get("skipped_seen", 0),
                    "interval_minutes": interval_minutes,
                }
            result = run_cloud_sync_cycle(
                db_manager=self._require_db(),
                sync_dir=sync_dir,
                config=config_payload,
                db_file=db_file,
                machine_id=machine_id,
                app_version=app_version,
                max_imports=20,
            )
            result["mode"] = mode
            result["interval_minutes"] = interval_minutes
            return result

        worker_cls = getattr(self, "_iterative_job_worker_cls", lambda: IterativeJobWorker)()
        worker = worker_cls(_job, parent=self)
        self._cloud_sync_worker = worker
        worker.finished.connect(self._on_cloud_sync_finished)
        worker.error.connect(self._on_cloud_sync_error)
        worker.cancelled.connect(self._on_cloud_sync_cancelled)
        delete_qthread_when_finished(worker)
        worker.start()
    def _finish_cloud_sync_worker(self: MainApp) -> None:
        self._cloud_sync_worker = None
        self.end_database_maintenance()
        self.apply_cloud_sync_settings()
    def _on_cloud_sync_finished(self: MainApp, result: Dict[str, Any]) -> None:
        imported = list(result.get("imported", []) or [])
        errors = list(result.get("errors", []) or [])
        merged = [item for item in imported if bool(item.get("merged", False))]
        news_added = sum(int(item.get("news_added", 0) or 0) for item in merged)
        memberships_added = sum(int(item.get("memberships_added", 0) or 0) for item in merged)
        exported = result.get("exported")
        exported_text = "내보냄" if exported else "내보내기 없음"
        status = (
            f"클라우드 동기화 완료: {exported_text}, "
            f"병합 {len(merged)}개, 기사 +{news_added}, 검색범위 +{memberships_added}"
        )
        invalid_count = int(result.get("invalid_count", 0) or 0)
        pending_unseen = int(result.get("pending_unseen", 0) or 0)
        if invalid_count:
            status += f", 무시한 스냅샷 {invalid_count}개"
        if pending_unseen:
            status += f", 대기 {pending_unseen}개"
        if errors:
            status += f", 오류 {len(errors)}건"
            logger.warning("Cloud sync import errors:\n- %s", "\n- ".join(errors))
        self._cloud_sync_last_status = status
        self._finish_cloud_sync_worker()
        if merged:
            self.on_database_maintenance_completed("cloud_sync", news_added + memberships_added)
        self.show_success_toast(status)
    def _on_cloud_sync_error(self: MainApp, error_msg: str) -> None:
        self._cloud_sync_last_status = f"클라우드 동기화 실패: {error_msg}"
        self._finish_cloud_sync_worker()
        self.show_error_toast(self._cloud_sync_last_status)
    def _on_cloud_sync_cancelled(self: MainApp) -> None:
        self._cloud_sync_last_status = "클라우드 동기화가 취소되었습니다."
        self._finish_cloud_sync_worker()
        self.show_warning_toast(self._cloud_sync_last_status)
