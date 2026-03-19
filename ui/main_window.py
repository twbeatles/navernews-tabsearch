import csv
from dataclasses import dataclass
import html
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
from collections import deque
from datetime import datetime
from functools import partial
from typing import Any, Dict, Iterator, List, Optional, Tuple, cast

import requests
from requests.adapters import HTTPAdapter

from PyQt6.QtCore import QEvent, QMutex, QMutexLocker, QRect, QThread, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QStatusBar,
    QSystemTrayIcon,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.backup import (
    AutoBackup as CoreAutoBackup,
    PENDING_RESTORE_FILENAME as CORE_PENDING_RESTORE_FILENAME,
    apply_pending_restore_if_any as core_apply_pending_restore_if_any,
)
from core.config_store import (
    AppConfig,
    default_config,
    encode_client_secret_for_storage,
    load_config_file,
    normalize_import_settings,
    resolve_client_secret_for_runtime,
    save_config_file_atomic,
)
from core.constants import (
    APP_DIR,
    APP_NAME,
    CONFIG_FILE,
    DB_FILE,
    ICON_FILE,
    ICON_PNG,
    LOG_FILE,
    VERSION,
)
from core.database import DatabaseManager
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.notifications import NotificationSound
from core.query_parser import (
    build_fetch_key,
    has_positive_keyword,
    parse_search_query,
    parse_tab_query,
)
from core.startup import StartupManager
from core.text_utils import RE_HTML_TAGS, perf_timer
from core.validation import ValidationUtils
from core.worker_registry import WorkerHandle, WorkerRegistry
from core.workers import ApiWorker
from ui.dialogs import BackupDialog, KeywordGroupDialog, LogViewerDialog
from ui._main_window_analysis import _MainWindowAnalysisMixin
from ui._main_window_fetch import _MainWindowFetchMixin
from ui._main_window_settings_io import _MainWindowSettingsIOMixin
from ui._main_window_tabs import _MainWindowTabsMixin
from ui._main_window_tray import _MainWindowTrayMixin
from ui.news_tab import NewsTab
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle, ToastType
from ui.toast import ToastQueue

configure_logging()
logger = logging.getLogger(__name__)

PENDING_RESTORE_FILENAME = CORE_PENDING_RESTORE_FILENAME
PENDING_RESTORE_FILE = os.path.join(APP_DIR, PENDING_RESTORE_FILENAME)


@dataclass
class TabFetchState:
    last_api_start_index: int = 0


class AutoBackup(CoreAutoBackup):
    def __init__(self, config_file: str = CONFIG_FILE, db_file: str = DB_FILE):
        super().__init__(
            config_file=config_file,
            db_file=db_file,
            app_version=VERSION,
            pending_restore_file=PENDING_RESTORE_FILE,
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
    QMainWindow,
):
    """메인 애플리케이션 윈도우 - 안정성 개선 버전"""
    
    def __init__(self):
        super().__init__()
        if not os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    pass
            except Exception:
                pass
        
        logger.info("MainApp 초기화 시작")
        
        # 종료 원인 추적을 위한 플래그 (가장 먼저 초기화)
        self._system_shutdown = False       # Windows 시스템 종료
        self._user_requested_close = False  # 사용자가 종료 요청
        self._force_close = False           # 강제 종료 (확인 다이얼로그 스킵)
        
        # 안전한 초기화를 위해 기본 속성 미리 정의
        self.client_id = ""
        self.client_secret = ""
        self.toast_queue: Optional[ToastQueue] = None
        self.db: Optional[DatabaseManager] = None
        self.session: Optional[requests.Session] = None
        
        try:
            self.db = DatabaseManager(DB_FILE)
            
            # Requests Session 설정 (성능 최적화: 연결 재사용)
            self.session = requests.Session()
            # Connection Pool 크기 증가 (동시 요청 처리)
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            self._require_session().mount('https://', adapter)
            self._require_session().mount('http://', adapter)
            
            self.workers = {}  # legacy compatibility mapping
            self._worker_registry = WorkerRegistry()
            self._worker_request_seq = 0
            self.toast_queue = ToastQueue(self)
            
            # 새로고침 상태 추적 (안정성 개선)
            self._refresh_in_progress = False
            self._refresh_queue = []
            self._refresh_mutex = QMutex()
            self._last_refresh_time = None
            self._maintenance_mode = False
            self._maintenance_reason = ""
            
            # 순차 새로고침 관련 변수 (완전 구현)
            self._pending_refresh_keywords = []
            self._sequential_refresh_active = False
            self._current_refresh_idx = 0
            self._total_refresh_count = 0
            self._sequential_added_count = 0  # 누적 추가 건수
            self._sequential_dup_count = 0    # 누적 중복 건수
            self._last_fetch_request_ts: Dict[str, float] = {}
            self._fetch_dedupe_window_sec = 10.0
            self._badge_unread_cache: Dict[str, int] = {}
            self._badge_refresh_running = False
            self._tab_fetch_state: Dict[str, TabFetchState] = {}
            self._fetch_cursor_by_key: Dict[str, int] = {}
            self._fetch_total_by_key: Dict[str, int] = {}
            self._request_start_index: Dict[int, int] = {}
            self._query_key_migration_hints_shown: set[str] = set()
            
            # 알림 관련 설정
            self.notification_enabled = True  # 데스크톱 알림 활성화
            self.alert_keywords = []  # 알림 키워드 목록
            self.sound_enabled = True  # 알림 소리 활성화
            self.notify_on_refresh = False  # 자동 새로고침 완료 알림 (기본 비활성화)
            
            # 키워드 그룹 관리자
            self.keyword_group_manager = KeywordGroupManager(CONFIG_FILE)
            
            # 자동 백업 관리자
            self.auto_backup = AutoBackup()
            
            # 검색 히스토리 (최근 10개)
            self.search_history = []
            
            # 네트워크 상태 추적
            self._network_error_count = 0  # 연속 네트워크 오류 횟수
            self._max_network_errors = 3   # 연속 오류 허용 횟수
            self._network_available = True  # 네트워크 연결 상태
            
            # 다음 새로고침 카운트다운 타이머
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._update_countdown)
            self._next_refresh_seconds = 0
            
            # 아이콘 설정
            self.set_application_icon()
            
            self.load_config()
            self.init_ui()
            self.setup_shortcuts()
            
            # 타이머 설정 (안정성 개선)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._safe_refresh_all)
            self.apply_refresh_interval()
            
            if self.client_id and self.tabs.count() > 1:
                QTimer.singleShot(1000, self._safe_refresh_all)
            
            
            # 종료 원인 추적 플래그 (상단으로 이동됨)
            
            # 탭 배지 업데이트 타이머 (30초마다)
            self._tab_badge_timer = QTimer(self)
            self._tab_badge_timer.timeout.connect(self.update_all_tab_badges)
            self._tab_badge_timer.start(30000)  # 30초
            self._badge_refresh_timer = QTimer(self)
            self._badge_refresh_timer.setSingleShot(True)
            self._badge_refresh_timer.timeout.connect(self.update_all_tab_badges)
            
            # 첫 실행 가이드 표시
            QTimer.singleShot(500, self._check_first_run)
            
            # 시작 시 자동 백업 (설정 파일이 있으면)
            if os.path.exists(CONFIG_FILE):
                QTimer.singleShot(
                    2000,
                    lambda: self.auto_backup.create_backup(include_db=False, trigger="auto"),
                )
            
            # 시스템 트레이 설정
            self.setup_system_tray()
            
            # 최소화 상태로 시작 옵션 처리
            start_minimized_requested = '--minimized' in sys.argv or self.config.get('start_minimized', False)
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
        except Exception as e:
            logger.critical(f"MainApp 초기화 중 치명적 오류: {e}")
            traceback.print_exc()
            QMessageBox.critical(None, "초기화 오류", f"프로그램 초기화 중 오류가 발생했습니다:\n{e}")
            raise

    def _status_bar(self) -> QStatusBar:
        status_bar = self.statusBar()
        if status_bar is None:
            raise RuntimeError("Status bar is unavailable")
        return status_bar

    def _tab_bar(self) -> QTabBar:
        tab_bar = self.tabs.tabBar()
        if tab_bar is None:
            raise RuntimeError("Tab bar is unavailable")
        return tab_bar

    def _style(self) -> QStyle:
        style = self.style()
        if style is None:
            raise RuntimeError("Widget style is unavailable")
        return style

    def _app_instance(self) -> QApplication:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplication instance is unavailable")
        return app

    def _require_db(self) -> DatabaseManager:
        if self.db is None:
            raise RuntimeError("Database manager is unavailable")
        return self.db

    def _require_session(self) -> requests.Session:
        if self.session is None:
            raise RuntimeError("HTTP session is unavailable")
        return self.session

    def _require_toast_queue(self) -> ToastQueue:
        if self.toast_queue is None:
            raise RuntimeError("Toast queue is unavailable")
        return self.toast_queue

    def _news_tab(self, widget: Optional[QWidget]) -> Optional[NewsTab]:
        return widget if isinstance(widget, NewsTab) else None

    def _news_tab_at(self, index: int) -> Optional[NewsTab]:
        return self._news_tab(self.tabs.widget(index))

    def _current_news_tab(self) -> Optional[NewsTab]:
        return self._news_tab(self.tabs.currentWidget())

    def _iter_news_tabs(self, start_index: int = 0) -> Iterator[tuple[int, NewsTab]]:
        for index in range(start_index, self.tabs.count()):
            tab = self._news_tab_at(index)
            if tab is not None:
                yield index, tab

    def _find_news_tab(self, keyword: str) -> Optional[tuple[int, NewsTab]]:
        for index, tab in self._iter_news_tabs(start_index=1):
            if tab.keyword == keyword:
                return index, tab
        return None

    def sync_link_state_across_tabs(
        self,
        source_tab: Optional[NewsTab],
        link: str,
        *,
        is_read: Optional[bool] = None,
        is_bookmarked: Optional[bool] = None,
        notes: Optional[str] = None,
        deleted: bool = False,
    ) -> None:
        normalized_link = str(link or "").strip()
        if not normalized_link:
            return

        tabs_to_reload: List[NewsTab] = []
        for _index, tab in self._iter_news_tabs():
            if source_tab is not None and tab is source_tab:
                continue
            changed = tab.apply_external_item_state(
                normalized_link,
                is_read=is_read,
                is_bookmarked=is_bookmarked,
                notes=notes,
                deleted=deleted,
            )
            if changed or deleted:
                continue
            if is_bookmarked is True and tab.is_bookmark_tab and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)
            if is_read is False and tab.chk_unread.isChecked() and tab not in tabs_to_reload:
                tabs_to_reload.append(tab)

        for tab in tabs_to_reload:
            try:
                tab.load_data_from_db()
            except Exception as e:
                logger.warning("External tab sync reload failed (%s): %s", tab.keyword, e)

        self._schedule_badge_refresh(delay_ms=0)
        self.update_tray_tooltip()
        QTimer.singleShot(300, self.update_tray_tooltip)

    def _add_menu_action(self, menu: QMenu, text: str) -> QAction:
        action = menu.addAction(text)
        if action is None:
            raise RuntimeError(f"Failed to add menu action: {text}")
        return action

    def _make_tab_fetch_state(self) -> TabFetchState:
        return TabFetchState()

    def is_maintenance_mode_active(self) -> bool:
        return bool(getattr(self, "_maintenance_mode", False))

    def _maintenance_block_message(self, action: str) -> str:
        reason = str(getattr(self, "_maintenance_reason", "") or "데이터 정리")
        return f"유지보수 중이라 {action}을(를) 실행할 수 없습니다. ({reason})"

    def _set_fetch_controls_enabled(self, enabled: bool) -> None:
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(enabled)
        if hasattr(self, "btn_add"):
            self.btn_add.setEnabled(enabled)

        for _index, tab in self._iter_news_tabs():
            if tab.is_bookmark_tab:
                continue
            if enabled:
                self.sync_tab_load_more_state(tab.keyword)
            else:
                tab.btn_load.setEnabled(False)
                tab.btn_load.setText("🔒 유지보수 중")

    def _apply_maintenance_ui_state(self) -> None:
        active = self.is_maintenance_mode_active()
        self._set_fetch_controls_enabled(not active)
        if active:
            self._status_bar().showMessage(
                f"🔧 유지보수 중: {self._maintenance_reason or '데이터 정리'}",
            )

    def _cancel_active_fetch_workers(self, wait_ms: int = 1500) -> tuple[bool, List[str]]:
        deadline = time.monotonic() + (max(0, int(wait_ms)) / 1000.0)
        unfinished_keywords: List[str] = []

        if self._sequential_refresh_active:
            self._sequential_refresh_active = False
            self._pending_refresh_keywords = []
            self._current_refresh_idx = 0
            self._total_refresh_count = 0
            self.progress.setVisible(False)

        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False

        handles = self._worker_registry.all_handles()
        for handle in handles:
            remaining_ms = max(50, int((deadline - time.monotonic()) * 1000))
            finished = self.cleanup_worker(
                keyword=handle.tab_keyword,
                request_id=handle.request_id,
                only_if_active=False,
                wait_ms=remaining_ms,
            )
            if not finished:
                unfinished_keywords.append(handle.tab_keyword)

        return len(unfinished_keywords) == 0, unfinished_keywords

    def begin_database_maintenance(self, operation: str) -> tuple[bool, str]:
        if self.is_maintenance_mode_active():
            return False, "이미 다른 유지보수 작업이 진행 중입니다."

        ok, unfinished_keywords = self._cancel_active_fetch_workers(wait_ms=1500)
        if not ok:
            keywords_txt = ", ".join(unfinished_keywords)
            logger.warning("Database maintenance blocked by active fetch workers: %s", keywords_txt)
            return (
                False,
                f"활성 새로고침을 1.5초 안에 정리하지 못했습니다: {keywords_txt}",
            )

        operation_label = {
            "delete_old_news": "오래된 기사 정리",
            "delete_all_news": "전체 기사 정리",
        }.get(str(operation or "").strip(), "데이터 정리")
        self._maintenance_mode = True
        self._maintenance_reason = operation_label
        self._apply_maintenance_ui_state()
        self.show_warning_toast(f"{operation_label}를 위해 유지보수 모드로 전환했습니다.")
        return True, ""

    def end_database_maintenance(self) -> None:
        if not self.is_maintenance_mode_active():
            return
        self._maintenance_mode = False
        self._maintenance_reason = ""
        self._apply_maintenance_ui_state()
        self._status_bar().showMessage("✅ 유지보수 모드가 해제되었습니다.", 3000)
        self.show_toast("유지보수 모드가 해제되었습니다.")

    
    def _update_countdown(self):
        """상태바 카운트다운 업데이트"""
        if self._next_refresh_seconds > 0:
            self._next_refresh_seconds -= 1
            minutes = self._next_refresh_seconds // 60
            seconds = self._next_refresh_seconds % 60
            
            if not self._sequential_refresh_active:
                if minutes > 0:
                    countdown_text = f"⏰ 다음 새로고침: {minutes}분 {seconds}초 후"
                else:
                    countdown_text = f"⏰ 다음 새로고침: {seconds}초 후"
                self._status_bar().showMessage(countdown_text)
        else:
            self._countdown_timer.stop()

    
    def set_application_icon(self):
        """애플리케이션 아이콘 설정"""
        icon_path = self._resolve_icon_path()
        
        # 아이콘 적용
        if icon_path and os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            QApplication.setWindowIcon(app_icon)  # 모든 창에 적용
        else:
            logger.warning(f"아이콘 파일을 찾을 수 없습니다: {ICON_FILE} 또는 {ICON_PNG}")
            logger.warning(f"실행 파일과 같은 폴더에 아이콘 파일을 배치하세요.")

    def _resolve_icon_path(self):
        """런타임 환경(소스/onefile/onedir)에 맞는 아이콘 경로 해석"""
        search_dirs = []
        meipass_dir = getattr(sys, "_MEIPASS", None)
        if meipass_dir:
            search_dirs.append(meipass_dir)
        search_dirs.extend([
            APP_DIR,
            os.path.dirname(os.path.abspath(__file__)),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ])

        for base_dir in search_dirs:
            if not base_dir:
                continue
            if sys.platform == "win32":
                ico_path = os.path.join(base_dir, ICON_FILE)
                if os.path.exists(ico_path):
                    return ico_path
            png_path = os.path.join(base_dir, ICON_PNG)
            if os.path.exists(png_path):
                return png_path
        return None

    def load_config(self):
        """설정 로드"""
        loaded_cfg: Optional[AppConfig] = None
        try:
            loaded_cfg = load_config_file(CONFIG_FILE)
        except Exception as e:
            logger.error(f"설정 로드 오류 (Config Load Error): {e}")
            QMessageBox.warning(
                self,
                "설정 로드 오류",
                f"설정 파일을 읽는 중 오류가 발생했습니다.\n기본 설정으로 시작합니다.\n\n{str(e)}",
            )

        if loaded_cfg is None:
            loaded_cfg = default_config()

        settings = loaded_cfg.get("app_settings", {})
        resolved_client_secret, _ = resolve_client_secret_for_runtime(settings)
        self.config = {
            "client_id": settings.get("client_id", ""),
            "client_secret": resolved_client_secret,
            "client_secret_enc": settings.get("client_secret_enc", ""),
            "client_secret_storage": settings.get("client_secret_storage", "plain"),
            "theme": settings.get("theme_index", 0),
            "interval": settings.get("refresh_interval_index", 2),
            "tabs": loaded_cfg.get("tabs", []),
            "notification_enabled": settings.get("notification_enabled", True),
            "alert_keywords": settings.get("alert_keywords", []),
            "sound_enabled": settings.get("sound_enabled", True),
            "minimize_to_tray": settings.get("minimize_to_tray", True),
            "close_to_tray": settings.get("close_to_tray", True),
            "start_minimized": settings.get("start_minimized", False),
            "auto_start_enabled": settings.get("auto_start_enabled", False),
            "notify_on_refresh": settings.get("notify_on_refresh", False),
            "window_geometry": settings.get("window_geometry"),
            "search_history": loaded_cfg.get("search_history", []),
            "api_timeout": settings.get("api_timeout", 15),
            "keyword_groups": loaded_cfg.get("keyword_groups", {}),
            "pagination_state": loaded_cfg.get("pagination_state", {}),
            "pagination_totals": loaded_cfg.get("pagination_totals", {}),
        }

        self.client_id = self.config["client_id"]
        self.client_secret = self.config["client_secret"]
        self.theme_idx = self.config["theme"]
        self.interval_idx = self.config["interval"]
        self.tabs_data = self.config["tabs"]
        self.notification_enabled = self.config.get("notification_enabled", True)
        self.alert_keywords = self.config.get("alert_keywords", [])
        self.sound_enabled = self.config.get("sound_enabled", True)

        self.minimize_to_tray = self.config.get("minimize_to_tray", True)
        self.close_to_tray = self.config.get("close_to_tray", True)
        self.start_minimized = self.config.get("start_minimized", False)
        self.auto_start_enabled = self.config.get("auto_start_enabled", False)
        self._saved_geometry = self.config.get("window_geometry", None)
        self.notify_on_refresh = self.config.get("notify_on_refresh", False)
        self.search_history = self.config.get("search_history", [])
        self.api_timeout = self.config.get("api_timeout", 15)
        self.keyword_group_manager.groups = self.keyword_group_manager._normalize_groups(
            self.config.get("keyword_groups", {})
        )
        raw_pagination_state = self.config.get("pagination_state", {})
        self._fetch_cursor_by_key = {
            str(fetch_key): int(start_idx)
            for fetch_key, start_idx in (raw_pagination_state.items() if isinstance(raw_pagination_state, dict) else [])
            if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
        }
        raw_pagination_totals = self.config.get("pagination_totals", {})
        self._fetch_total_by_key = {
            str(fetch_key): int(total)
            for fetch_key, total in (raw_pagination_totals.items() if isinstance(raw_pagination_totals, dict) else [])
            if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
        }

    def save_config(self):
        """설정 저장"""
        tab_names = [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)]

        secret_payload = encode_client_secret_for_storage(self.client_secret)
        data: AppConfig = {
            "app_settings": {
                "client_id": self.client_id,
                "client_secret": secret_payload.get("client_secret", ""),
                "client_secret_enc": secret_payload.get("client_secret_enc", ""),
                "client_secret_storage": secret_payload.get("client_secret_storage", "plain"),
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
                "window_geometry": {
                    "x": self.x(),
                    "y": self.y(),
                    "width": self.width(),
                    "height": self.height(),
                },
            },
            "tabs": tab_names,
            "search_history": self.search_history,
            "keyword_groups": self.keyword_group_manager.groups,
            "pagination_state": {
                str(fetch_key): max(1, min(1000, int(start_idx)))
                for fetch_key, start_idx in self._fetch_cursor_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
            },
            "pagination_totals": {
                str(fetch_key): int(total)
                for fetch_key, total in self._fetch_total_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
            },
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                backup_file = CONFIG_FILE + ".backup"
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as src:
                        with open(backup_file, "w", encoding="utf-8") as dst:
                            dst.write(src.read())
                except Exception as backup_err:
                    logger.warning(f"설정 백업 복사 생략됨 (Config backup copy skipped): {backup_err}")

            save_config_file_atomic(CONFIG_FILE, data)
        except Exception as e:
            logger.error(f"설정 저장 오류 (Config Save Error): {e}")
            QMessageBox.warning(self, "저장 오류", f"설정을 저장하는 중 오류가 발생했습니다:\n\n{str(e)}")

    def _get_available_screen_geometry(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            if rect.width() > 0 and rect.height() > 0:
                return rect
        return QRect(0, 0, 1366, 900)

    def _build_default_window_geometry(self) -> Dict[str, int]:
        screen_rect = self._get_available_screen_geometry()
        min_width = min(980, screen_rect.width())
        min_height = min(700, screen_rect.height())

        width = int(screen_rect.width() * 0.92)
        height = int(screen_rect.height() * 0.88)
        width = max(min_width, min(width, screen_rect.width()))
        height = max(min_height, min(height, screen_rect.height()))

        x = screen_rect.x() + max(0, (screen_rect.width() - width) // 2)
        y = screen_rect.y() + max(0, (screen_rect.height() - height) // 2)
        return {"x": x, "y": y, "width": width, "height": height}

    def _normalize_window_geometry(self, raw_geometry: Optional[Dict[str, Any]]) -> Dict[str, int]:
        default_geometry = self._build_default_window_geometry()
        if not isinstance(raw_geometry, dict):
            return default_geometry

        screen_rect = self._get_available_screen_geometry()

        def _to_int(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        width = _to_int(raw_geometry.get("width"), default_geometry["width"])
        height = _to_int(raw_geometry.get("height"), default_geometry["height"])
        x = _to_int(raw_geometry.get("x"), default_geometry["x"])
        y = _to_int(raw_geometry.get("y"), default_geometry["y"])

        min_width = min(600, screen_rect.width())
        min_height = min(400, screen_rect.height())
        width = max(min_width, min(width, screen_rect.width()))
        height = max(min_height, min(height, screen_rect.height()))

        max_x = screen_rect.x() + max(0, screen_rect.width() - width)
        max_y = screen_rect.y() + max(0, screen_rect.height() - height)
        x = max(screen_rect.x(), min(x, max_x))
        y = max(screen_rect.y(), min(y, max_y))

        return {"x": x, "y": y, "width": width, "height": height}

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")

        initial_geometry = self._normalize_window_geometry(self._saved_geometry)
        self.setGeometry(
            initial_geometry["x"],
            initial_geometry["y"],
            initial_geometry["width"],
            initial_geometry["height"],
        )
        
        self.setMinimumSize(600, 400)  # 최소 창 크기 설정
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        
        # --- 주요 액션 그룹 ---
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.setToolTip("모든 탭의 뉴스를 새로고침합니다 (Ctrl+R, F5)")
        self.btn_refresh.setObjectName("RefreshBtn")
        
        self.btn_save = QPushButton("💾 내보내기")
        self.btn_save.setToolTip("현재 탭의 표시 결과를 CSV로 내보냅니다 (Ctrl+S)")
        
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_save)
        
        # --- 분석/관리 그룹 ---
        self.btn_stats = QPushButton("📊 통계")
        self.btn_stats.setToolTip("전체 뉴스 통계 및 언론사별 분석 보기")
        
        self.btn_setting = QPushButton("⚙ 설정")
        self.btn_setting.setToolTip("API 키 및 프로그램 설정 (Ctrl+,)")
        
        self.btn_backup = QPushButton("🗂 백업")
        self.btn_backup.setToolTip("설정 백업 및 복원")
        
        self.btn_help = QPushButton("❓ 도움말")
        self.btn_help.setToolTip("사용 방법 및 도움말 (F1)")
        
        toolbar.addWidget(self.btn_stats)
        toolbar.addWidget(self.btn_setting)
        toolbar.addWidget(self.btn_backup)
        toolbar.addWidget(self.btn_help)
        
        toolbar.addStretch()
        
        # --- 탭 관리 그룹 ---
        self.btn_add = QPushButton("➕ 새 탭")
        self.btn_add.setToolTip("새로운 키워드 탭 추가 (Ctrl+T)")
        self.btn_add.setObjectName("AddTab")
        
        toolbar.addWidget(self.btn_add)
        layout.addLayout(toolbar)
        
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setTextVisible(True)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        tab_bar = self._tab_bar()
        tab_bar.setUsesScrollButtons(True)
        tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        tab_bar.tabBarDoubleClicked.connect(self.rename_tab)
        tab_bar.tabMoved.connect(self.on_tab_moved)  # 탭 순서 저장
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self.on_tab_context_menu)
        layout.addWidget(self.tabs)
        
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_setting.clicked.connect(self.open_settings)
        self.btn_stats.clicked.connect(self.show_stats_analysis)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_backup.clicked.connect(self.show_backup_dialog)
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.btn_save.clicked.connect(self.export_data)
        
        self.bm_tab = NewsTab("북마크", self._require_db(), self.theme_idx, self)
        self.tabs.addTab(self.bm_tab, "⭐ 북마크")
        self._tab_bar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        
        for key in self.tabs_data:
            if key and key != "북마크":
                self.add_news_tab(key)
        
        # 초기 탭 배지 업데이트
        QTimer.singleShot(100, self.update_all_tab_badges)
        
        # 상태바 초기 메시지
        if self.client_id:
            self._status_bar().showMessage(f"✅ 준비됨 - {len(self.tabs_data)}개 탭")
        else:
            self._status_bar().showMessage("⚠️ API 키가 설정되지 않았습니다. 설정에서 API 키를 입력하세요.")
        


    def setup_shortcuts(self):
        """키보드 단축키 설정"""
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_all)
        QShortcut(QKeySequence("Ctrl+T"), self, self.add_tab_dialog)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+S"), self, self.export_data)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings)
        QShortcut(QKeySequence("F1"), self, self.show_help)
        QShortcut(QKeySequence("F5"), self, self.refresh_all)
        
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Alt+{i}"), self, lambda idx=i-1: self.switch_to_tab(idx))
        
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_filter)

    def _check_first_run(self):
        """첫 실행 시 API 키 설정 가이드 표시"""
        if not self.client_id or not self.client_secret:
            reply = QMessageBox.question(
                self,
                "🚀 뉴스 스크래퍼 Pro에 오신 것을 환영합니다!",
                "네이버 뉴스를 검색하려면 API 키가 필요합니다.\n\n"
                "네이버 개발자 센터에서 무료로 발급받을 수 있습니다.\n"
                "(https://developers.naver.com)\n\n"
                "지금 API 키를 설정하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.open_settings()
    
    def _set_tab_badge_text(self, tab_index: int, keyword: str, unread_count: int):
        self.tabs.setTabText(tab_index, self._format_tab_title(keyword, unread_count=unread_count))

    def _tab_icon_for_keyword(self, keyword: str) -> str:
        return "📰" if not str(keyword or "").startswith("-") else "🚫"

    def _format_tab_title(self, keyword: str, unread_count: int = 0) -> str:
        normalized_keyword = str(keyword or "").strip()
        badge = ""
        count = max(0, int(unread_count or 0))
        if count > 0:
            badge = " (99+)" if count > 99 else f" ({count})"
        return f"{self._tab_icon_for_keyword(normalized_keyword)} {normalized_keyword}{badge}"

    def _schedule_badge_refresh(self, delay_ms: int = 200):
        if not hasattr(self, "_badge_refresh_timer"):
            return
        if self._badge_refresh_timer.isActive():
            return
        self._badge_refresh_timer.start(max(0, int(delay_ms)))

    def update_all_tab_badges(self):
        """모든 탭의 배지(미읽음 수) 업데이트"""
        if getattr(self, "_badge_refresh_running", False):
            logger.info("PERF|ui.update_all_tab_badges.skip|0.00ms|reason=already_running")
            return

        self._badge_refresh_running = True
        try:
            tab_infos: List[Tuple[int, str, str, str]] = []
            query_keys: List[str] = []
            for i, widget in self._iter_news_tabs(start_index=1):
                keyword = widget.keyword
                db_keyword, exclude_words = parse_tab_query(keyword)
                search_keyword, _ = parse_search_query(keyword)
                query_key = build_fetch_key(search_keyword, exclude_words)
                if not db_keyword or not query_key:
                    continue
                tab_infos.append((i, keyword, db_keyword, query_key))
                query_keys.append(query_key)

            if not tab_infos:
                return

            with perf_timer("ui.update_all_tab_badges", f"tabs={len(tab_infos)}"):
                deduped_query_keys = list(dict.fromkeys(query_keys))
                unread_by_query_key = (
                    self._require_db().get_unread_counts_by_query_keys(deduped_query_keys)
                    if deduped_query_keys
                    else {}
                )

                for tab_index, keyword, _db_keyword, query_key in tab_infos:
                    unread_count = int(unread_by_query_key.get(query_key, 0))
                    self._badge_unread_cache[keyword] = unread_count
                    self._set_tab_badge_text(tab_index, keyword, unread_count)
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류: {e}")
        finally:
            self._badge_refresh_running = False

    def update_tab_badge(self, keyword: str):
        """특정 탭의 배지 업데이트"""
        try:
            located_tab = self._find_news_tab(keyword)
            if located_tab is not None:
                tab_index, _widget = located_tab
                cached = self._badge_unread_cache.get(keyword)
                if cached is not None:
                    self._set_tab_badge_text(tab_index, keyword, int(cached))
            self._schedule_badge_refresh()
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류 ({keyword}): {e}")

    def sync_tab_load_more_state(self, keyword: str):
        """Re-apply persisted load-more state after a tab reloads from DB."""
        located_tab = self._find_news_tab(keyword)
        if located_tab is None:
            return

        _tab_index, tab_widget = located_tab
        search_keyword, exclude_words = parse_search_query(keyword)
        fetch_key = build_fetch_key(search_keyword, exclude_words)
        fetch_state = self._tab_fetch_state.setdefault(keyword, self._make_tab_fetch_state())
        persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
        if persisted_cursor > fetch_state.last_api_start_index:
            fetch_state.last_api_start_index = persisted_cursor

        total = self._fetch_total_by_key.get(fetch_key)
        if isinstance(total, int) and total >= 0:
            tab_widget.total_api_count = total
        self._apply_load_more_button_state(
            tab_widget,
            total,
            fetch_state.last_api_start_index,
        )

    def maybe_show_query_refresh_hint(self, keyword: str):
        """Show a one-time hint when a new query_key scope still needs its first refresh."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword or normalized_keyword in self._query_key_migration_hints_shown:
            return

        search_keyword, exclude_words = parse_search_query(normalized_keyword)
        db_keyword, _ = parse_tab_query(normalized_keyword)
        query_key = build_fetch_key(search_keyword, exclude_words)
        legacy_query_key = build_fetch_key(db_keyword, [])
        if not db_keyword or not query_key or query_key == legacy_query_key:
            return
        if query_key in self._fetch_total_by_key or query_key in self._fetch_cursor_by_key:
            return

        db = self._require_db()
        if db.get_counts(db_keyword, query_key=query_key) > 0:
            return
        if db.get_counts(db_keyword) <= 0:
            return

        self._query_key_migration_hints_shown.add(normalized_keyword)
        self.show_warning_toast(
            f"'{normalized_keyword}' 탭은 한 번 새로고침해야 기존 데이터와 정확히 분리됩니다."
        )

    def switch_to_tab(self, index: int):
        """탭 전환"""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
    
    def focus_filter(self):
        """현재 탭의 필터 입력란에 포커스"""
        current_widget = self._current_news_tab()
        if current_widget is not None:
            current_widget.inp_filter.setFocus()
            current_widget.inp_filter.selectAll()
    
    def on_tab_moved(self, from_idx: int, to_idx: int):
        """탭 이동 시 순서 저장"""
        logger.info(f"탭 이동: {from_idx} -> {to_idx}")
        self.save_config()
    
    def show_desktop_notification(self, title: str, message: str):
        """데스크톱 알림 표시"""
        if not self.notification_enabled:
            return
        try:
            if hasattr(self, 'tray') and self.tray:
                self.tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    3000  # 3초
                )
            else:
                self.show_toast(f"{title}: {message}")
            if self.sound_enabled:
                NotificationSound.play('success')
        except Exception as e:
            logger.warning(f"데스크톱 알림 오류: {e}")
    
    def show_log_viewer(self):
        """로그 뷰어 다이얼로그 표시"""
        dialog = LogViewerDialog(self)
        dialog.exec()
    
    def show_keyword_groups(self):
        """키워드 그룹 관리 다이얼로그 표시"""
        # 현재 탭 목록 수집
        current_tabs = [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)]
        
        dialog = KeywordGroupDialog(self.keyword_group_manager, current_tabs, self)
        dialog.exec()
    
    def show_backup_dialog(self):
        """백업 관리 다이얼로그 표시"""
        dialog = BackupDialog(self.auto_backup, self)
        dialog.exec()
    
    def check_alert_keywords(self, items: list) -> list:
        """알림 키워드 체크 - 해당 키워드 포함된 기사 반환"""
        if not self.alert_keywords:
            return []
        
        matched = []
        for item in items:
            title = item.get('title', '').lower()
            desc = item.get('description', '').lower()
            for kw in self.alert_keywords:
                if kw.lower() in title or kw.lower() in desc:
                    matched.append((item, kw))
                    break
        return matched

    def show_toast(self, message: str, toast_type: ToastType = ToastType.INFO):
        """토스트 메시지 표시 - 유형별 스타일 지원"""
        self._require_toast_queue().add(message, toast_type)
    
    def show_success_toast(self, message: str):
        """성공 토스트 메시지"""
        self.show_toast(message, ToastType.SUCCESS)
    
    def show_warning_toast(self, message: str):
        """경고 토스트 메시지"""
        self.show_toast(message, ToastType.WARNING)
    
    def show_error_toast(self, message: str):
        """오류 토스트 메시지"""
        self.show_toast(message, ToastType.ERROR)
    
    def resizeEvent(self, a0: Optional[QResizeEvent]):
        """창 크기 변경 시 토스트 위치 업데이트"""
        super().resizeEvent(a0)
        if self.toast_queue is not None and self.toast_queue.current_toast is not None:
            self.toast_queue.current_toast.update_position()

    def apply_refresh_interval(self):
        """자동 새로고침 간격 적용 - 카운트다운 지원 버전"""
        try:
            self.timer.stop()
            self._countdown_timer.stop()
            idx = self.interval_idx
            minutes = [10, 30, 60, 120, 360]
            
            if 0 <= idx < len(minutes):
                ms = minutes[idx] * 60 * 1000
                self.timer.setInterval(ms)
                self.timer.start()
                
                # 카운트다운 타이머 시작
                self._next_refresh_seconds = minutes[idx] * 60
                self._countdown_timer.setInterval(1000)  # 1초마다 업데이트
                self._countdown_timer.start()
                
                self._status_bar().showMessage(f"⏰ 자동 새로고침: {minutes[idx]}분 간격")
                logger.info(f"자동 새로고침 설정: {minutes[idx]}분 ({ms}ms)")
            else:
                # 인덱스 5 = "자동 새로고침 안함"
                self.timer.stop()
                self._countdown_timer.stop()
                self._next_refresh_seconds = 0
                self._status_bar().showMessage("⏰ 자동 새로고침 꺼짐")
                logger.info("자동 새로고침 비활성화됨")
        except Exception as e:
            logger.error(f"타이머 설정 오류: {e}")
            traceback.print_exc()
