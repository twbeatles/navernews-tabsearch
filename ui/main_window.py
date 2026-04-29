import csv
from collections import deque
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
from functools import partial
from typing import Any, Dict, Optional

from PyQt6.QtCore import QMutex, QTimer
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from core.backup import (
    AutoBackup as CoreAutoBackup,
    PENDING_RESTORE_FILENAME as CORE_PENDING_RESTORE_FILENAME,
    apply_pending_restore_if_any as core_apply_pending_restore_if_any,
)
from core.constants import (
    CONFIG_FILE,
    DB_FILE,
    PENDING_RESTORE_FILE as CORE_PENDING_RESTORE_FILE,
    RUNTIME_PATHS,
    RuntimePaths,
    VERSION,
)
from core.database import DatabaseManager
from core.http_client import HttpClientConfig
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.worker_registry import WorkerRegistry
from core.workers import IterativeJobWorker
from ui._main_window_analysis import _MainWindowAnalysisMixin
from ui._main_window_fetch import _MainWindowFetchMixin
from ui._main_window_settings_io import _MainWindowSettingsIOMixin
from ui._main_window_tabs import _MainWindowTabsMixin
from ui._main_window_tray import _MainWindowTrayMixin
from ui.main_window_support import (
    TabFetchState,
    _MainWindowBaseMixin,
    _MainWindowConfigMixin,
    _MainWindowUIShellMixin,
)
from ui.toast import ToastQueue

configure_logging()
logger = logging.getLogger(__name__)

PENDING_RESTORE_FILENAME = CORE_PENDING_RESTORE_FILENAME
PENDING_RESTORE_FILE = CORE_PENDING_RESTORE_FILE


class AutoBackup(CoreAutoBackup):
    def __init__(
        self,
        config_file: Optional[str] = None,
        db_file: Optional[str] = None,
        runtime_paths: Optional[RuntimePaths] = None,
        pending_restore_file: Optional[str] = None,
    ):
        resolved_runtime_paths = runtime_paths or RUNTIME_PATHS
        super().__init__(
            config_file=config_file or resolved_runtime_paths.config_file,
            db_file=db_file or resolved_runtime_paths.db_file,
            app_version=VERSION,
            pending_restore_file=pending_restore_file or resolved_runtime_paths.pending_restore_file,
        )


def apply_pending_restore_if_any(
    pending_file: str = PENDING_RESTORE_FILE,
    config_file: str = CONFIG_FILE,
    db_file: str = DB_FILE,
) -> bool:
    return core_apply_pending_restore_if_any(
        pending_file=pending_file,
        config_file=config_file,
        db_file=db_file,
    )


def should_start_minimized(start_requested: bool, tray_available: bool) -> bool:
    """트레이 사용 가능할 때만 시작 최소화 적용."""
    return bool(start_requested and tray_available)


class MainApp(
    _MainWindowTabsMixin,
    _MainWindowFetchMixin,
    _MainWindowSettingsIOMixin,
    _MainWindowTrayMixin,
    _MainWindowAnalysisMixin,
    _MainWindowBaseMixin,
    _MainWindowConfigMixin,
    _MainWindowUIShellMixin,
    QMainWindow,
):
    """메인 애플리케이션 윈도우 - 안정성 개선 버전"""

    def __init__(self, runtime_paths: Optional[RuntimePaths] = None):
        super().__init__()
        self.runtime_paths = runtime_paths or RUNTIME_PATHS
        os.makedirs(self.runtime_paths.data_dir, exist_ok=True)
        if not os.path.exists(self.runtime_paths.log_file):
            try:
                with open(self.runtime_paths.log_file, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass

        logger.info("MainApp 초기화 시작")

        self._system_shutdown = False
        self._user_requested_close = False
        self._force_close = False
        self._shutdown_in_progress = False

        self.client_id = ""
        self.client_secret = ""
        self.toast_queue: Optional[ToastQueue] = None
        self.db: Optional[DatabaseManager] = None
        self.http_client_config: Optional[HttpClientConfig] = None

        try:
            self.db = DatabaseManager(self.runtime_paths.db_file)

            self.http_client_config = HttpClientConfig()

            self.workers = {}
            self._worker_registry = WorkerRegistry()
            self._worker_request_seq = 0
            self.toast_queue = ToastQueue(self)

            self._refresh_in_progress = False
            self._refresh_queue = []
            self._refresh_mutex = QMutex()
            self._last_refresh_time = None
            self._maintenance_mode = False
            self._maintenance_reason = ""

            self._pending_refresh_keywords = []
            self._sequential_refresh_active = False
            self._current_refresh_idx = 0
            self._total_refresh_count = 0
            self._sequential_new_count = 0
            self._sequential_added_count = 0
            self._sequential_dup_count = 0
            self._last_fetch_request_ts: Dict[str, float] = {}
            self._fetch_dedupe_window_sec = 10.0
            self._badge_unread_cache: Dict[str, int] = {}
            self._badge_refresh_running = False
            self._tab_fetch_state: Dict[str, TabFetchState] = {}
            self._fetch_cursor_by_key: Dict[str, int] = {}
            self._fetch_total_by_key: Dict[str, int] = {}
            self._last_auto_refresh_by_keyword: Dict[str, float] = {}
            self._request_start_index: Dict[int, int] = {}
            self._query_key_migration_hints_shown: set[str] = set()
            self._export_worker: Optional[IterativeJobWorker] = None
            self._export_target_path = ""
            self._export_cancel_requested = False
            self._fts_backfill_worker: Optional[IterativeJobWorker] = None
            self._fts_backfill_retry_attempt = 0
            self._fts_backfill_pause_requested = False
            self._fts_backfill_pause_delay_ms = 1000
            self._fts_backfill_retry_timer = QTimer(self)
            self._fts_backfill_retry_timer.setSingleShot(True)
            self._fts_backfill_retry_timer.timeout.connect(self._start_fts_backfill)
            self._fetch_cooldown_until = 0.0
            self._fetch_cooldown_reason = ""
            self._tab_hydration_queue: deque[str] = deque()
            self._hydration_inflight_keyword = ""
            self._hydration_timer = QTimer(self)
            self._hydration_timer.setSingleShot(True)
            self._hydration_timer.timeout.connect(self._process_tab_hydration)

            self.notification_enabled = True
            self.alert_keywords = []
            self.sound_enabled = True
            self.notify_on_refresh = False

            self.keyword_group_manager = KeywordGroupManager(
                self.runtime_paths.config_file,
                legacy_file=self.runtime_paths.keyword_groups_file,
            )
            self.auto_backup = AutoBackup(runtime_paths=self.runtime_paths)
            self.search_history = []

            self._network_error_count = 0
            self._max_network_errors = 3
            self._network_available = True
            self._sequential_refresh_is_auto = False

            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._update_countdown)
            self._next_refresh_seconds = 0

            self.set_application_icon()

            self.load_config()
            self.init_ui()
            self.setup_shortcuts()
            QTimer.singleShot(0, self._start_fts_backfill)

            self.timer = QTimer(self)
            self.timer.timeout.connect(self._safe_refresh_all)
            self.apply_refresh_interval()

            if self.client_id and self.tabs.count() > 1:
                QTimer.singleShot(1000, self._safe_refresh_all)

            self._tab_badge_timer = QTimer(self)
            self._tab_badge_timer.timeout.connect(self.update_all_tab_badges)
            self._tab_badge_timer.start(30000)
            self._badge_refresh_timer = QTimer(self)
            self._badge_refresh_timer.setSingleShot(True)
            self._badge_refresh_timer.timeout.connect(self.update_all_tab_badges)

            QTimer.singleShot(500, self._check_first_run)

            if os.path.exists(self.runtime_paths.config_file):
                QTimer.singleShot(
                    2000,
                    lambda: self.auto_backup.create_backup(include_db=False, trigger="auto"),
                )

            self.setup_system_tray()

            start_minimized_requested = "--minimized" in sys.argv or self.config.get("start_minimized", False)
            tray_available = bool(getattr(self, "tray", None))
            if should_start_minimized(start_minimized_requested, tray_available):
                QTimer.singleShot(100, self.hide)
            elif start_minimized_requested and not tray_available:
                logger.warning("트레이 미지원 환경: 시작 최소화 요청을 무시합니다.")
                QTimer.singleShot(
                    150,
                    lambda: self._status_bar().showMessage(
                        "⚠ 트레이를 사용할 수 없어 최소화 시작이 적용되지 않았습니다.",
                        5000,
                    ),
                )
                QTimer.singleShot(
                    200,
                    lambda: self.show_warning_toast("트레이 미지원 환경에서는 최소화 시작을 사용할 수 없습니다."),
                )

            logger.info("MainApp 초기화 완료")
        except Exception as exc:
            logger.critical("MainApp 초기화 중 치명적 오류: %s", exc)
            traceback.print_exc()
            QMessageBox.critical(None, "초기화 오류", f"프로그램 초기화 중 오류가 발생했습니다:\n{exc}")
            raise


__all__ = [
    "AutoBackup",
    "IterativeJobWorker",
    "MainApp",
    "PENDING_RESTORE_FILE",
    "PENDING_RESTORE_FILENAME",
    "TabFetchState",
    "apply_pending_restore_if_any",
    "should_start_minimized",
]
