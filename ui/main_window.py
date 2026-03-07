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
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter

from PyQt6.QtCore import QEvent, QMutex, QMutexLocker, QRect, QThread, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
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

class MainApp(QMainWindow):
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
        self.toast_queue = None
        self.db = None
        self.session = None  # 세션 초기화
        
        try:
            self.db = DatabaseManager(DB_FILE)
            
            # Requests Session 설정 (성능 최적화: 연결 재사용)
            self.session = requests.Session()
            # Connection Pool 크기 증가 (동시 요청 처리)
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)
            
            self.workers = {}  # legacy compatibility mapping
            self._worker_registry = WorkerRegistry()
            self._worker_request_seq = 0
            self.toast_queue = ToastQueue(self)
            
            # 새로고침 상태 추적 (안정성 개선)
            self._refresh_in_progress = False
            self._refresh_queue = []
            self._refresh_mutex = QMutex()
            self._last_refresh_time = None
            
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
            self._request_start_index: Dict[int, int] = {}
            
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
                    lambda: self.statusBar().showMessage(
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
                self.statusBar().showMessage(countdown_text)
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
        if hasattr(sys, "_MEIPASS"):
            search_dirs.append(sys._MEIPASS)
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

    def setup_system_tray(self):
        """시스템 트레이 아이콘 설정"""
        try:
            # 트레이 아이콘 지원 확인
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("시스템 트레이를 사용할 수 없습니다.")
                self.tray = None
                return
            
            self.tray = QSystemTrayIcon(self)
            
            # 아이콘 설정
            icon_path = self._resolve_icon_path()
            
            if icon_path and os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                # 기본 아이콘 사용
                self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
            
            # 트레이 컨텍스트 메뉴 생성
            tray_menu = QMenu(self)
            
            # 열기 액션
            action_show = tray_menu.addAction("📰 열기")
            action_show.triggered.connect(self.show_window)
            
            # 새로고침 액션
            action_refresh = tray_menu.addAction("🔄 새로고침")
            action_refresh.triggered.connect(self._safe_refresh_all)
            
            tray_menu.addSeparator()
            
            # 설정 액션
            action_settings = tray_menu.addAction("⚙ 설정")
            action_settings.triggered.connect(self.open_settings)
            
            tray_menu.addSeparator()
            
            # 종료 액션
            action_quit = tray_menu.addAction("❌ 종료")
            action_quit.triggered.connect(self.real_quit)
            
            self.tray.setContextMenu(tray_menu)
            
            # 더블클릭 시 창 보이기
            self.tray.activated.connect(self.on_tray_activated)
            
            # 초기 툴팁 설정
            self.update_tray_tooltip()
            
            # 트레이 아이콘 표시
            self.tray.show()
            
            logger.info("시스템 트레이 아이콘 설정 완료")
        except Exception as e:
            logger.error(f"시스템 트레이 설정 오류: {e}")
            self.tray = None
    
    def on_tray_activated(self, reason):
        """트레이 아이콘 활성화 이벤트 처리"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 싱글 클릭 시 툴팁 업데이트
            self.update_tray_tooltip()
    
    def update_tray_tooltip(self):
        """트레이 아이콘 툴팁 업데이트 (읽지 않은 기사 수 표시)"""
        if not hasattr(self, 'tray') or not self.tray:
            return
        
        try:
            unread_count = int(self.db.get_total_unread_count()) if self.db else 0
            
            if unread_count > 0:
                tooltip = f"{APP_NAME}\n📬 읽지 않은 기사: {unread_count:,}개"
            else:
                tooltip = f"{APP_NAME}\n✅ 모든 기사를 읽었습니다"
            
            self.tray.setToolTip(tooltip)
        except Exception as e:
            logger.warning(f"트레이 툴팁 업데이트 오류: {e}")
            self.tray.setToolTip(APP_NAME)
    
    def show_window(self):
        """창 표시 (트레이에서 복원)"""
        if self.isHidden():
            self.show()
        if self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.update_tray_tooltip()
    
    def real_quit(self):
        """프로그램 완전 종료 (트레이 메뉴에서 호출)"""
        logger.info("사용자가 트레이 메뉴에서 종료 요청")
        self._user_requested_close = True
        self._force_close = True
        
        # 설정 저장
        try:
            self.save_config()
        except Exception as e:
            logger.error(f"종료 전 설정 저장 오류: {e}")
        
        # 트레이 아이콘 숨기기
        if hasattr(self, 'tray') and self.tray:
            self.tray.hide()
        
        self.close()
    
    def show_tray_notification(self, title: str, message: str, icon_type=None):
        """시스템 트레이 알림 표시 (새 뉴스 도착 등)"""
        if not hasattr(self, 'tray') or not self.tray:
            return
        
        try:
            if icon_type is None:
                icon_type = QSystemTrayIcon.MessageIcon.Information
            
            self.tray.showMessage(
                title,
                message,
                icon_type,
                5000  # 5초간 표시
            )
        except Exception as e:
            logger.warning(f"트레이 알림 표시 오류: {e}")

    def load_config(self):
        """설정 로드"""
        loaded_cfg = None
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

    def save_config(self):
        """설정 저장"""
        tab_names = []
        for i in range(1, self.tabs.count()):
            tab_widget = self.tabs.widget(i)
            if tab_widget and hasattr(tab_widget, 'keyword'):
                tab_names.append(tab_widget.keyword)

        secret_payload = encode_client_secret_for_storage(self.client_secret)
        data = {
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
        self.btn_save.setToolTip("현재 탭의 뉴스를 CSV로 내보냅니다 (Ctrl+S)")
        
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
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)
        self.tabs.tabBar().tabMoved.connect(self.on_tab_moved)  # 탭 순서 저장
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.on_tab_context_menu)
        layout.addWidget(self.tabs)
        
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_setting.clicked.connect(self.open_settings)
        self.btn_stats.clicked.connect(self.show_stats_analysis)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_backup.clicked.connect(self.show_backup_dialog)
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.btn_save.clicked.connect(self.export_data)
        
        self.bm_tab = NewsTab("북마크", self.db, self.theme_idx, self)
        self.tabs.addTab(self.bm_tab, "⭐ 북마크")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        
        for key in self.tabs_data:
            if key and key != "북마크":
                self.add_news_tab(key)
        
        # 초기 탭 배지 업데이트
        QTimer.singleShot(100, self.update_all_tab_badges)
        
        # 상태바 초기 메시지
        if self.client_id:
            self.statusBar().showMessage(f"✅ 준비됨 - {len(self.tabs_data)}개 탭")
        else:
            self.statusBar().showMessage("⚠️ API 키가 설정되지 않았습니다. 설정에서 API 키를 입력하세요.")
        


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
            tab_infos: List[Tuple[int, str, str, List[str]]] = []
            plain_db_keywords: List[str] = []
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if not widget or not hasattr(widget, "keyword"):
                    continue
                keyword = widget.keyword
                db_keyword, exclude_words = parse_tab_query(keyword)
                if not db_keyword:
                    continue
                normalized_excludes = [
                    ex for ex in exclude_words if isinstance(ex, str) and ex.strip()
                ]
                tab_infos.append((i, keyword, db_keyword, normalized_excludes))
                if not normalized_excludes:
                    plain_db_keywords.append(db_keyword)

            if not tab_infos:
                return

            with perf_timer("ui.update_all_tab_badges", f"tabs={len(tab_infos)}"):
                deduped_plain_keywords = list(dict.fromkeys(plain_db_keywords))
                unread_by_kw = (
                    self.db.get_unread_counts_by_keywords(deduped_plain_keywords)
                    if deduped_plain_keywords
                    else {}
                )

                for tab_index, keyword, db_keyword, exclude_words in tab_infos:
                    if exclude_words:
                        unread_count = int(
                            self.db.count_news(
                                keyword=db_keyword,
                                only_unread=True,
                                exclude_words=exclude_words,
                            )
                        )
                    else:
                        unread_count = int(unread_by_kw.get(db_keyword, 0))
                    self._badge_unread_cache[keyword] = unread_count
                    self._set_tab_badge_text(tab_index, keyword, unread_count)
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류: {e}")
        finally:
            self._badge_refresh_running = False

    def update_tab_badge(self, keyword: str):
        """특정 탭의 배지 업데이트"""
        try:
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if widget and hasattr(widget, "keyword") and widget.keyword == keyword:
                    cached = self._badge_unread_cache.get(keyword)
                    if cached is not None:
                        self._set_tab_badge_text(i, keyword, int(cached))
                    break
            self._schedule_badge_refresh()
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류 ({keyword}): {e}")

    def switch_to_tab(self, index: int):
        """탭 전환"""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
    
    def focus_filter(self):
        """현재 탭의 필터 입력란에 포커스"""
        current_widget = self.tabs.currentWidget()
        if current_widget and hasattr(current_widget, 'inp_filter'):
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
                # 알림 소리 재생
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
        current_tabs = []
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget and hasattr(widget, 'keyword'):
                current_tabs.append(widget.keyword)
        
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
        self.toast_queue.add(message, toast_type)
    
    def show_success_toast(self, message: str):
        """성공 토스트 메시지"""
        self.show_toast(message, ToastType.SUCCESS)
    
    def show_warning_toast(self, message: str):
        """경고 토스트 메시지"""
        self.show_toast(message, ToastType.WARNING)
    
    def show_error_toast(self, message: str):
        """오류 토스트 메시지"""
        self.show_toast(message, ToastType.ERROR)
    
    def resizeEvent(self, event):
        """창 크기 변경 시 토스트 위치 업데이트"""
        super().resizeEvent(event)
        if hasattr(self, 'toast_queue') and self.toast_queue and self.toast_queue.current_toast:
            self.toast_queue.current_toast.update_position()

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event.type() != QEvent.Type.WindowStateChange:
                return
            if self._force_close:
                return
            if not self.isMinimized():
                return
            if not self.minimize_to_tray:
                return
            if not hasattr(self, "tray") or not self.tray:
                return

            QTimer.singleShot(0, self.hide)
            if not hasattr(self, "_tray_minimize_notified") or not self._tray_minimize_notified:
                self.show_tray_notification(APP_NAME, "프로그램이 트레이로 최소화되었습니다.")
                self._tray_minimize_notified = True
            self.update_tray_tooltip()
        except Exception as e:
            logger.warning(f"최소화 이벤트 처리 오류: {e}")

    def close_current_tab(self):
        """현재 탭 닫기"""
        idx = self.tabs.currentIndex()
        if idx > 0:
            self.close_tab(idx)

    def _normalize_tab_keyword(self, raw_keyword: str) -> Optional[str]:
        if not isinstance(raw_keyword, str):
            return None
        keyword = ValidationUtils.sanitize_keyword(raw_keyword).strip()
        if not keyword:
            return None
        if not has_positive_keyword(keyword):
            return None
        return keyword

    def _is_fetch_key_referenced(self, fetch_key: str, skip_keyword: Optional[str] = None) -> bool:
        if not fetch_key:
            return False
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if not widget or not hasattr(widget, "keyword"):
                continue
            tab_keyword = widget.keyword
            if skip_keyword is not None and tab_keyword == skip_keyword:
                continue
            search_query, exclude_words = parse_search_query(tab_keyword)
            if not search_query:
                continue
            if build_fetch_key(search_query, exclude_words) == fetch_key:
                return True
        return False

    def add_news_tab(self, keyword: str):
        """뉴스 탭 추가"""
        keyword = self._normalize_tab_keyword(keyword)
        if not keyword:
            logger.warning("유효하지 않은 탭 키워드로 add_news_tab 요청이 무시되었습니다.")
            return

        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if hasattr(widget, 'keyword') and widget.keyword == keyword:
                self.tabs.setCurrentIndex(i)
                return
        
        tab = NewsTab(keyword, self.db, self.theme_idx, self)
        tab.btn_load.clicked.connect(lambda _checked=False, tab_ref=tab: self.fetch_news(tab_ref.keyword, is_more=True))
        search_query, exclude_words = parse_search_query(keyword)
        fetch_key = build_fetch_key(search_query, exclude_words)
        fetch_state = self._tab_fetch_state.setdefault(keyword, TabFetchState())
        persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
        if persisted_cursor > fetch_state.last_api_start_index:
            fetch_state.last_api_start_index = persisted_cursor
        self.tabs.addTab(tab, self._format_tab_title(keyword, unread_count=0))
        
        # 탭 추가 직후 캐시 로드 (오프라인 모드 지원 및 즉각적인 UI 표시)

    def add_tab_dialog(self):
        """새 탭 추가 다이얼로그 - 검색 히스토리 지원"""
        dialog = QDialog(self)
        dialog.setWindowTitle("새 탭 추가")
        dialog.resize(450, 300)
        
        layout = QVBoxLayout(dialog)
        
        info_label = QLabel(
            "검색할 키워드를 입력하세요.\n"
            "제외 키워드는 '-'를 앞에 붙여주세요.\n\n"
            "예시: 주식 -코인, 인공지능 AI -광고\n"
            "※ API 검색은 양키워드를 모두 사용하며, DB 그룹은 첫 키워드 기준입니다."
        )
        info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info_label)
        
        input_field = QLineEdit()
        input_field.setPlaceholderText("🔍 키워드 입력...")
        layout.addWidget(input_field)
        
        # 최근 검색 히스토리 표시
        if self.search_history:
            history_label = QLabel("📋 최근 검색:")
            history_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
            layout.addWidget(history_label)
            
            history_layout = QHBoxLayout()
            for kw in self.search_history[:5]:  # 최근 5개
                btn = QPushButton(kw)
                btn.setStyleSheet("padding: 4px 8px; font-size: 9pt;")
                btn.clicked.connect(lambda checked, text=kw: input_field.setText(text))
                history_layout.addWidget(btn)
            history_layout.addStretch()
            layout.addLayout(history_layout)
        
        # 빠른 입력 (추천 키워드)
        quick_label = QLabel("💡 추천 키워드:")
        quick_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(quick_label)
        
        quick_layout = QHBoxLayout()
        examples = ["주식", "부동산", "IT 기술", "스포츠", "경제"]
        for example in examples:
            btn = QPushButton(example)
            btn.setStyleSheet("padding: 4px 8px; font-size: 9pt;")
            btn.clicked.connect(lambda checked, text=example: input_field.setText(text))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)
        
        layout.addStretch()
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec():
            raw_keyword = input_field.text().strip()
            
            # 키워드 입력 검증
            if not raw_keyword:
                QMessageBox.warning(self, "입력 오류", "키워드를 입력해 주세요.")
                return
            
            if len(raw_keyword) > 100:
                QMessageBox.warning(
                    self, 
                    "입력 오류", 
                    f"키워드가 너무 깁니다. ({len(raw_keyword)}자)\n"
                    "최대 100자까지 입력 가능합니다."
                )
                return
            
            keyword = self._normalize_tab_keyword(raw_keyword)
            if not keyword:
                QMessageBox.warning(
                    self,
                    "입력 오류",
                    "최소 1개 이상의 일반 키워드를 포함해야 합니다.\n예: AI -광고",
                )
                return
            
            # 중복 탭 체크
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if hasattr(w, 'keyword') and w.keyword == keyword:
                    QMessageBox.information(
                        self, 
                        "중복 태브", 
                        f"'{keyword}' 탭이 이미 존재합니다.\n해당 탭으로 이동합니다."
                    )
                    self.tabs.setCurrentIndex(i)
                    return
            
            self.add_news_tab(keyword)
            self.fetch_news(keyword)
            
            # 검색 히스토리에 추가
            if keyword not in self.search_history:
                self.search_history.insert(0, keyword)
                self.search_history = self.search_history[:10]  # 최대 10개 유지
            
            # 설정 저장 (히스토리 업데이트)
            self.save_config()

    def close_tab(self, idx: int):
        """탭 닫기"""
        if idx == 0:
            return
        
        widget = self.tabs.widget(idx)
        removed_keyword = None
        if widget:
            if hasattr(widget, "keyword"):
                removed_keyword = widget.keyword
                active_request_id = self._worker_registry.get_active_request_id(removed_keyword)
                if active_request_id is not None:
                    self.cleanup_worker(
                        keyword=removed_keyword,
                        request_id=active_request_id,
                        only_if_active=False,
                    )
            if hasattr(widget, "cleanup"):
                try:
                    widget.cleanup()
                except Exception as e:
                    logger.warning(f"탭 정리 중 오류: {e}")
            widget.deleteLater()
        self.tabs.removeTab(idx)
        if removed_keyword:
            self._tab_fetch_state.pop(removed_keyword, None)
            removed_search_query, removed_exclude_words = parse_search_query(removed_keyword)
            removed_fetch_key = build_fetch_key(removed_search_query, removed_exclude_words)
            if removed_fetch_key and not self._is_fetch_key_referenced(removed_fetch_key):
                self._fetch_cursor_by_key.pop(removed_fetch_key, None)
        self.save_config()

    def rename_tab(self, idx: int):
        """탭 이름 변경"""
        if idx == 0:
            return
        
        w = self.tabs.widget(idx)
        if not w:
            return
        
        text, ok = QInputDialog.getText(
            self,
            '탭 이름 변경',
            '새 검색 키워드를 입력하세요:',
            QLineEdit.EchoMode.Normal,
            w.keyword
        )
        
        if ok and text.strip():
            old_keyword = w.keyword
            active_request_id = self._worker_registry.get_active_request_id(old_keyword)
            if active_request_id is not None:
                self.cleanup_worker(
                    keyword=old_keyword,
                    request_id=active_request_id,
                    only_if_active=False,
                )
            new_keyword = self._normalize_tab_keyword(text)
            if not new_keyword:
                QMessageBox.warning(
                    self,
                    "입력 오류",
                    "탭 이름에는 최소 1개 이상의 일반 키워드가 필요합니다.",
                )
                return

            for i in range(1, self.tabs.count()):
                if i == idx:
                    continue
                target = self.tabs.widget(i)
                if target and hasattr(target, "keyword") and target.keyword == new_keyword:
                    QMessageBox.information(self, "중복 탭", f"'{new_keyword}' 탭이 이미 존재합니다.")
                    return

            w.keyword = new_keyword
            
            self.tabs.setTabText(idx, self._format_tab_title(new_keyword, unread_count=0))
            
            old_search_keyword, old_exclude_words = parse_search_query(old_keyword)
            new_search_keyword, new_exclude_words = parse_search_query(new_keyword)

            old_fetch_key = build_fetch_key(old_search_keyword, old_exclude_words)
            new_fetch_key = build_fetch_key(new_search_keyword, new_exclude_words)

            fetch_state = self._tab_fetch_state.pop(old_keyword, None)
            if old_fetch_key != new_fetch_key:
                # 쿼리 의미가 바뀌면 페이지네이션/요청 dedupe 상태를 초기화한다.
                self._last_fetch_request_ts.pop(old_fetch_key, None)
                self._last_fetch_request_ts.pop(new_fetch_key, None)
                if old_fetch_key and not self._is_fetch_key_referenced(old_fetch_key, skip_keyword=new_keyword):
                    self._fetch_cursor_by_key.pop(old_fetch_key, None)
                self._tab_fetch_state[new_keyword] = TabFetchState()
                persisted_cursor = int(self._fetch_cursor_by_key.get(new_fetch_key, 0) or 0)
                if persisted_cursor > 0:
                    self._tab_fetch_state[new_keyword].last_api_start_index = persisted_cursor
            elif fetch_state is not None:
                self._tab_fetch_state[new_keyword] = fetch_state
            else:
                self._tab_fetch_state.setdefault(new_keyword, TabFetchState())
                persisted_cursor = int(self._fetch_cursor_by_key.get(new_fetch_key, 0) or 0)
                if persisted_cursor > self._tab_fetch_state[new_keyword].last_api_start_index:
                    self._tab_fetch_state[new_keyword].last_api_start_index = persisted_cursor

            groups_changed = False
            for group_name, keywords in self.keyword_group_manager.groups.items():
                if old_keyword in keywords:
                    keywords[:] = [new_keyword if keyword == old_keyword else keyword for keyword in keywords]
                    deduped: List[str] = []
                    for keyword in keywords:
                        if keyword not in deduped:
                            deduped.append(keyword)
                    keywords[:] = deduped
                    groups_changed = True
            if groups_changed:
                self.keyword_group_manager.save_groups()

            # 기존 DB 데이터는 보존하고, 리네임된 탭은 새 키워드 기준으로 즉시 재조회한다.
            try:
                w.load_data_from_db()
            except Exception as e:
                logger.warning(f"리네임 직후 탭 재조회 실패: {e}")

            self.fetch_news(new_keyword)
            self.save_config()

    def on_tab_context_menu(self, pos):
        """탭 바 컨텍스트 메뉴"""
        idx = self.tabs.tabBar().tabAt(pos)
        if idx <= 0:  # 0은 북마크 탭
            return
            
        widget = self.tabs.widget(idx)
        if not widget or not hasattr(widget, 'keyword'):
            return
            
        keyword = widget.keyword
        
        menu = QMenu(self)
        
        act_refresh = menu.addAction("🔄 새로고침")
        act_rename = menu.addAction("✏️ 이름 변경")
        menu.addSeparator()
        
        # 그룹 메뉴
        group_menu = menu.addMenu("📁 그룹에 추가")
        groups = self.keyword_group_manager.get_all_groups()
        if groups:
            for group in groups:
                act = group_menu.addAction(group)
                act.triggered.connect(lambda checked, g=group, k=keyword: 
                                    self._add_to_group_callback(g, k))
        else:
            group_menu.setDisabled(True)
            
        menu.addSeparator()
        act_close = menu.addAction("❌ 탭 닫기")
        
        # mapToGlobal은 self.tabs.tabBar() 기준으로 변환해야 함
        action = menu.exec(self.tabs.tabBar().mapToGlobal(pos))
        
        if action == act_refresh:
            self.fetch_news(keyword)
        elif action == act_rename:
            self.rename_tab(idx)
        elif action == act_close:
            self.close_tab(idx)

    def _add_to_group_callback(self, group: str, keyword: str):
        """컨텍스트 메뉴에서 그룹 추가 콜백"""
        if self.keyword_group_manager.add_keyword_to_group(group, keyword):
            self.show_success_toast(f"'{keyword}'을(를) '{group}' 그룹에 추가했습니다.")
        else:
            self.show_warning_toast(f"이미 '{group}' 그룹에 존재하는 키워드입니다.")

    def _safe_refresh_all(self):
        """안전한 자동 새로고침 래퍼 (타이머에서 호출)"""
        # 네트워크 연속 오류 시 자동 새로고침 일시 중지
        if self._network_error_count >= self._max_network_errors:
            if self._network_available:  # 첫 번째 감지 시에만 로그
                logger.warning(f"네트워크 연속 오류 {self._network_error_count}회. 자동 새로고침 일시 중지.")
                self._network_available = False
                self.statusBar().showMessage("⚠ 네트워크 오류로 자동 새로고침 일시 중지 (수동 새로고침으로 재개)")
            return
        
        # 이미 새로고침 진행 중이면 건너뜀
        with QMutexLocker(self._refresh_mutex):
            if self._refresh_in_progress or self._sequential_refresh_active:
                logger.warning("새로고침이 이미 진행 중입니다. 건너킵니다.")
                return
            self._refresh_in_progress = True
        
        started = False
        try:
            started = self.refresh_all()
        except Exception as e:
            logger.error(f"자동 새로고침 오류: {e}")
        finally:
            if not started:
                # 시작 실패/조기 종료 케이스에서는 락 플래그를 즉시 복구
                # (시작 성공 시 플래그 해제는 _finish_sequential_refresh에서 처리)
                with QMutexLocker(self._refresh_mutex):
                    self._refresh_in_progress = False

    def refresh_all(self) -> bool:
        """모든 탭 새로고침 - 완전한 순차 새로고침 버전"""
        logger.info("전체 새로고침 시작")
        
        # 이미 순차 새로고침 진행 중이면 무시
        if self._sequential_refresh_active:
            logger.warning("순차 새로고침이 이미 진행 중입니다. 건너킵니다.")
            return False
        
        try:
            valid, msg = ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
            if not valid:
                self.statusBar().showMessage(f"⚠ {msg}")
                logger.warning(f"API 자격증명 오류: {msg}")
                return False

            # 수동 새로고침 시 네트워크 오류 카운터 리셋 (자동 새로고침 재개)
            self._network_error_count = 0
            self._network_available = True
            
            # 북마크 탭 새로고침 (동기)
            try:
                self.bm_tab.load_data_from_db()
            except Exception as e:
                logger.error(f"북마크 탭 로드 오류: {e}")
            
            # 새로고침할 키워드 목록 수집
            self._pending_refresh_keywords = []
            tab_count = self.tabs.count()
            for i in range(1, tab_count):
                try:
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'keyword'):
                        if has_positive_keyword(widget.keyword):
                            self._pending_refresh_keywords.append(widget.keyword)
                except Exception as e:
                    logger.error(f"탭 {i} 접근 오류: {e}")
            
            if not self._pending_refresh_keywords:
                self.statusBar().showMessage("새로고침할 탭이 없습니다.")
                return False
            
            # 순차 새로고침 상태 초기화
            self._sequential_refresh_active = True
            self._current_refresh_idx = 0
            self._total_refresh_count = len(self._pending_refresh_keywords)
            self._sequential_added_count = 0  # 누적 카운터 초기화
            self._sequential_dup_count = 0
            
            # UI 설정
            self.progress.setVisible(True)
            self.progress.setRange(0, self._total_refresh_count)
            self.progress.setValue(0)
            self.statusBar().showMessage(f"🔄 순차 새로고침 중... (0/{self._total_refresh_count})")
            self.btn_refresh.setEnabled(False)
            
            logger.info(f"순차 새로고침 시작: {self._total_refresh_count}개 탭")
            
            # 첫 번째 탭 새로고침 시작
            self._process_next_refresh()
            return True
                    
        except Exception as e:
            logger.error(f"refresh_all 오류: {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 새로고침 오류: {str(e)}")
            self._finish_sequential_refresh()
            return False

    def _process_next_refresh(self):
        """순차 새로고침 체인: 다음 탭 처리"""
        if not self._sequential_refresh_active:
            return
            
        if self._current_refresh_idx >= len(self._pending_refresh_keywords):
            # 모든 탭 완료
            self._finish_sequential_refresh()
            return
        
        keyword = self._pending_refresh_keywords[self._current_refresh_idx]
        logger.info(f"순차 새로고침: [{self._current_refresh_idx + 1}/{self._total_refresh_count}] '{keyword}'")
        
        self.progress.setValue(self._current_refresh_idx)
        self.statusBar().showMessage(
            f"🔄 '{keyword}' 새로고침 중... ({self._current_refresh_idx + 1}/{self._total_refresh_count})"
        )
        
        try:
            self.fetch_news(keyword, is_sequential=True)
        except Exception as e:
            logger.error(f"'{keyword}' 새로고침 오류: {e}")
            # 오류 발생해도 다음 탭 진행
            self._current_refresh_idx += 1
            QTimer.singleShot(500, self._process_next_refresh)

    def _on_sequential_fetch_done(self, keyword: str):
        """순차 새로고침에서 하나의 fetch 완료 시 호출"""
        if not self._sequential_refresh_active:
            return
            
        self._current_refresh_idx += 1
        
        # 약간의 딜레이 후 다음 탭 처리 (API rate limit 방지)
        QTimer.singleShot(300, self._process_next_refresh)

    def _finish_sequential_refresh(self):
        """순차 새로고침 완료 처리"""
        self._sequential_refresh_active = False
        self._pending_refresh_keywords = []
        self._last_refresh_time = datetime.now()
        
        # _safe_refresh_all에서 설정한 플래그도 해제
        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False
        
        self.progress.setValue(self._total_refresh_count)
        self.progress.setVisible(False)
        self.btn_refresh.setEnabled(True)
        
        # 누적 카운터를 사용한 최종 메시지
        added = self._sequential_added_count
        dup = self._sequential_dup_count
        
        logger.info(f"순차 새로고침 완료 ({self._total_refresh_count}개 탭, {added}건 추가, {dup}건 중복)")
        
        toast_msg = f"✓ {self._total_refresh_count}개 탭 새로고침 완료 ({added}건 추가"
        if dup > 0:
            toast_msg += f", {dup}건 중복"
        toast_msg += ")"
        
        self.statusBar().showMessage(toast_msg, 5000)
        self.show_toast(toast_msg)
        
        # 자동 새로고침 완료 윈도우 알림 (설정 시)
        if self.notify_on_refresh and added > 0:
            self.show_tray_notification(
                "📰 자동 새로고침 완료",
                f"{added}건의 새 뉴스가 업데이트되었습니다."
            )
        
        # 카운트다운 타이머 재시작
        self.apply_refresh_interval()

    def _next_worker_request_id(self) -> int:
        self._worker_request_seq += 1
        return self._worker_request_seq

    def _is_active_worker_request(self, keyword: str, request_id: Optional[int]) -> bool:
        if request_id is None:
            return True
        return self._worker_registry.is_active(keyword, request_id)

    def _compute_load_more_state(self, total: int, last_api_start_index: int) -> bool:
        total = max(0, int(total or 0))
        last_api_start_index = max(0, int(last_api_start_index or 0))
        next_start = last_api_start_index + 100
        has_more = next_start <= min(1000, total)
        return has_more

    def _apply_load_more_button_state(self, tab_widget, total: int, last_api_start_index: int) -> bool:
        has_more = self._compute_load_more_state(total, last_api_start_index)
        if has_more:
            tab_widget.btn_load.setEnabled(True)
            tab_widget.btn_load.setText("📥 더 불러오기")
        else:
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("✅ 마지막 페이지")
        return has_more

    def fetch_news(self, keyword: str, is_more: bool = False, is_sequential: bool = False):
        """뉴스 가져오기 - 순차 새로고침 지원"""
        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            if not is_sequential:
                self.show_warning_toast("탭 키워드에 검색어가 없습니다. 탭 이름을 확인해주세요.")
            return
        db_keyword, _ = parse_tab_query(keyword)
        if not db_keyword:
            db_keyword = search_keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)

        if not is_more and not is_sequential:
            now_ts = time.time()
            last_ts = self._last_fetch_request_ts.get(fetch_key, 0.0)
            if (now_ts - last_ts) < self._fetch_dedupe_window_sec:
                logger.info(
                    f"PERF|net.fetch_deduped|0.00ms|kw={fetch_key}|window={self._fetch_dedupe_window_sec}s"
                )
                return
            self._last_fetch_request_ts[fetch_key] = now_ts

        fetch_state = self._tab_fetch_state.setdefault(keyword, TabFetchState())
        start_idx = 1
        if is_more:
            persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
            if persisted_cursor > fetch_state.last_api_start_index:
                fetch_state.last_api_start_index = persisted_cursor
            if fetch_state.last_api_start_index > 0:
                start_idx = fetch_state.last_api_start_index + 100
            else:
                start_idx = 101
            if start_idx > 1000:
                QMessageBox.information(
                    self,
                    "알림",
                    "네이버 검색 API는 최대 1,000개까지만 조회할 수 있습니다.",
                )
                if is_sequential:
                    self._on_sequential_fetch_done(keyword)
                return

        old_handle = self._worker_registry.get_active_handle(keyword)
        if old_handle:
            self.cleanup_worker(keyword=keyword, request_id=old_handle.request_id, only_if_active=True)

        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, "keyword") and w.keyword == keyword:
                w.btn_load.setEnabled(False)
                w.btn_load.setText("⏳ 로딩 중...")
                break

        worker = ApiWorker(
            self.client_id,
            self.client_secret,
            search_keyword,
            db_keyword,
            exclude_words,
            self.db,
            start_idx,
            timeout=self.api_timeout,
            display_keyword=keyword,
        )
        thread = QThread()
        worker.moveToThread(thread)

        request_id = self._next_worker_request_id()
        handle = WorkerHandle(
            request_id=request_id,
            tab_keyword=keyword,
            search_keyword=search_keyword,
            db_keyword=db_keyword,
            exclude_words=list(exclude_words),
            worker=worker,
            thread=thread,
        )
        self._request_start_index[request_id] = start_idx
        self._worker_registry.register(handle)
        self.workers[keyword] = (worker, thread)

        worker.finished.connect(
            lambda res, rid=request_id: self.on_fetch_done(res, keyword, is_more, is_sequential, rid)
        )
        worker.error.connect(
            lambda err, rid=request_id: self.on_fetch_error(err, keyword, is_sequential, rid)
        )
        if not is_sequential:
            worker.progress.connect(self.statusBar().showMessage)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id, kw=keyword: self.cleanup_worker(
                keyword=kw, request_id=rid, only_if_active=False
            )
        )

        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(
        self,
        result: Dict,
        keyword: str,
        is_more: bool,
        is_sequential: bool = False,
        request_id: Optional[int] = None,
    ):
        """뉴스 가져오기 완료 - 순차 새로고침 지원"""
        try:
            if not self._is_active_worker_request(keyword, request_id):
                logger.info(f"오래된 완료 콜백 무시 (stale on_fetch_done ignored): kw={keyword}, rid={request_id}")
                return

            search_keyword, exclude_words = parse_search_query(keyword)
            if not search_keyword:
                search_keyword = keyword
            fetch_key = build_fetch_key(search_keyword, exclude_words)
            
            # DB 저장은 Worker에서 이미 수행됨
            added_count = result.get('added_count', 0)
            dup_count = result.get('dup_count', 0)
            completed_start_idx = None
            if request_id is not None:
                completed_start_idx = self._request_start_index.get(request_id)
                if completed_start_idx is not None:
                    self._tab_fetch_state.setdefault(keyword, TabFetchState()).last_api_start_index = completed_start_idx
                    if completed_start_idx > 0:
                        self._fetch_cursor_by_key[fetch_key] = int(completed_start_idx)
            
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if w and hasattr(w, 'keyword') and w.keyword == keyword:
                    w.total_api_count = result['total']
                    w.update_timestamp()
                    w.load_data_from_db()

                    last_api_start_index = completed_start_idx
                    if last_api_start_index is None:
                        last_api_start_index = self._tab_fetch_state.setdefault(
                            keyword,
                            TabFetchState(),
                        ).last_api_start_index
                    total = int(result.get('total', 0) or 0)
                    self._apply_load_more_button_state(w, total, last_api_start_index)
                    if getattr(w, "worker", None):
                        w.worker.finished.connect(
                            lambda *_args, tab_ref=w, total_ref=total, start_idx_ref=last_api_start_index:
                            self._apply_load_more_button_state(tab_ref, total_ref, start_idx_ref)
                        )
                        w.worker.error.connect(
                            lambda *_args, tab_ref=w, total_ref=total, start_idx_ref=last_api_start_index:
                            self._apply_load_more_button_state(tab_ref, total_ref, start_idx_ref)
                        )
                    
                    if not is_more and not is_sequential:
                        msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                        if dup_count > 0:
                            msg += f", {dup_count}건 중복"
                        if result.get('filtered', 0) > 0:
                            msg += f", {result['filtered']}건 필터링"
                        msg += ")"
                        w.lbl_status.setText(msg)
                    break
            
            # 순차 새로고침 중이면 UI 복원하지 않음
            if not is_sequential:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)
                
                if not is_more:
                    toast_msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        toast_msg += f", {dup_count}건 유사"
                    toast_msg += ")"
                    self.show_toast(toast_msg)
                    self.statusBar().showMessage(toast_msg, 3000)
                    
                    # 새 기사가 있으면 데스크톱 알림
                    if added_count > 0:
                        self.show_desktop_notification(
                            f"📰 {keyword}",
                            f"{added_count}건의 새 뉴스가 있습니다."
                        )
                        # 창이 숨겨져 있으면 트레이 알림도 표시
                        if not self.isVisible():
                            self.show_tray_notification(
                                f"📰 {keyword}",
                                f"{added_count}건의 새 뉴스가 도착했습니다."
                            )
                        # 트레이 툴팁 업데이트
                        self.update_tray_tooltip()
                    
                    # 알림 키워드 체크
                    matched = self.check_alert_keywords(result['items'])
                    if matched:
                        for item, kw in matched[:3]:  # 최대 3개
                            title = html.unescape(RE_HTML_TAGS.sub('', item.get('title', '')))
                            self.show_desktop_notification(
                                f"🔔 알림 키워드: {kw}",
                                title[:50]
                            )
            else:
                # 순차 새로고침 체인: 카운터 누적 후 다음 탭으로 진행
                self._sequential_added_count += added_count
                self._sequential_dup_count += dup_count
                logger.info(f"순차 새로고침 완료: '{keyword}' ({added_count}건 추가)")
                self._on_sequential_fetch_done(keyword)
            
            # 성공 시 네트워크 오류 카운터 리셋
            self._network_error_count = 0
            self._network_available = True
            
            # 탭 배지 업데이트
            self.update_tab_badge(keyword)
                
        except Exception as e:
            logger.error(f"가져오기 완료 처리 오류 (Fetch Done Error): {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 처리 중 오류: {str(e)}")
            # UI 복원
            if not is_sequential:
                self.progress.setVisible(False)
                self.btn_refresh.setEnabled(True)
            else:
                # 순차 새로고침 중 오류 발생해도 다음 탭 진행
                self._on_sequential_fetch_done(keyword)

    def on_fetch_error(
        self, error_msg: str, keyword: str, is_sequential: bool = False, request_id: Optional[int] = None
    ):
        """뉴스 가져오기 오류 - 순차 새로고침 지원"""
        if not self._is_active_worker_request(keyword, request_id):
            logger.info(f"오래된 오류 콜백 무시 (stale on_fetch_error ignored): kw={keyword}, rid={request_id}")
            return

        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            search_keyword = keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)
        self._last_fetch_request_ts.pop(fetch_key, None)
        if request_id is not None:
            self._request_start_index.pop(request_id, None)

        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(True)
                w.btn_load.setText("📥 더 불러오기")
                break
        
        if not is_sequential:
            # 개별 새로고침 시 UI 복원 및 오류 메시지
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self.btn_refresh.setEnabled(True)
            
            self.statusBar().showMessage(f"⚠ '{keyword}' 오류: {error_msg}", 5000)
            QMessageBox.critical(
                self, 
                "API 오류", 
                f"'{keyword}' 검색 중 오류가 발생했습니다:\n\n{error_msg}\n\n"
                "API 키가 올바른지, 네트워크 연결 상태를 확인해주세요."
            )
        else:
            # 순차 새로고침 중에는 오류 로그만 남기고 다음 탭으로 진행
            logger.warning(f"순차 새로고침 중 오류: '{keyword}' - {error_msg}")
            self._on_sequential_fetch_done(keyword)
        
        # 네트워크 관련 오류인 경우 카운터 증가
        network_error_keywords = ['네트워크', 'timeout', '연결', 'connection', 'Timeout', 'Network']
        is_network_error = any(kw in error_msg for kw in network_error_keywords)
        if is_network_error:
            self._network_error_count += 1
            logger.warning(f"네트워크 오류 카운트: {self._network_error_count}/{self._max_network_errors}")
        else:
            # 네트워크가 아닌 오류는 카운터 리셋 (API 키 오류 등)
            self._network_error_count = 0

    def cleanup_worker(
        self,
        keyword: Optional[str] = None,
        request_id: Optional[int] = None,
        only_if_active: bool = False,
    ):
        """워커 정리 - request_id 기반 안정성 개선"""
        try:
            if request_id is None and keyword:
                request_id = self._worker_registry.get_active_request_id(keyword)
            if request_id is None:
                return

            handle = self._worker_registry.get_by_request_id(request_id)
            if not handle:
                return

            if only_if_active and keyword and not self._worker_registry.is_active(keyword, request_id):
                return

            handle = self._worker_registry.pop_by_request_id(request_id)
            if not handle:
                return

            worker = handle.worker
            thread = handle.thread

            try:
                worker.finished.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.error.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.progress.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass

            try:
                worker.stop()
            except (AttributeError, RuntimeError):
                pass

            try:
                thread.quit()
                thread.wait(1000)
            except (AttributeError, RuntimeError):
                pass

            self.workers.pop(handle.tab_keyword, None)
            self._request_start_index.pop(request_id, None)
            logger.info(f"워커 정리 완료: {handle.tab_keyword} (rid={request_id})")
        except Exception as e:
            logger.error(f"워커 정리 오류 (keyword={keyword}, rid={request_id}): {e}")

    def refresh_bookmark_tab(self):
        """북마크 탭 새로고침"""
        self.bm_tab.load_data_from_db()

    def on_database_maintenance_completed(self, operation: str, affected_count: int = 0):
        """DB 직접 변경 후 열린 탭/배지/UI 상태를 동기화한다."""
        try:
            for i in range(self.tabs.count()):
                widget = self.tabs.widget(i)
                if widget and hasattr(widget, "load_data_from_db"):
                    widget.load_data_from_db()
            self._schedule_badge_refresh(delay_ms=0)
            self.update_tray_tooltip()
            QTimer.singleShot(300, self.update_tray_tooltip)
            logger.info(f"DB 유지보수 후 UI 동기화 완료: op={operation}, count={affected_count}")
        except Exception as e:
            logger.warning(f"DB 유지보수 후 UI 동기화 오류: {e}")

    def export_data(self):
        """데이터 내보내기"""
        cur_widget = self.tabs.currentWidget()
        if not cur_widget or not hasattr(cur_widget, 'news_data_cache') or not cur_widget.news_data_cache:
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
                with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['제목', '링크', '날짜', '출처', '요약', '읽음', '북마크', '메모', '중복'])
                    
                    for item in cur_widget.news_data_cache:
                        writer.writerow([
                            item['title'],
                            item['link'],
                            item['pubDate'],
                            item['publisher'],
                            item['description'],
                            '읽음' if item['is_read'] else '안읽음',
                            '⭐' if item['is_bookmarked'] else '',
                            item.get('notes', ''),
                            '유사' if item.get('is_duplicate', 0) else ''
                        ])
                
                self.show_success_toast(f"✓ {len(cur_widget.news_data_cache)}개 항목이 저장되었습니다")
                QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")
                
            except Exception as e:
                QMessageBox.warning(self, "오류", f"저장 중 오류 발생:\n{str(e)}")
    
    def export_settings(self):
        """설정 JSON 내보내기 (API 키 제외)"""
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "설정 내보내기",
            f"news_scraper_settings_{datetime.now().strftime('%Y%m%d')}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if fname:
            # API 키는 보안상 제외
            export_data = {
                'export_version': '1.0',
                'app_version': VERSION,
                'settings': {
                    'theme_index': self.theme_idx,
                    'refresh_interval_index': self.interval_idx,
                    'notification_enabled': self.notification_enabled,
                    'alert_keywords': self.alert_keywords,
                    'sound_enabled': self.sound_enabled,
                    'minimize_to_tray': self.minimize_to_tray,
                    'close_to_tray': self.close_to_tray,
                    'start_minimized': self.start_minimized,
                    'notify_on_refresh': self.notify_on_refresh,
                    'api_timeout': self.api_timeout,
                },
                'tabs': [self.tabs.widget(i).keyword 
                        for i in range(1, self.tabs.count()) 
                        if hasattr(self.tabs.widget(i), 'keyword')],
                'keyword_groups': self.keyword_group_manager.groups,
            }
            
            try:
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=4, ensure_ascii=False)
                self.show_success_toast("✓ 설정이 내보내기되었습니다.")
                QMessageBox.information(self, "완료", f"설정이 저장되었습니다:\n{fname}\n\n(API 키는 보안상 제외됨)")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 내보내기 오류:\n{str(e)}")
    
    def import_settings(self):
        """설정 JSON 가져오기"""
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "설정 가져오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if fname:
            try:
                with open(fname, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)
                
                # 설정 적용 (정규화 + 보정 경고)
                settings = import_data.get('settings', {})
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
                
                # 테마 적용
                self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
                for i in range(self.tabs.count()):
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'theme'):
                        widget.theme = self.theme_idx
                        widget.render_html()
                
                # 탭 추가 (중복 제외)
                imported_tabs = import_data.get('tabs', [])
                existing_keywords = {
                    self.tabs.widget(i).keyword
                    for i in range(1, self.tabs.count())
                    if hasattr(self.tabs.widget(i), 'keyword')
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

    def show_statistics(self):
        """통계 정보 표시"""
        stats = self.db.get_statistics()
        
        if stats['total'] > 0:
            read_count = stats['total'] - stats['unread']
            read_percent = (read_count / stats['total']) * 100
        else:
            read_percent = 0
        
        dialog = QDialog(self)
        dialog.setWindowTitle("통계 정보")
        dialog.resize(350, 350)
        
        layout = QVBoxLayout(dialog)
        
        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()
        
        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
            ("탭 개수:", f"{self.tabs.count() - 1}개"),
        ]
        
        for i, (label, value) in enumerate(items):
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel(value)
            val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
            grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
        
        group.setLayout(grid)
        layout.addWidget(group)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()

    def show_stats_analysis(self):
        """통계 및 분석 통합 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 통계 및 분석")
        dialog.resize(550, 500)
        
        main_layout = QVBoxLayout(dialog)
        
        # 탭 위젯
        tab_widget = QTabWidget()
        
        # === 통계 탭 ===
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        
        stats = self.db.get_statistics()
        if stats['total'] > 0:
            read_percent = ((stats['total'] - stats['unread']) / stats['total']) * 100
        else:
            read_percent = 0
        
        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()
        
        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
            ("탭 개수:", f"{self.tabs.count() - 1}개"),
        ]
        
        for i, (label, value) in enumerate(items):
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel(value)
            val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
            grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
        
        group.setLayout(grid)
        stats_layout.addWidget(group)
        stats_layout.addStretch()
        
        # === 분석 탭 ===
        analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(analysis_widget)
        
        tab_label = QLabel("분석할 탭을 선택하세요:")
        analysis_layout.addWidget(tab_label)
        
        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword'):
                # DB 조회용 키워드(db_keyword)를 data로 저장
                if hasattr(w, "db_keyword"):
                    db_kw = w.db_keyword
                else:
                    db_kw, _ = parse_tab_query(w.keyword)
                if not db_kw:
                    continue
                tab_combo.addItem(w.keyword, w.keyword)
        analysis_layout.addWidget(tab_combo)
        
        result_label = QLabel("📈 언론사별 기사 수:")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        analysis_layout.addWidget(result_label)
        
        result_list = QListWidget()
        analysis_layout.addWidget(result_list)
        
        def update_analysis():
            result_list.clear()
            tab_query = tab_combo.currentData()
            if isinstance(tab_query, str) and tab_query.strip():
                db_keyword, exclude_words = parse_tab_query(tab_query)
                publishers = self.db.get_top_publishers(
                    db_keyword,
                    exclude_words=exclude_words,
                    limit=20,
                )
            else:
                publishers = self.db.get_top_publishers(None, limit=20)
            
            if publishers:
                for i, (pub, count) in enumerate(publishers, 1):
                    result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                result_list.addItem("데이터가 없습니다.")
        
        tab_combo.currentIndexChanged.connect(update_analysis)
        update_analysis()
        
        # 탭 추가
        tab_widget.addTab(stats_widget, "📊 통계")
        tab_widget.addTab(analysis_widget, "📈 언론사 분석")
        
        main_layout.addWidget(tab_widget)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        main_layout.addWidget(btn_close)
        
        dialog.exec()

    def show_analysis(self):
        """언론사별 분석 (호환성 유지)"""
        self.show_stats_analysis()

    def show_help(self):
        """도움말 표시 (설정 창의 도움말 탭으로 열기)"""
        current_config = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'interval': self.interval_idx,
            'theme': self.theme_idx,
            'sound_enabled': self.sound_enabled,
            'api_timeout': self.api_timeout,
        }
        
        dlg = SettingsDialog(current_config, self)
        # 도움말 탭으로 전환 (탭 인덱스 1)
        if hasattr(dlg, 'findChild'):
            tab_widget = dlg.findChild(QTabWidget)
            if tab_widget:
                tab_widget.setCurrentIndex(1)  # 도움말 탭
        
        dlg.exec()

    def open_settings(self):
        """설정 다이얼로그"""
        current_config = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'interval': self.interval_idx,
            'theme': self.theme_idx,
            'notification_enabled': self.notification_enabled,
            'alert_keywords': self.alert_keywords,
            'sound_enabled': self.sound_enabled,
            'minimize_to_tray': self.minimize_to_tray,
            'close_to_tray': self.close_to_tray,
            'start_minimized': self.start_minimized,
            'auto_start_enabled': self.auto_start_enabled,
            'notify_on_refresh': self.notify_on_refresh,
            'api_timeout': self.api_timeout,
        }
        
        dlg = SettingsDialog(current_config, self)
        if dlg.exec():
            data = dlg.get_data()
            
            self.client_id = data['id']
            self.client_secret = data['secret']
            self.interval_idx = data['interval']
            
            # 알림 설정 적용
            self.notification_enabled = data.get('notification_enabled', True)
            self.alert_keywords = data.get('alert_keywords', [])
            self.sound_enabled = data.get('sound_enabled', True)
            self.api_timeout = data.get('api_timeout', 15)
            
            # 트레이 설정 적용
            self.minimize_to_tray = data.get('minimize_to_tray', True)
            self.close_to_tray = data.get('close_to_tray', True)
            prev_start_minimized = self.start_minimized
            new_start_minimized = data.get('start_minimized', False)
            if new_start_minimized and not getattr(self, "tray", None):
                logger.warning("트레이 미지원 환경: start_minimized 설정을 해제합니다.")
                new_start_minimized = False
                self.show_warning_toast("트레이를 사용할 수 없어 '시작 시 최소화'가 해제되었습니다.")
            self.start_minimized = new_start_minimized
            self.notify_on_refresh = data.get('notify_on_refresh', False)
            
            # 자동 시작 설정 적용 (Windows 레지스트리)
            new_auto_start = data.get('auto_start_enabled', False)
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
            
            if self.theme_idx != data['theme']:
                self.theme_idx = data['theme']
                self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
                
                for i in range(self.tabs.count()):
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'theme'):
                        widget.theme = self.theme_idx
                        widget.render_html()
            
            self.apply_refresh_interval()
            self.save_config()
            
            self.show_success_toast("✓ 설정이 저장되었습니다.")

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
                
                self.statusBar().showMessage(f"⏰ 자동 새로고침: {minutes[idx]}분 간격")
                logger.info(f"자동 새로고침 설정: {minutes[idx]}분 ({ms}ms)")
            else:
                # 인덱스 5 = "자동 새로고침 안함"
                self.timer.stop()
                self._countdown_timer.stop()
                self._next_refresh_seconds = 0
                self.statusBar().showMessage("⏰ 자동 새로고침 꺼짐")
                logger.info("자동 새로고침 비활성화됨")
        except Exception as e:
            logger.error(f"타이머 설정 오류: {e}")
            traceback.print_exc()


    def closeEvent(self, event):
        """종료 이벤트 - 트레이 최소화 지원 버전"""
        # 초기화 실패 시에도 안전하게 동작하도록 방어적 코딩
        if not hasattr(self, '_system_shutdown'):
            self._system_shutdown = False
        if not hasattr(self, '_force_close'):
            self._force_close = False
        if not hasattr(self, '_user_requested_close'):
            self._user_requested_close = False
        
        # 종료 원인 분석을 위한 호출 스택 로깅
        caller_info = self._get_close_caller_info() if hasattr(self, '_get_close_caller_info') else "Unknown"
        logger.info(f"closeEvent 호출됨 (호출 원인: {caller_info})")
        
        # 시스템 종료거나 강제 종료 요청인 경우 → 실제 종료
        if self._system_shutdown or self._force_close:
            if self._system_shutdown:
                logger.warning("시스템 종료로 인한 프로그램 종료")
            # 실제 종료 처리로 진행
            self._perform_real_close(event)
            return
        
        # 트레이 아이콘이 있고, 트레이로 최소화 설정이 켜져 있으면 → 트레이로 숨기기
        if hasattr(self, 'tray') and self.tray and self.close_to_tray:
            logger.info("창을 트레이로 최소화")
            event.ignore()
            self.hide()
            
            # 처음 트레이로 숨길 때 알림 표시
            if not hasattr(self, '_tray_hide_notified') or not self._tray_hide_notified:
                self.show_tray_notification(
                    APP_NAME,
                    "프로그램이 시스템 트레이에서 계속 실행됩니다.\n트레이 아이콘을 더블클릭하여 창을 열 수 있습니다."
                )
                self._tray_hide_notified = True
            
            # 트레이 툴팁 업데이트
            self.update_tray_tooltip()
            return
        
        # 트레이 최소화가 비활성화된 경우 → 종료 확인 다이얼로그
        if not self._user_requested_close:
            reply = QMessageBox.question(
                self,
                "프로그램 종료",
                "정말로 프로그램을 종료하시겠습니까?\n\n"
                "종료하면 뉴스 자동 새로고침이 중지됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                logger.info("사용자가 종료를 취소함")
                event.ignore()
                return
            
            self._user_requested_close = True
            logger.info("사용자가 종료 확인함")
        
        # 실제 종료 처리
        self._perform_real_close(event)
    
    def _perform_real_close(self, event):
        """프로그램 실제 종료 처리"""
        logger.info("프로그램 실제 종료 시작...")
        
        try:
            # 모든 타이머 중지 (초기화되지 않았을 수 있으므로 hasattr 체크)
            if hasattr(self, 'timer') and self.timer:
                self.timer.stop()
            if hasattr(self, '_countdown_timer') and self._countdown_timer:
                self._countdown_timer.stop()
            if hasattr(self, '_tab_badge_timer') and self._tab_badge_timer:
                self._tab_badge_timer.stop()
            logger.info("타이머 중지됨")
            
            # 모든 워커 정리 (request_id 기반)
            if hasattr(self, "_worker_registry"):
                for handle in list(self._worker_registry.all_handles()):
                    try:
                        self.cleanup_worker(
                            keyword=handle.tab_keyword,
                            request_id=handle.request_id,
                            only_if_active=False,
                        )
                    except Exception as e:
                        logger.error(f"워커 종료 오류 ({handle.tab_keyword}, rid={handle.request_id}): {e}")

            self.workers.clear()
            logger.info("워커 정리 완료")
            
            # 설정 저장
            try:
                self.save_config()
                logger.info("설정 저장 완료")
            except Exception as e:
                logger.error(f"설정 저장 오류: {e}")
            
            # DB 종료
            if hasattr(self, 'db') and self.db:
                try:
                    self.db.close()
                    logger.info("DB 연결 종료")
                except Exception as e:
                    logger.error(f"DB 종료 오류: {e}")
            
            # HTTP 세션 종료
            if hasattr(self, 'session') and self.session:
                try:
                    self.session.close()
                    logger.info("HTTP 세션 종료")
                except Exception as e:
                    logger.error(f"세션 종료 오류: {e}")
            
            # 전역 HTTP 세션 정리
            
            logger.info("프로그램 종료 처리 완료")
            
            # 명시적으로 애플리케이션 종료
            QApplication.instance().quit()
            
        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}")
            traceback.print_exc()
            # 오류가 나더라도 종료 시도
            QApplication.instance().quit()
        
        event.accept()
    
    def _get_close_caller_info(self) -> str:
        """종료 호출 원인을 분석하여 반환"""
        try:
            # 호출 스택 분석
            stack = inspect.stack()
            caller_info = []
            
            for frame_info in stack[2:8]:  # closeEvent 이후 최대 6개 프레임 분석
                func_name = frame_info.function
                filename = os.path.basename(frame_info.filename)
                lineno = frame_info.lineno
                
                # 중요한 호출자 정보만 기록
                if func_name not in ['closeEvent', '_get_close_caller_info']:
                    caller_info.append(f"{func_name}@{filename}:{lineno}")
            
            if not caller_info:
                return "Unknown"
            
            return " <- ".join(caller_info[:3])  # 최대 3개만 표시
        except Exception as e:
            return f"Error analyzing stack: {e}"
    
    # def nativeEvent(self, eventType, message):
    #     """Windows 네이티브 이벤트 처리 - 시스템 종료 감지"""
    #     return super().nativeEvent(eventType, message)
    
    def request_close(self, confirmed: bool = False):
        """트레이 메뉴 등에서 종료 요청 시 사용"""
        if confirmed:
            self._user_requested_close = True
            self._force_close = True
        self.close()
