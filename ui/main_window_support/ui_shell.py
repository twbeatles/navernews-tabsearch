# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false
from __future__ import annotations

import logging
import traceback
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
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


class _MainWindowUIShellMixin:
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
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.setToolTip("모든 탭의 뉴스를 새로고침합니다 (Ctrl+R, F5)")
        self.btn_refresh.setObjectName("RefreshBtn")

        self.btn_save = QPushButton("💾 내보내기")
        self.btn_save.setToolTip("현재 탭의 표시 결과를 CSV로 내보냅니다 (Ctrl+S)")

        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_save)

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
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        tab_bar.tabBarDoubleClicked.connect(self.rename_tab)
        tab_bar.tabMoved.connect(self.on_tab_moved)
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
        self._connect_news_tab_hydration(self.bm_tab)
        self.tabs.addTab(self.bm_tab, "⭐ 북마크")
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
                "네이버 개발자 센터에서 무료로 발급받을 수 있습니다.\n"
                "(https://developers.naver.com)\n\n"
                "지금 API 키를 설정하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.open_settings()

    def _set_tab_badge_text(self, tab_index: int, keyword: str, unread_count: int):
        self.tabs.setTabText(tab_index, self._format_tab_title(keyword, unread_count=unread_count))

    def _tab_icon_for_keyword(self, keyword: str) -> str:
        return "📰" if has_positive_keyword(str(keyword or "")) else "🚫"

    def _format_tab_title(self, keyword: str, unread_count: int = 0) -> str:
        normalized_keyword = str(keyword or "").strip()
        badge = ""
        count = max(0, int(unread_count or 0))
        if count > 0:
            badge = " (99+)" if count > 99 else f" ({count})"
        return f"{self._tab_icon_for_keyword(normalized_keyword)} {normalized_keyword}{badge}"

    def _schedule_badge_refresh(self, delay_ms: int = 75):
        if not hasattr(self, "_badge_refresh_timer"):
            return
        if self._badge_refresh_timer.isActive():
            self._badge_refresh_timer.stop()
        self._badge_refresh_timer.start(max(0, int(delay_ms)))

    def update_all_tab_badges(self):
        """모든 탭의 배지(미읽음 수) 업데이트"""
        if getattr(self, "_badge_refresh_running", False):
            logger.info("PERF|ui.update_all_tab_badges.skip|0.00ms|reason=already_running")
            return

        if self.is_maintenance_mode_active():
            logger.info("PERF|ui.update_all_tab_badges.skip|0.00ms|reason=maintenance")
            return

        self._badge_refresh_running = True
        try:
            tab_infos: List[Tuple[int, NewsTab]] = []
            for i, widget in self._iter_news_tabs(start_index=1):
                if not getattr(widget, "db_keyword", "") or not getattr(widget, "query_key", ""):
                    continue
                tab_infos.append((i, widget))

            if not tab_infos:
                return

            with perf_timer("ui.update_all_tab_badges", f"tabs={len(tab_infos)}"):
                db = self._require_db()
                for tab_index, widget in tab_infos:
                    keyword = widget.keyword
                    scope_kwargs = widget._build_query_scope().count_kwargs()
                    scope_kwargs["only_unread"] = True
                    unread_count = int(db.count_news(**scope_kwargs))
                    self._badge_unread_cache[keyword] = unread_count
                    self._set_tab_badge_text(tab_index, keyword, unread_count)
        except Exception as exc:
            logger.warning("탭 배지 업데이트 오류: %s", exc)
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
        except Exception as exc:
            logger.warning("탭 배지 업데이트 오류 (%s): %s", keyword, exc)

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
        try:
            if db.get_counts(db_keyword, query_key=query_key) > 0:
                return
            if db.get_counts(db_keyword) <= 0:
                return
        except Exception as exc:
            logger.warning("Query refresh hint skipped because DB read failed (%s): %s", normalized_keyword, exc)
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
        logger.info("탭 이동: %s -> %s", from_idx, to_idx)
        self.save_config()

    def show_desktop_notification(self, title: str, message: str):
        """데스크톱 알림 표시"""
        if not self.notification_enabled:
            return
        try:
            if hasattr(self, "tray") and self.tray:
                self.tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            else:
                self.show_toast(f"{title}: {message}")
            if self.sound_enabled:
                NotificationSound.play("success")
        except Exception as exc:
            logger.warning("데스크톱 알림 오류: %s", exc)

    def show_log_viewer(self):
        """로그 뷰어 다이얼로그 표시"""
        dialog = LogViewerDialog(self)
        dialog.exec()

    def show_keyword_groups(self):
        """키워드 그룹 관리 다이얼로그 표시"""
        current_tabs = [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)]

        dialog = KeywordGroupDialog(self.keyword_group_manager, current_tabs, self)
        dialog.exec()

    def save_saved_search(self, name: str, payload: dict):
        normalized_name = str(name or "").strip()[:60]
        if not normalized_name:
            return
        searches = dict(getattr(self, "saved_searches", {}))
        searches[normalized_name] = dict(payload)
        self.saved_searches = searches
        self.save_config()
        self._refresh_saved_search_combos()
        self.show_success_toast("검색 조건을 저장했습니다.")

    def delete_saved_search(self, name: str):
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return
        searches = dict(getattr(self, "saved_searches", {}))
        if normalized_name not in searches:
            self.show_warning_toast("삭제할 저장 검색을 찾지 못했습니다.")
            return
        searches.pop(normalized_name, None)
        self.saved_searches = searches
        self.save_config()
        self._refresh_saved_search_combos()
        self.show_success_toast("저장 검색을 삭제했습니다.")

    def _refresh_saved_search_combos(self):
        for _index, tab in self._iter_news_tabs():
            refresh_combo = getattr(tab, "_refresh_saved_search_combo", None)
            if callable(refresh_combo):
                refresh_combo()

    def open_saved_search_target_tab(self, keyword: str):
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return self._current_news_tab()
        fetch_key = self._canonical_fetch_key_for_keyword(normalized_keyword)
        located_tab = self._find_news_tab_by_fetch_key(fetch_key)
        if located_tab is None:
            self.add_news_tab(normalized_keyword, defer_initial_load=True)
            located_tab = self._find_news_tab_by_fetch_key(fetch_key)
        if located_tab is None:
            return self._current_news_tab()
        tab_index, tab = located_tab
        self.tabs.setCurrentIndex(tab_index)
        return tab

    def _reload_tabs_for_visibility_filters(self):
        for _index, tab in self._iter_news_tabs():
            try:
                refresh_tags = getattr(tab, "_refresh_tag_filter_options", None)
                if callable(refresh_tags):
                    refresh_tags()
                tab.load_data_from_db()
            except Exception as exc:
                logger.warning("Visibility filter reload failed (%s): %s", tab.keyword, exc)
        self._schedule_badge_refresh(delay_ms=0)

    def add_blocked_publisher(self, publisher: str):
        publishers, preferred_publishers = normalize_publisher_filter_lists(
            list(getattr(self, "blocked_publishers", [])) + [publisher],
            getattr(self, "preferred_publishers", []),
        )
        if publishers == getattr(self, "blocked_publishers", []) and preferred_publishers == getattr(
            self,
            "preferred_publishers",
            [],
        ):
            self.show_warning_toast("이미 차단된 출처입니다.")
            return
        self.blocked_publishers = publishers
        self.preferred_publishers = preferred_publishers
        self.save_config()
        self._reload_tabs_for_visibility_filters()
        self.show_success_toast(f"'{publisher}' 출처를 차단했습니다.")

    def add_preferred_publisher(self, publisher: str):
        blocked_publishers, publishers = normalize_publisher_filter_lists(
            getattr(self, "blocked_publishers", []),
            list(getattr(self, "preferred_publishers", [])) + [publisher],
            preferred_wins=True,
        )
        if publishers == getattr(self, "preferred_publishers", []) and blocked_publishers == getattr(
            self,
            "blocked_publishers",
            [],
        ):
            self.show_warning_toast("이미 선호 출처입니다.")
            return
        self.blocked_publishers = blocked_publishers
        self.preferred_publishers = publishers
        self.save_config()
        self._reload_tabs_for_visibility_filters()
        self.show_success_toast(f"'{publisher}' 출처를 선호 목록에 추가했습니다.")

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
            title = item.get("title", "").lower()
            desc = item.get("description", "").lower()
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
                self._set_countdown_status_text("")
                self._status_bar().showMessage("⏰ 자동 새로고침 꺼짐")
                logger.info("자동 새로고침 비활성화됨")
        except Exception as exc:
            logger.error("타이머 설정 오류: %s", exc)
            traceback.print_exc()
