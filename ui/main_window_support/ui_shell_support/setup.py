# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false
from __future__ import annotations

import logging
import re
import traceback
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QApplication,
    QMenu,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.constants import APP_NAME, VERSION
from core.content_filters import normalize_publisher_filter_lists
from core.notifications import NotificationSound
from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query, parse_tab_query
from core.text_utils import perf_timer
from ui.dialogs import BackupDialog, KeywordGroupDialog, LogViewerDialog
from ui.news_tab import NewsTab
from ui.styles import AppStyle, ToastType

logger = logging.getLogger(__name__)


class _MainWindowSetupShellMixin:
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

        self.setMinimumSize(600, 400)
        self.setStyleSheet(self._active_app_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.btn_refresh = QPushButton("새로고침")
        self.btn_refresh.setToolTip("모든 탭의 뉴스를 새로고침합니다 (Ctrl+R, F5)")
        self.btn_refresh.setObjectName("RefreshBtn")

        self.btn_archive = QPushButton("기사 검색")
        self.btn_archive.setToolTip("저장된 전체 기사에서 검색합니다 (Ctrl+Shift+F)")

        # 읽기 흐름 밖의 기능은 더보기 메뉴 한 곳으로 모은다.
        self.btn_manage = QPushButton("더보기")
        self.btn_manage.setObjectName("MoreMenu")
        self.btn_manage.setToolTip("내보내기, 통계, 태그·규칙 관리, 백업, 설정")
        self.manage_menu = QMenu(self.btn_manage)
        self.action_export = self._add_menu_action(self.manage_menu, "현재 탭 내보내기 (CSV)\tCtrl+S")
        self.action_stats = self._add_menu_action(self.manage_menu, "통계")
        self.manage_menu.addSeparator()
        self.action_tags = self._add_menu_action(self.manage_menu, "태그 관리\tCtrl+Shift+T")
        self.action_rules = self._add_menu_action(self.manage_menu, "자동화 규칙\tCtrl+Shift+A")
        self.action_aliases = self._add_menu_action(self.manage_menu, "출처 별칭")
        self.manage_menu.addSeparator()
        self.action_backup = self._add_menu_action(self.manage_menu, "백업 및 복원")
        self.action_update = self._add_menu_action(self.manage_menu, "업데이트 확인")
        self.manage_menu.addSeparator()
        self.action_settings = self._add_menu_action(self.manage_menu, "설정\tCtrl+,")
        self.action_help = self._add_menu_action(self.manage_menu, "도움말\tF1")
        self.btn_manage.setMenu(self.manage_menu)

        self.btn_add = QPushButton("+ 새 탭")
        self.btn_add.setToolTip("새로운 키워드 탭 추가 (Ctrl+T)")
        self.btn_add.setObjectName("AddTab")

        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_archive)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_manage)
        toolbar.addWidget(self.btn_add)
        layout.addLayout(toolbar)

        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        tab_bar = self._tab_bar()
        tab_bar.setUsesScrollButtons(True)
        tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        tab_bar.tabBarDoubleClicked.connect(self.rename_tab)
        tab_bar.tabMoved.connect(self.on_tab_moved)
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self.on_tab_context_menu)
        layout.addWidget(self.tabs)

        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_archive.clicked.connect(self.show_archive_search)
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.action_export.triggered.connect(self.export_data)
        self.action_stats.triggered.connect(self.show_stats_analysis)
        self.action_tags.triggered.connect(self.show_tag_manager)
        self.action_rules.triggered.connect(self.show_automation_rules)
        self.action_aliases.triggered.connect(self.show_publisher_aliases)
        self.action_backup.triggered.connect(self.show_backup_dialog)
        self.action_update.triggered.connect(self.on_update_button_clicked)
        self.action_settings.triggered.connect(self.open_settings)
        self.action_help.triggered.connect(self.show_help)

        self.bm_tab = NewsTab("북마크", self._require_db(), self._effective_theme_idx(), self)
        self._connect_news_tab_hydration(self.bm_tab)
        self.tabs.addTab(self.bm_tab, "★ 북마크")
        self._tab_bar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

        for key in self.tabs_data:
            if key and key != "북마크":
                self.add_news_tab(key)

        QTimer.singleShot(0, self._bootstrap_tab_hydration)
        QTimer.singleShot(100, self.update_all_tab_badges)

        self.countdown_status_label = QLabel("")
        self.countdown_status_label.setObjectName("CountdownStatus")
        self._status_bar().addPermanentWidget(self.countdown_status_label)

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
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self.show_archive_search)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, self.show_tag_manager)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, self.show_automation_rules)

        for i in range(1, 10):
            QShortcut(QKeySequence(f"Alt+{i}"), self, lambda idx=i - 1: self.switch_to_tab(idx))

        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_filter)

    def _check_first_run(self):
        """첫 실행 시 API 키 설정 가이드 표시"""
        if not self.client_id or not self.client_secret:
            reply = QMessageBox.question(
                self,
                "🚀 뉴스 스크래퍼 Pro에 오신 것을 환영합니다!",
                "네이버 뉴스를 검색하려면 API 키가 필요합니다.\n\n"
                "네이버 클라우드 플랫폼의 NAVER API HUB에서\n"
                "Application을 등록하고 Client ID/Secret을 발급받으세요.\n"
                "(https://www.ncloud.com/product/applicationService/naverApiHub)\n\n"
                "지금 API 키를 설정하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.open_settings()

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
            policy_minutes = []
            for policy in getattr(self, "tab_refresh_policies", {}).values():
                try:
                    policy_value = int(str(policy))
                except ValueError:
                    continue
                if policy_value in minutes:
                    policy_minutes.append(policy_value)

            global_minutes = minutes[idx] if 0 <= idx < len(minutes) else None
            active_minutes = [value for value in ([global_minutes] if global_minutes else []) + policy_minutes if value]

            if active_minutes:
                tick_minutes = min(active_minutes)
                ms = tick_minutes * 60 * 1000
                self.timer.setInterval(ms)
                self.timer.start()

                self._next_refresh_seconds = tick_minutes * 60
                self._countdown_timer.setInterval(1000)
                self._countdown_timer.start()
                self._set_countdown_status_text(f"⏰ 다음 새로고침 확인: {tick_minutes}분 0초 후")

                self._status_bar().showMessage(f"⏰ 자동 새로고침 확인: {tick_minutes}분 간격")
                logger.info("자동 새로고침 설정: %s분 (%sms)", tick_minutes, ms)
            else:
                self.timer.stop()
                self._countdown_timer.stop()
                self._next_refresh_seconds = 0
                self._set_countdown_status_text("자동 새로고침 끔")
                self._status_bar().showMessage("⏰ 자동 새로고침 꺼짐")
                logger.info("자동 새로고침 비활성화됨")
        except Exception as exc:
            logger.error("타이머 설정 오류: %s", exc)
            traceback.print_exc()
