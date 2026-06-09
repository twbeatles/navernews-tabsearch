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


class _MainWindowBadgeShellMixin:
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
                    return
            self._schedule_badge_refresh()
        except Exception as exc:
            logger.warning("탭 배지 업데이트 오류 (%s): %s", keyword, exc)

    def update_badge_cache_from_tab_load(self, keyword: str, unread_count: int):
        """Update badge cache from a DBWorker result without scheduling another count."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return
        count = max(0, int(unread_count or 0))
        self._badge_unread_cache[normalized_keyword] = count
        located_tab = self._find_news_tab(normalized_keyword)
        if located_tab is not None:
            tab_index, _widget = located_tab
            self._set_tab_badge_text(tab_index, normalized_keyword, count)

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
