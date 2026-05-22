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


class _MainWindowActionShellMixin:
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
