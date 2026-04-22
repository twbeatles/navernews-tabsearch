from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox, QWidget

from core.database import DatabaseManager
from core.logging_setup import configure_logging
from core.workers import IterativeJobWorker
from ui.news_tab_support import (
    _NewsTabActionsMixin,
    _NewsTabLoadingMixin,
    _NewsTabRenderingMixin,
    _NewsTabStateMixin,
    _NewsTabUIControlsMixin,
)

configure_logging()
logger = logging.getLogger(__name__)


class NewsTab(
    _NewsTabStateMixin,
    _NewsTabLoadingMixin,
    _NewsTabRenderingMixin,
    _NewsTabUIControlsMixin,
    _NewsTabActionsMixin,
    QWidget,
):
    """개별 뉴스 탭."""

    PAGE_SIZE = 50
    FILTER_DEBOUNCE_MS = 250
    hydration_finished = pyqtSignal(str)
    hydration_failed = pyqtSignal(str, str)

    def __init__(
        self,
        keyword: str,
        db_manager: DatabaseManager,
        theme_mode: int = 0,
        parent=None,
        *,
        defer_initial_load: bool = False,
    ):
        super().__init__(parent)
        self.keyword = keyword
        self.db = db_manager
        self.theme = theme_mode
        self.is_bookmark_tab = keyword == "북마크"

        self.news_data_cache = []
        self.filtered_data_cache = []
        self.total_api_count = 0
        self.last_update = None
        self._item_by_hash: Dict[str, Dict[str, Any]] = {}
        self._item_by_link: Dict[str, Dict[str, Any]] = {}
        self._preview_data_cache: Dict[str, str] = {}
        self._item_html_cache: Dict[Tuple[Any, ...], str] = {}
        self._css_cache_by_theme: Dict[int, str] = {}
        self._unread_count_cache = 0
        self._load_request_id = 0
        self._data_version = 0
        self._last_render_signature: Optional[Tuple[Any, ...]] = None
        self._last_loaded_scope_signature: Optional[Tuple[Any, ...]] = None
        self._last_filter_text = ""
        self._cached_badge_keyword = ""
        self._cached_badges_html = ""
        self._request_scope_signatures: Dict[int, Tuple[Any, ...]] = {}
        self._render_context_signature: Optional[Tuple[Any, ...]] = None
        self._rendered_body_html = ""
        self._rendered_item_count = 0
        self._pending_render_append_from_index: Optional[int] = None
        self._pending_render_scroll_restore: Optional[int] = None
        self._render_scheduled = False

        self._rendered_count = 0
        self._is_loading_more = False
        self._total_filtered_count = 0
        self._loaded_offset = 0
        self._pending_append_request_ids: set[int] = set()
        self._pending_scroll_restore = 0
        self._date_filter_active = False
        self._maintenance_mode_active = False
        self._is_closing = False
        self._cleanup_started = False
        self._initial_load_deferred = bool(defer_initial_load)
        self._initial_load_inflight = False
        self._initial_load_completed = False
        self._initial_request_id: Optional[int] = None
        self._cancelled_initial_request_ids: set[int] = set()

        self.worker = None
        self.job_worker: Optional[Any] = None
        self._mark_all_mode_label = "탭 전체"
        self._mark_all_maintenance_active = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_render)

        self.setup_ui()
        if self._initial_load_deferred:
            self.lbl_status.setText("⏳ 로딩 대기 중...")
        else:
            self.request_initial_hydration()


__all__ = ["IterativeJobWorker", "NewsTab", "QDesktopServices", "QMessageBox"]
