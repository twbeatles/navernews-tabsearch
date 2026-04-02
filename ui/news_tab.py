import html
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast

from PyQt6.QtCore import QDate, Qt, QTimer, QUrl
from PyQt6.QtGui import QClipboard, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QDateEdit,
    QToolButton,
    QVBoxLayout,
    QScrollBar,
    QWidget,
)

from core.database import DatabaseManager
from core.logging_setup import configure_logging
from core.query_parser import build_fetch_key, parse_search_query, parse_tab_query
from core.text_utils import TextUtils, parse_date_string, perf_timer
from core.workers import AsyncJobWorker, DBQueryScope, DBWorker
from ui.dialogs import NoteDialog
from ui.protocols import MainWindowProtocol
from ui.styles import AppStyle, Colors
from ui.widgets import NewsBrowser, NoScrollComboBox

configure_logging()
logger = logging.getLogger(__name__)

class NewsTab(QWidget):
    """개별 뉴스 탭."""

    PAGE_SIZE = 50
    FILTER_DEBOUNCE_MS = 250
    
    def __init__(self, keyword: str, db_manager: DatabaseManager, theme_mode: int = 0, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.db = db_manager
        self.theme = theme_mode
        self.is_bookmark_tab = (keyword == "북마크")
        
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
        self._is_closing = False
        self._cleanup_started = False

        # Async DB Worker
        self.worker: Optional[DBWorker] = None
        self.job_worker: Optional[AsyncJobWorker] = None
        self._mark_all_mode_label = "탭 전체"
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_render)
        
        self.setup_ui()
        self.load_data_from_db()

    @property
    def db_keyword(self):
        """DB 저장용 키워드 (첫 번째 단어만 사용)"""
        db_keyword, _ = parse_tab_query(self.keyword)
        return db_keyword

    @property
    def exclude_words(self):
        """탭 쿼리의 제외어 목록."""
        _, exclude_words = parse_tab_query(self.keyword)
        return exclude_words

    @property
    def query_key(self):
        """Full query scope key used for DB membership."""
        search_keyword, exclude_words = parse_search_query(self.keyword)
        return build_fetch_key(search_keyword, exclude_words)

    def _current_filter_text(self) -> str:
        return self.inp_filter.text().strip()

    def _current_date_range(self) -> Tuple[Optional[str], Optional[str]]:
        if not self._date_filter_active:
            return None, None
        return (
            self.date_start.date().toString("yyyy-MM-dd"),
            self.date_end.date().toString("yyyy-MM-dd"),
        )

    def _has_active_filters(self) -> bool:
        return bool(
            self._current_filter_text()
            or self.chk_unread.isChecked()
            or self.chk_hide_dup.isChecked()
            or self._date_filter_active
        )

    def _build_query_scope(self) -> DBQueryScope:
        start_date, end_date = self._current_date_range()
        return DBQueryScope(
            keyword=self.db_keyword,
            filter_txt=self._current_filter_text(),
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab,
            only_unread=self.chk_unread.isChecked(),
            hide_duplicates=self.chk_hide_dup.isChecked(),
            exclude_words=tuple(self.exclude_words),
            start_date=start_date,
            end_date=end_date,
            query_key=None if self.is_bookmark_tab else self.query_key,
        )

    def _scope_signature(self, scope: DBQueryScope) -> Tuple[Any, ...]:
        return (
            scope.keyword,
            scope.filter_txt,
            scope.sort_mode,
            scope.only_bookmark,
            scope.only_unread,
            scope.hide_duplicates,
            scope.exclude_words,
            scope.start_date,
            scope.end_date,
            scope.query_key,
        )

    def get_all_filtered_items(self) -> List[Dict[str, Any]]:
        return self.db.fetch_news(**self._build_query_scope().fetch_kwargs())

    def _prepare_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        link = str(item.get("link", "") or "")
        title = str(item.get("title", "") or "")
        desc = str(item.get("description", "") or "")
        if not item.get("_link_hash"):
            item["_link_hash"] = hashlib.md5(link.encode()).hexdigest() if link else ""
        item["_title_lc"] = title.lower()
        item["_desc_lc"] = desc.lower()
        if not item.get("_date_fmt"):
            item["_date_fmt"] = parse_date_string(item.get("pubDate", ""))
        return item

    def _index_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        prepared = self._prepare_item(item)
        link_hash = str(prepared.get("_link_hash", "") or "")
        if link_hash:
            self._item_by_hash[link_hash] = prepared
            self._preview_data_cache[link_hash] = str(prepared.get("description", "") or "")
        normalized_link = str(prepared.get("link", "") or "").strip()
        if normalized_link:
            self._item_by_link[normalized_link] = prepared
        return prepared

    def _index_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self._index_item(item) for item in items]

    def _rebuild_item_indexes(self):
        self._item_by_hash = {}
        self._item_by_link = {}
        self._preview_data_cache = {}
        self._index_items(self.news_data_cache)
        if hasattr(self.browser, "set_preview_data"):
            self.browser.set_preview_data(dict(self._preview_data_cache))

    def _target_by_hash(self, link_hash: str) -> Optional[Dict[str, Any]]:
        return self._item_by_hash.get(link_hash)

    def _target_by_link(self, link: str) -> Optional[Dict[str, Any]]:
        normalized_link = str(link or "").strip()
        if not normalized_link:
            return None
        return self._item_by_link.get(normalized_link)

    def _discard_item_render_cache(self, link_hash: str):
        if not link_hash:
            return
        stale_keys = [cache_key for cache_key in self._item_html_cache if cache_key[3] == link_hash]
        for cache_key in stale_keys:
            self._item_html_cache.pop(cache_key, None)

    def _invalidate_item_render_cache(self, target: Dict[str, Any]):
        discard = getattr(self, "_discard_item_render_cache", None)
        if not callable(discard):
            return
        discard(str(target.get("_link_hash", "") or ""))

    def _remove_cached_target(self, target: Dict[str, Any]) -> bool:
        removed = False
        if target in self.news_data_cache:
            self.news_data_cache.remove(target)
            removed = True
        if target in self.filtered_data_cache:
            self.filtered_data_cache.remove(target)
            removed = True
        link_hash = str(target.get("_link_hash", "") or "")
        if link_hash:
            self._item_by_hash.pop(link_hash, None)
            self._preview_data_cache.pop(link_hash, None)
            self._discard_item_render_cache(link_hash)
        link = str(target.get("link", "") or "").strip()
        if link:
            self._item_by_link.pop(link, None)
        if removed and hasattr(self.browser, "set_preview_data"):
            self.browser.set_preview_data(dict(self._preview_data_cache))
        return removed

    def apply_external_item_state(
        self,
        link: str,
        *,
        is_read: Optional[bool] = None,
        is_bookmarked: Optional[bool] = None,
        notes: Optional[str] = None,
        deleted: bool = False,
    ) -> bool:
        target = self._target_by_link(link)
        if target is None:
            return False

        if deleted:
            if not target.get("is_read", 0):
                self._adjust_unread_cache(False, True)
            if self._remove_cached_target(target):
                self._refresh_after_local_change(requires_refilter=True)
                return True
            return False

        changed = False

        if is_bookmarked is not None:
            new_bookmarked = 1 if bool(is_bookmarked) else 0
            if int(target.get("is_bookmarked", 0) or 0) != new_bookmarked:
                target["is_bookmarked"] = new_bookmarked
                changed = True
            if self.is_bookmark_tab and new_bookmarked == 0:
                if not target.get("is_read", 0):
                    self._adjust_unread_cache(False, True)
                if self._remove_cached_target(target):
                    self._refresh_after_local_change(requires_refilter=True)
                    return True

        if is_read is not None:
            was_read = bool(target.get("is_read", 0))
            now_read = bool(is_read)
            if was_read != now_read:
                target["is_read"] = 1 if now_read else 0
                self._adjust_unread_cache(was_read, now_read)
                changed = True
            if self.chk_unread.isChecked() and now_read:
                if self._remove_cached_target(target):
                    self._refresh_after_local_change(requires_refilter=True)
                    return True

        if notes is not None:
            new_note = str(notes)
            if str(target.get("notes", "") or "") != new_note:
                target["notes"] = new_note
                changed = True

        if changed:
            NewsTab._invalidate_item_render_cache(cast(Any, self), target)
            self._refresh_after_local_change()
        return changed

    def _main_window(self) -> Optional[MainWindowProtocol]:
        candidate = self.window()
        if candidate is None:
            return None
        required_attrs = (
            "update_tab_badge",
            "refresh_bookmark_tab",
            "show_toast",
            "show_warning_toast",
            "sync_tab_load_more_state",
            "maybe_show_query_refresh_hint",
        )
        if not all(hasattr(candidate, attr) for attr in required_attrs):
            return None
        return cast(MainWindowProtocol, candidate)

    def _browser_scroll_bar(self) -> QScrollBar:
        scroll_bar = self.browser.verticalScrollBar()
        if scroll_bar is None:
            raise RuntimeError("News browser scrollbar is unavailable")
        return scroll_bar

    def _detach_worker_signals(self, worker: Any, signal_names: Tuple[str, ...]) -> None:
        for signal_name in signal_names:
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect()
            except Exception:
                pass

    def _clipboard(self) -> QClipboard:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Clipboard is unavailable")
        return clipboard

    def _schedule_render(
        self,
        *,
        append_from_index: Optional[int] = None,
        restore_scroll: Optional[int] = None,
    ):
        if append_from_index is not None:
            if self._pending_render_append_from_index is None:
                self._pending_render_append_from_index = append_from_index
            else:
                self._pending_render_append_from_index = min(
                    self._pending_render_append_from_index,
                    append_from_index,
                )
        else:
            self._pending_render_append_from_index = None

        if restore_scroll is not None:
            self._pending_render_scroll_restore = restore_scroll

        if self._render_scheduled:
            return

        self._render_scheduled = True
        self._render_timer.start(0)

    def _render_context_key(self, filter_word: str) -> Tuple[Any, ...]:
        return (
            self.theme,
            self.keyword,
            filter_word,
            self._total_filtered_count,
            self.is_bookmark_tab,
        )

    def _build_document_html(self, body_html: str, remaining_html: str = "") -> str:
        is_dark = self.theme == 1
        if self.theme not in self._css_cache_by_theme:
            colors = Colors.get_html_colors(is_dark)
            self._css_cache_by_theme[self.theme] = AppStyle.HTML_TEMPLATE.format(**colors)
        css = self._css_cache_by_theme[self.theme]
        return f"<html><head><meta charset='utf-8'>{css}</head><body>{body_html}{remaining_html}</body></html>"

    def _empty_state_html(self) -> str:
        if self.is_bookmark_tab:
            msg = "<div class='empty-state-title'>⭐ 북마크</div>북마크된 기사가 없습니다.<br><br>기사 카드의 [북마크] 버튼을 눌러<br>중요한 기사를 저장하세요."
        elif self.chk_unread.isChecked():
            msg = "<div class='empty-state-title'>✓ 완료!</div>모든 기사를 읽었습니다."
        else:
            msg = "<div class='empty-state-title'>📰 뉴스</div>표시할 기사가 없습니다.<br><br>새로고침 버튼을 눌러 최신 뉴스를 가져오세요."
        return f"<div class='empty-state'>{msg}</div>"

    def _item_render_cache_key(self, item: Dict[str, Any], filter_word: str) -> Tuple[Any, ...]:
        return (
            self.theme,
            filter_word,
            self.keyword,
            str(item.get("_link_hash", "") or ""),
            int(item.get("is_read", 0) or 0),
            int(item.get("is_bookmarked", 0) or 0),
            int(item.get("is_duplicate", 0) or 0),
            str(item.get("notes", "") or ""),
            str(item.get("title", "") or ""),
            str(item.get("description", "") or ""),
            str(item.get("publisher", "") or ""),
            str(item.get("_date_fmt", "") or ""),
        )

    def _flush_render(self):
        self._render_scheduled = False
        with perf_timer("ui.render_html", f"kw={self.keyword}|rows={len(self.filtered_data_cache)}"):
            filter_word = self._current_filter_text()
            render_signature = (
                self.theme,
                filter_word,
                len(self.filtered_data_cache),
                self._total_filtered_count,
                self._data_version,
            )
            restore_scroll = self._pending_render_scroll_restore
            if restore_scroll is None:
                restore_scroll = self._browser_scroll_bar().value()
            append_from_index = self._pending_render_append_from_index
            self._pending_render_scroll_restore = None
            self._pending_render_append_from_index = None

            if render_signature == self._last_render_signature:
                self.update_status_label()
                if restore_scroll > 0:
                    QTimer.singleShot(0, lambda: self._browser_scroll_bar().setValue(restore_scroll))
                return

            if not self.filtered_data_cache:
                body_html = self._empty_state_html()
                self._rendered_body_html = body_html
                self._rendered_item_count = 0
                self._render_context_signature = self._render_context_key(filter_word)
            else:
                base_badges_html = self._get_keyword_badges_html()
                render_context = self._render_context_key(filter_word)
                can_append = (
                    append_from_index is not None
                    and append_from_index == self._rendered_item_count
                    and self._render_context_signature == render_context
                    and 0 <= append_from_index <= len(self.filtered_data_cache)
                )
                if can_append:
                    new_fragments = [
                        self._render_single_item(item, filter_word, base_badges_html)
                        for item in self.filtered_data_cache[append_from_index:]
                    ]
                    self._rendered_body_html += "".join(new_fragments)
                else:
                    self._rendered_body_html = "".join(
                        self._render_single_item(item, filter_word, base_badges_html)
                        for item in self.filtered_data_cache
                    )
                self._rendered_item_count = len(self.filtered_data_cache)
                self._render_context_signature = render_context
                body_html = self._rendered_body_html

            remaining = max(0, self._total_filtered_count - len(self.filtered_data_cache))
            footer_html = self._get_load_more_html(remaining) if remaining > 0 else ""
            self.browser.setHtml(self._build_document_html(body_html, footer_html))
            self._last_render_signature = render_signature

            if restore_scroll > 0:
                QTimer.singleShot(0, lambda: self._browser_scroll_bar().setValue(restore_scroll))
            self.update_status_label()

    def _refresh_after_local_change(self, requires_refilter: bool = False):
        self._data_version += 1
        self._last_render_signature = None
        if requires_refilter:
            self.load_data_from_db()
        else:
            self._schedule_render()

    def _notify_badge_change(self):
        parent = self._main_window()
        if parent is not None:
            try:
                parent.update_tab_badge(self.keyword)
            except Exception:
                pass

    def _recount_unread_cache(self):
        self._unread_count_cache = sum(1 for item in self.news_data_cache if not item.get("is_read", 0))

    def _adjust_unread_cache(self, was_read: bool, now_read: bool):
        if was_read == now_read:
            return
        if was_read and not now_read:
            self._unread_count_cache += 1
        elif (not was_read) and now_read:
            self._unread_count_cache = max(0, self._unread_count_cache - 1)

    def _get_keyword_badges_html(self) -> str:
        if self.is_bookmark_tab or not self.keyword:
            return ""
        if self._cached_badge_keyword == self.keyword:
            return self._cached_badges_html
        badges = []
        for kw in self.keyword.split():
            if kw.startswith("-"):
                continue
            badges.append(f"<span class='keyword-tag'>{html.escape(kw)}</span>")
        self._cached_badge_keyword = self.keyword
        self._cached_badges_html = "".join(badges)
        return self._cached_badges_html

    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # --- 상단 필터 카드 ---
        filter_card = QFrame()
        filter_card.setObjectName("FilterCard")
        is_dark = (self.theme == 1)
        filter_card.setStyleSheet(f"""
            QFrame#FilterCard {{
                background-color: {Colors.DARK_CARD_BG if is_dark else Colors.LIGHT_CARD_BG};
                border: 1px solid {Colors.DARK_BORDER if is_dark else Colors.LIGHT_BORDER};
                border-radius: 10px;
                padding: 8px;
            }}
        """)
        
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(8)
        
        # 1열: 검색/정렬
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)
        
        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)
        
        # 필터 디바운싱 타이머 (300ms)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self._apply_filter_debounced)
        self.inp_filter.textChanged.connect(self._on_filter_changed)
        
        self.combo_sort = NoScrollComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self.load_data_from_db)
        
        row1_layout.addWidget(self.inp_filter, 4)
        row1_layout.addWidget(self.combo_sort, 1)
        
        filter_layout.addLayout(row1_layout)
        
        # 2열: 옵션 체크박스 + 날짜 필터
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(12)
        
        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self.load_data_from_db)
        
        self.chk_hide_dup = QCheckBox("중복 숨김")
        self.chk_hide_dup.stateChanged.connect(self.load_data_from_db)
        
        row2_layout.addWidget(self.chk_unread)
        row2_layout.addWidget(self.chk_hide_dup)
        
        self.btn_date_toggle = QToolButton()
        self.btn_date_toggle.setText("📅 기간")
        self.btn_date_toggle.setCheckable(True)
        self.btn_date_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_date_toggle.toggled.connect(self._toggle_date_filter)
        
        self.date_container = QWidget()
        date_inner_layout = QHBoxLayout(self.date_container)
        date_inner_layout.setContentsMargins(0, 0, 0, 0)
        date_inner_layout.setSpacing(4)
        
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setMinimumWidth(120)
        self.date_start.setDate(QDate.currentDate().addDays(-7))
        self.date_start.dateChanged.connect(self._on_date_start_changed)
        
        self.lbl_tilde = QLabel("~")
        
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setMinimumWidth(120)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.dateChanged.connect(self._on_date_end_changed)

        self.btn_apply_date = QPushButton("적용")
        self.btn_apply_date.clicked.connect(self._apply_date_filter)

        self.btn_clear_date = QPushButton("해제")
        self.btn_clear_date.clicked.connect(self._clear_date_filter)

        date_inner_layout.addWidget(self.date_start)
        date_inner_layout.addWidget(self.lbl_tilde)
        date_inner_layout.addWidget(self.date_end)
        date_inner_layout.addWidget(self.btn_apply_date)
        date_inner_layout.addWidget(self.btn_clear_date)
        
        row2_layout.addWidget(self.btn_date_toggle)
        row2_layout.addWidget(self.date_container)
        row2_layout.addStretch()
        
        filter_layout.addLayout(row2_layout)

        # 초기에는 날짜 필터 숨김
        self.date_container.setVisible(False)
        self._update_date_toggle_style(False)
        self._refresh_date_filter_controls()
        
        layout.addWidget(filter_card)
        
        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_link_clicked)
        self.browser.action_triggered.connect(self.on_browser_action)
        layout.addWidget(self.browser)
        
        btm_layout = QHBoxLayout()
        
        self.btn_load = QPushButton("📥 더 불러오기")
        self.btn_read_all = QPushButton("✓ 모두 읽음")
        self.btn_top = QPushButton("⬆ 맨 위로")
        self.lbl_status = QLabel("대기 중")
        
        if self.is_bookmark_tab:
            self.btn_load.hide()
        
        btm_layout.addWidget(self.btn_load)
        btm_layout.addWidget(self.btn_read_all)
        btm_layout.addWidget(self.btn_top)
        btm_layout.addStretch()
        btm_layout.addWidget(self.lbl_status)
        layout.addLayout(btm_layout)

        self.btn_top.clicked.connect(lambda: self._browser_scroll_bar().setValue(0))
        self.btn_read_all.clicked.connect(self.mark_all_read)
    
    def _toggle_date_filter(self, checked: bool):
        """날짜 필터 표시/숨김 토글"""
        self.date_container.setVisible(checked)
        if checked:
            self.date_container.adjustSize()
            self.date_container.updateGeometry()
            self.date_container.repaint()
            self._refresh_date_filter_controls()
            return

        was_active = self._date_filter_active
        self._date_filter_active = False
        self._refresh_date_filter_controls()
        if was_active:
            self.load_data_from_db()
        else:
            self.update_status_label()

    def _update_date_toggle_style(self, checked: bool):
        """날짜 토글 버튼 스타일 업데이트"""
        is_dark = (self.theme == 1)

        if is_dark:
            btn_active_bg = Colors.DARK_PRIMARY_LIGHT
            btn_active_border = Colors.DARK_PRIMARY
            btn_active_text = Colors.DARK_TEXT
            btn_inactive_border = Colors.DARK_BORDER
            btn_inactive_text = Colors.DARK_TEXT_MUTED
            date_bg = "#334155" if checked else "#1E293B"
            date_text = Colors.DARK_TEXT
            date_border = Colors.DARK_PRIMARY if checked else Colors.DARK_BORDER
            tilde_text = Colors.DARK_TEXT_MUTED
        else:
            btn_active_bg = Colors.LIGHT_PRIMARY_LIGHT
            btn_active_border = Colors.LIGHT_PRIMARY
            btn_active_text = "#4338ca"
            btn_inactive_border = Colors.LIGHT_BORDER
            btn_inactive_text = Colors.LIGHT_TEXT_MUTED
            date_bg = "#EEF2FF" if checked else "#FFFFFF"
            date_text = Colors.LIGHT_TEXT
            date_border = Colors.LIGHT_PRIMARY if checked else Colors.LIGHT_BORDER
            tilde_text = Colors.LIGHT_TEXT_MUTED

        if checked:
            btn_style = (
                f"background: {btn_active_bg}; border: 1px solid {btn_active_border}; "
                f"border-radius: 4px; padding: 4px; color: {btn_active_text};"
            )
        else:
            btn_style = (
                f"background: transparent; border: 1px solid {btn_inactive_border}; "
                f"border-radius: 4px; padding: 4px; color: {btn_inactive_text};"
            )
        self.btn_date_toggle.setStyleSheet(btn_style)

        date_edit_style = (
            "QDateEdit {"
            f"background-color: {date_bg};"
            f"color: {date_text};"
            f"border: 1px solid {date_border};"
            "border-radius: 4px;"
            "padding: 2px 6px;"
            "}"
            "QDateEdit:focus {"
            f"border: 1px solid {date_border};"
            "}"
        )
        if (
            hasattr(self, "date_start")
            and hasattr(self, "date_end")
            and hasattr(self, "lbl_tilde")
        ):
            self.date_start.setStyleSheet(date_edit_style)
            self.date_end.setStyleSheet(date_edit_style)
            self.lbl_tilde.setStyleSheet(f"color: {tilde_text};")

    def _refresh_date_filter_controls(self):
        active = bool(self._date_filter_active)
        self.btn_date_toggle.setText("📅 기간 적용 중" if active else "📅 기간")
        self.btn_apply_date.setEnabled(self.btn_date_toggle.isChecked())
        self.btn_clear_date.setEnabled(active)
        self._update_date_toggle_style(active)

    def _set_date_edit_value(self, widget: QDateEdit, date_value: QDate):
        widget.blockSignals(True)
        try:
            widget.setDate(date_value)
        finally:
            widget.blockSignals(False)

    def _normalize_date_inputs(self):
        start_date = self.date_start.date()
        end_date = self.date_end.date()
        if start_date > end_date:
            self._set_date_edit_value(self.date_end, start_date)
        return self.date_start.date(), self.date_end.date()

    def _on_date_start_changed(self, selected_date: QDate):
        if selected_date > self.date_end.date():
            self._set_date_edit_value(self.date_end, selected_date)
        if self._date_filter_active:
            self.load_data_from_db()

    def _on_date_end_changed(self, selected_date: QDate):
        if selected_date < self.date_start.date():
            self._set_date_edit_value(self.date_start, selected_date)
        if self._date_filter_active:
            self.load_data_from_db()

    def _apply_date_filter(self):
        self._normalize_date_inputs()
        self._date_filter_active = True
        self._refresh_date_filter_controls()
        self.load_data_from_db()

    def _clear_date_filter(self):
        if not self._date_filter_active:
            self.update_status_label()
            return
        self._date_filter_active = False
        self._refresh_date_filter_controls()
        self.load_data_from_db()

    def _on_filter_changed(self):
        """필터 입력 변경 시 디바운싱 타이머 시작"""
        self.filter_timer.stop()
        self.filter_timer.start(self.FILTER_DEBOUNCE_MS)
    
    def _apply_filter_debounced(self):
        """디바운싱된 필터 적용"""
        self.apply_filter()

    def load_data_from_db(self, append: bool = False):
        """DB에서 현재 필터 범위의 페이지를 로드한다."""
        if getattr(self, "_is_closing", False):
            return
        with perf_timer("ui.load_data_from_db", f"kw={self.keyword}|append={int(append)}"):
            if self.worker and self.worker.isRunning():
                self._detach_worker_signals(self.worker, ("finished", "error"))
                self.worker.stop()
                if not self.worker.wait(150):
                    logger.warning(f"DBWorker wait timeout: {self.keyword}")

            if not append:
                self._loaded_offset = 0
                self._is_loading_more = False
            elif self._is_loading_more:
                return

            self._load_request_id += 1
            current_request_id = self._load_request_id
            if append:
                self._pending_append_request_ids.add(current_request_id)
                self._pending_scroll_restore = self._browser_scroll_bar().value()
                self._is_loading_more = True
            else:
                self._pending_append_request_ids.clear()
                self._pending_scroll_restore = 0

            self.lbl_status.setText("⏳ 데이터 로딩 중...")
            self.btn_load.setEnabled(False)

            scope = self._build_query_scope()
            self._request_scope_signatures[current_request_id] = self._scope_signature(scope)
            offset = self._loaded_offset if append else 0
            self.worker = DBWorker(
                self.db,
                scope=scope,
                limit=self.PAGE_SIZE,
                offset=offset,
                include_total=not append,
                known_total_count=self._total_filtered_count if append else None,
            )
            self.worker.finished.connect(
                lambda data, total_count, rid=current_request_id, worker_ref=self.worker: self.on_data_loaded(
                    data,
                    total_count,
                    request_id=rid,
                    unread_count=getattr(worker_ref, "last_unread_count", None),
                )
            )
            self.worker.error.connect(lambda err_msg, rid=current_request_id: self.on_data_error(err_msg, rid))
            self.worker.start()

    def on_data_loaded(
        self,
        data,
        total_count,
        request_id: Optional[int] = None,
        unread_count: Optional[int] = None,
    ):
        """데이터 로드 완료 시 호출"""
        if getattr(self, "_is_closing", False):
            if request_id is not None:
                self._request_scope_signatures.pop(request_id, None)
                self._pending_append_request_ids.discard(request_id)
            return
        if request_id is not None and request_id != self._load_request_id:
            self._request_scope_signatures.pop(request_id, None)
            logger.info(f"PERF|ui.on_data_loaded.stale|0.00ms|kw={self.keyword}|rid={request_id}")
            return

        with perf_timer("ui.on_data_loaded", f"kw={self.keyword}|rows={len(data)}"):
            scope_signature = None
            if request_id is not None:
                scope_signature = self._request_scope_signatures.pop(request_id, None)
            is_append = bool(request_id in self._pending_append_request_ids)
            if request_id is not None:
                self._pending_append_request_ids.discard(request_id)
            if scope_signature is None:
                scope_signature = self._scope_signature(self._build_query_scope())

            append_from_index: Optional[int] = None
            prepared_rows = [dict(item) for item in data]
            if is_append and scope_signature == self._last_loaded_scope_signature:
                append_from_index = len(self.news_data_cache)
                prepared_rows = self._index_items(prepared_rows)
                self.news_data_cache.extend(prepared_rows)
                if hasattr(self.browser, "set_preview_data"):
                    self.browser.set_preview_data(dict(self._preview_data_cache))
            else:
                prepared_rows = [self._prepare_item(item) for item in prepared_rows]
                self.news_data_cache = prepared_rows
                self._loaded_offset = 0
                self._rebuild_item_indexes()

            self.filtered_data_cache = list(self.news_data_cache)
            self._loaded_offset = len(self.news_data_cache)
            self._rendered_count = len(self.filtered_data_cache)
            self._total_filtered_count = int(total_count or 0)
            self._last_loaded_scope_signature = scope_signature
            self._last_filter_text = self._current_filter_text().lower()
            if unread_count is None:
                self._recount_unread_cache()
            else:
                self._unread_count_cache = max(0, int(unread_count or 0))
            self._data_version += 1
            self._last_render_signature = None
            self._is_loading_more = False
            self.btn_load.setEnabled(True)

            if self.total_api_count <= 0 and self._total_filtered_count > self.total_api_count:
                self.total_api_count = self._total_filtered_count

            restore_scroll = None
            if is_append and self._pending_scroll_restore > 0:
                restore_scroll = self._pending_scroll_restore
            self._pending_scroll_restore = 0
            self._schedule_render(
                append_from_index=append_from_index,
                restore_scroll=restore_scroll,
            )

            parent = self._main_window()
            if parent is not None:
                parent.sync_tab_load_more_state(self.keyword)
                if not self.news_data_cache and not self.is_bookmark_tab:
                    parent.maybe_show_query_refresh_hint(self.keyword)

    def on_data_error(self, err_msg, request_id: Optional[int] = None):
        """데이터 로드 오류 시 호출"""
        if getattr(self, "_is_closing", False):
            if request_id is not None:
                self._request_scope_signatures.pop(request_id, None)
                self._pending_append_request_ids.discard(request_id)
            return
        if request_id is not None and request_id != self._load_request_id:
            self._request_scope_signatures.pop(request_id, None)
            return
        if request_id is not None:
            self._pending_append_request_ids.discard(request_id)
            self._request_scope_signatures.pop(request_id, None)
        self._is_loading_more = False
        self._pending_scroll_restore = 0
        self.lbl_status.setText(f"⚠️ 오류: {err_msg}")
        self.btn_load.setEnabled(True)

    def apply_filter(self):
        """필터 변경 시 DB 기반으로 첫 페이지부터 다시 조회한다."""
        with perf_timer("ui.apply_filter", f"kw={self.keyword}|rows={len(self.news_data_cache)}"):
            filter_txt = self._current_filter_text()
            if filter_txt:
                self.inp_filter.setObjectName("FilterActive")
            else:
                self.inp_filter.setObjectName("")
            self.inp_filter.setStyle(self.inp_filter.style())

            filter_txt_lc = filter_txt.lower()
            if filter_txt_lc == self._last_filter_text and self._loaded_offset <= self.PAGE_SIZE:
                self.update_status_label()
                return

            self._last_filter_text = filter_txt_lc
            self.load_data_from_db(append=False)

    def _render_single_item(self, item: Dict[str, Any], filter_word: str, base_badges_html: str) -> str:
        """단일 뉴스 아이템 HTML 렌더링"""
        link_hash = str(
            item.get("_link_hash")
            or (hashlib.md5(str(item.get("link", "") or "").encode()).hexdigest() if item.get("link") else "")
        )
        item["_link_hash"] = link_hash
        cache_key = self._item_render_cache_key(item, filter_word)
        cached_html = self._item_html_cache.get(cache_key)
        if cached_html is not None:
            return cached_html

        is_read_cls = " read" if item.get("is_read", 0) else ""
        is_dup_cls = " duplicate" if item.get("is_duplicate", 0) else ""
        title_pfx = "⭐ " if item.get("is_bookmarked", 0) else ""

        item_link = item.get("link", "")
        item_title = item.get("title", "(제목 없음)")
        item_desc = item.get("description", "")

        if filter_word:
            title = TextUtils.highlight_text(item_title, filter_word)
            desc = TextUtils.highlight_text(item_desc, filter_word)
        else:
            title = html.escape(item_title)
            desc = html.escape(item_desc)

        bk_txt = "북마크 해제" if item.get("is_bookmarked", 0) else "북마크"
        bk_col = "#DC3545" if item.get("is_bookmarked", 0) else "#17A2B8"

        date_str = item.get("_date_fmt") or parse_date_string(item.get("pubDate", ""))
        item["_date_fmt"] = date_str

        has_note = bool(item.get("notes") and str(item.get("notes", "")).strip())
        note_indicator = " 📝" if has_note else ""

        actions = f"""
            <a href='app://share/{link_hash}'>공유</a>
            <a href='app://ext/{link_hash}'>외부</a>
            <a href='app://note/{link_hash}'>메모{note_indicator}</a>
        """
        if item.get("is_read", 0):
            actions += f"<a href='app://unread/{link_hash}'>안읽음</a>"
        actions += f"<a href='app://bm/{link_hash}' style='color:{bk_col}'>{bk_txt}</a>"

        badges = base_badges_html

        if item.get("is_duplicate", 0):
            badges += "<span class='duplicate-badge'>유사</span>"

        rendered = f"""
        <div class="news-item{is_read_cls}{is_dup_cls}">
            <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
            <div class="meta-info">
                <span class="meta-left">📰 {item.get('publisher', '출처없음')} · {date_str} {badges}</span>
                <span class="actions">{actions}</span>
            </div>
            <div class="description">{desc}</div>
        </div>
        """
        self._item_html_cache[cache_key] = rendered
        return rendered

    def _get_load_more_html(self, remaining: int) -> str:
        """더 보기 버튼 HTML"""
        return f"""
        <div class="load-more-container" style="text-align: center; padding: 20px;">
            <a href="app://load_more" style="
                display: inline-block;
                padding: 12px 30px;
                background: linear-gradient(135deg, #007AFF, #00C7BE);
                color: white;
                text-decoration: none;
                border-radius: 25px;
                font-weight: bold;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            ">더 보기 ({remaining}개 남음)</a>
        </div>
        """

    def render_html(self):
        """Schedule an HTML render on the next event-loop tick."""
        self._schedule_render()

    def append_items(self):
        """다음 DB 페이지를 로드한다."""
        if self._is_loading_more:
            return
        if len(self.filtered_data_cache) >= self._total_filtered_count:
            return
        self.load_data_from_db(append=True)


    def update_status_label(self):
        """상태 레이블 업데이트 - 캐시 기반 최적화"""
        loaded_count = len(self.filtered_data_cache)
        total_filtered = max(self._total_filtered_count, loaded_count)
        active_start_date, active_end_date = self._current_date_range()

        if not self.is_bookmark_tab:
            unread = self._unread_count_cache
            overall_total = max(int(self.total_api_count or 0), total_filtered)
            msg = f"'{self.keyword}': 총 {overall_total}개"

            if self._has_active_filters():
                msg += f" | 필터링: {total_filtered}개"
            else:
                msg += f" | {loaded_count}개"

            if loaded_count < total_filtered:
                msg += f" (표시: {loaded_count}개)"

            if active_start_date and active_end_date:
                msg += f" | 기간: {active_start_date}~{active_end_date}"

            if unread > 0:
                msg += f" | 안 읽음: {unread}개"
            if self.last_update:
                msg += f" | 업데이트: {self.last_update}"
            self.lbl_status.setText(msg)
        else:
            if self._has_active_filters():
                status_text = f"⭐ 북마크 {total_filtered}개"
            else:
                status_text = f"⭐ 북마크 {loaded_count}개"

            if loaded_count < total_filtered:
                status_text += f" (표시: {loaded_count}개)"

            if active_start_date and active_end_date:
                status_text += f" | 기간: {active_start_date}~{active_end_date}"

            self.lbl_status.setText(status_text)


    def _open_article_url(
        self,
        link: str,
        *,
        failure_message: str,
    ) -> bool:
        normalized_link = str(link or "").strip()
        if not normalized_link:
            self._emit_local_action_failure(failure_message)
            return False

        url = QUrl.fromUserInput(normalized_link)
        if not url.isValid():
            self._emit_local_action_failure(failure_message)
            return False

        if not QDesktopServices.openUrl(url):
            self._emit_local_action_failure(failure_message)
            return False

        return True

    def _open_external_link_and_mark_read(self, target: Dict[str, Any]):
        link = target.get("link", "")
        if not link:
            return

        if not self._open_article_url(
            str(link),
            failure_message="브라우저에서 기사를 열지 못했습니다. 기본 브라우저 설정을 확인해주세요.",
        ):
            return
        self._set_read_state(
            target,
            True,
            failure_message="읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
        )

    def _emit_local_action_failure(self, failure_message: str) -> None:
        if not failure_message:
            return
        self.lbl_status.setText(f"⚠️ {failure_message}")
        parent = self._main_window()
        if parent is not None:
            parent.show_warning_toast(failure_message)

    def _set_read_state(
        self,
        target: Dict[str, Any],
        new_read: bool,
        failure_message: str = "",
    ) -> bool:
        """읽음 상태를 DB와 UI에 일관되게 반영한다."""
        link = target.get("link", "")
        if not link:
            return False

        was_read = bool(target.get("is_read", 0))
        now_read = bool(new_read)
        if was_read == now_read:
            return True

        if not self.db.update_status(link, "is_read", 1 if now_read else 0):
            self._emit_local_action_failure(failure_message)
            return False

        target["is_read"] = 1 if now_read else 0
        NewsTab._invalidate_item_render_cache(cast(Any, self), target)
        self._adjust_unread_cache(was_read, now_read)
        if self.chk_unread.isChecked() and now_read:
            self._remove_cached_target(target)
            self._refresh_after_local_change(requires_refilter=True)
        else:
            self._refresh_after_local_change()
        self._notify_badge_change()
        parent = self._main_window()
        if parent is not None and hasattr(parent, "sync_link_state_across_tabs"):
            parent.sync_link_state_across_tabs(self, link, is_read=now_read)
        return True

    def _set_bookmark_state(
        self,
        target: Dict[str, Any],
        new_bookmarked: bool,
        *,
        failure_message: str = "북마크 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
        success_message: str = "",
    ) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False

        new_value = 1 if bool(new_bookmarked) else 0
        if int(target.get("is_bookmarked", 0) or 0) == new_value:
            return True

        if not self.db.update_status(link, "is_bookmarked", new_value):
            self._emit_local_action_failure(failure_message)
            return False

        target["is_bookmarked"] = new_value
        NewsTab._invalidate_item_render_cache(cast(Any, self), target)

        requires_refilter = False
        if self.is_bookmark_tab and new_value == 0:
            if not target.get("is_read", 0):
                self._adjust_unread_cache(False, True)
            self._remove_cached_target(target)
            requires_refilter = True

        self._refresh_after_local_change(requires_refilter=requires_refilter)
        self._notify_badge_change()
        parent = self._main_window()
        if parent is not None:
            if hasattr(parent, "sync_link_state_across_tabs"):
                parent.sync_link_state_across_tabs(
                    self,
                    link,
                    is_bookmarked=bool(new_value),
                )
            if success_message:
                parent.show_toast(success_message)
        return True

    def _save_note_state(
        self,
        target: Dict[str, Any],
        note: str,
        *,
        failure_message: str = "메모를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
        success_message: str = "📝 메모가 저장되었습니다.",
    ) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False

        new_note = str(note or "")
        if not self.db.save_note(link, new_note):
            self._emit_local_action_failure(failure_message)
            return False

        target["notes"] = new_note
        NewsTab._invalidate_item_render_cache(cast(Any, self), target)
        self._refresh_after_local_change()
        parent = self._main_window()
        if parent is not None:
            if hasattr(parent, "sync_link_state_across_tabs"):
                parent.sync_link_state_across_tabs(self, link, notes=new_note)
            if success_message:
                parent.show_toast(success_message)
        return True

    def _edit_note_for_target(self, target: Dict[str, Any]) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False
        current_note = self.db.get_note(link)
        dialog = NoteDialog(current_note, self)
        if not dialog.exec():
            return False
        return self._save_note_state(target, dialog.get_note())

    def _delete_target(self, target: Dict[str, Any]) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False

        reply = QMessageBox.question(
            self,
            "삭제",
            "이 기사를 목록에서 삭제하시겠습니까?\n(DB에서 완전히 삭제됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        try:
            if not self.db.delete_link(link):
                QMessageBox.warning(self, "오류", "삭제 대상 기사를 찾을 수 없습니다.")
                return False
            if not target.get("is_read", 0):
                self._adjust_unread_cache(False, True)
            self._remove_cached_target(target)
            self._refresh_after_local_change(requires_refilter=True)
            self._notify_badge_change()
            parent = self._main_window()
            if parent is not None:
                if hasattr(parent, "sync_link_state_across_tabs"):
                    parent.sync_link_state_across_tabs(self, link, deleted=True)
                parent.show_toast("🗑 삭제되었습니다.")
            return True
        except Exception as e:
            QMessageBox.warning(self, "오류", f"삭제 실패: {e}")
            return False

    def on_link_clicked(self, url: QUrl):
        """링크 클릭 처리"""
        scheme = url.scheme()
        if scheme != "app":
            return

        action = url.host()
        link_hash = url.path().lstrip('/')

        if action == "load_more":
            self.append_items()
            return

        target = self._target_by_hash(link_hash)
        if not target:
            return

        link = target.get("link", "")

        if action == "open":
            if not self._open_article_url(
                str(link),
                failure_message="기사를 열지 못했습니다. 링크 또는 브라우저 설정을 확인해주세요.",
            ):
                return
            self._set_read_state(
                target,
                True,
                failure_message="읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
            )

        elif action == "bm":
            new_val = not bool(target.get("is_bookmarked", 0))
            message = "⭐ 북마크에 추가되었습니다." if new_val else "북마크가 해제되었습니다."
            self._set_bookmark_state(target, new_val, success_message=message)

        elif action == "share":
            clip = f"{target.get('title', '')}\n{target.get('link', '')}"
            self._clipboard().setText(clip)
            parent = self._main_window()
            if parent is not None:
                parent.show_toast("📋 링크와 제목이 복사되었습니다!")
            return

        elif action == "unread":
            if self._set_read_state(
                target,
                False,
                failure_message="안 읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
            ):
                parent = self._main_window()
                if parent is not None:
                    parent.show_toast("📖 안 읽음으로 표시되었습니다.")

        elif action == "note":
            self._edit_note_for_target(target)
            return

        elif action == "ext":
            self._open_external_link_and_mark_read(target)
            return

    def mark_all_read(self):
        """모두 읽음으로 표시 (비동기)"""
        if getattr(self, "_is_closing", False):
            return
        mode_dialog = QMessageBox(self)
        mode_dialog.setIcon(QMessageBox.Icon.Question)
        mode_dialog.setWindowTitle("모두 읽음으로 표시")
        mode_dialog.setText("읽음 처리 범위를 선택하세요.")
        mode_dialog.setInformativeText(
            "현재 표시 결과는 필터/기간/제외어 조건으로 계산된 전체 결과입니다."
        )

        btn_visible_only = mode_dialog.addButton("현재 표시 결과만", QMessageBox.ButtonRole.AcceptRole)
        btn_tab_all = mode_dialog.addButton("탭 전체", QMessageBox.ButtonRole.ActionRole)
        mode_dialog.addButton(QMessageBox.StandardButton.Cancel)
        mode_dialog.setDefaultButton(btn_visible_only)
        mode_dialog.exec()

        clicked = mode_dialog.clickedButton()
        if clicked not in (btn_visible_only, btn_tab_all):
            return

        self.lbl_status.setText("⏳ 처리 중...")
        self.btn_read_all.setEnabled(False)
        start_date, end_date = self._current_date_range()

        if clicked == btn_visible_only:
            if self._total_filtered_count <= 0:
                self.btn_read_all.setEnabled(True)
                self.lbl_status.setText("읽음 처리할 기사가 없습니다.")
                parent = self._main_window()
                if parent is not None:
                    parent.show_toast("읽음 처리할 기사가 없습니다.")
                return

            self._mark_all_mode_label = "현재 표시 결과"
            self.job_worker = AsyncJobWorker(
                self.db.mark_query_as_read,
                self.db_keyword,
                self.exclude_words,
                self.is_bookmark_tab,
                self._current_filter_text(),
                self.chk_hide_dup.isChecked(),
                start_date,
                end_date,
                query_key=self.query_key,
            )
        else:
            self._mark_all_mode_label = "탭 전체"
            self.job_worker = AsyncJobWorker(
                self.db.mark_query_as_read,
                self.db_keyword,
                self.exclude_words,
                self.is_bookmark_tab,
                "",
                False,
                None,
                None,
                query_key=self.query_key,
            )

        self.job_worker.finished.connect(self._on_mark_all_read_done)
        self.job_worker.error.connect(self._on_mark_all_read_error)
        self.job_worker.start()
             
    def _on_mark_all_read_done(self, count):
        """모두 읽음 처리 완료"""
        if getattr(self, "_is_closing", False):
            return
        self.btn_read_all.setEnabled(True)
        parent = self._main_window()
        if parent is not None:
            if hasattr(parent, "on_database_maintenance_completed"):
                parent.on_database_maintenance_completed("mark_all_read", int(count or 0))
            mode_label = getattr(self, "_mark_all_mode_label", "선택 범위")
            parent.show_toast(f"✓ {mode_label} {count}개의 기사를 읽음으로 표시했습니다.")
        self.load_data_from_db()
            
    def _on_mark_all_read_error(self, err_msg):
        """모두 읽음 처리 오류"""
        if getattr(self, "_is_closing", False):
            return
        self.btn_read_all.setEnabled(True)
        self.lbl_status.setText("오류 발생")
        QMessageBox.critical(self, "오류", f"처리 중 오류가 발생했습니다:\n\n{err_msg}")

    def update_timestamp(self):
        """업데이트 시간 갱신"""
        self.last_update = datetime.now().strftime('%H:%M:%S')


    def on_browser_action(self, action, link_hash):
        """브라우저 컨텍스트 메뉴 액션 처리"""
        target = self._target_by_hash(link_hash)
        if not target:
            return

        link = target.get("link", "")

        if action == "ext":
            self._open_external_link_and_mark_read(target)

        elif action == "share":
            clip = f"{target.get('title', '')}\n{target.get('link', '')}"
            self._clipboard().setText(clip)
            parent = self._main_window()
            if parent is not None:
                parent.show_toast("📋 링크와 제목이 복사되었습니다!")

        elif action == "bm":
            new_val = not bool(target.get("is_bookmarked", 0))
            message = "⭐ 북마크됨" if new_val else "북마크 해제됨"
            self._set_bookmark_state(target, new_val, success_message=message)

        elif action == "toggle_read":
            new_val = not bool(target.get("is_read", 0))
            if self._set_read_state(
                target,
                new_val,
                failure_message="읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
            ):
                parent = self._main_window()
                if parent is not None:
                    parent.show_toast("✓ 읽음으로 표시되었습니다." if new_val else "📖 안 읽음으로 표시되었습니다.")

        elif action == "note":
            self._edit_note_for_target(target)

        elif action == "delete":
            self._delete_target(target)

    def cleanup(self):
        """탭 종료 시 리소스 정리"""
        if getattr(self, "_cleanup_started", False):
            return
        self._cleanup_started = True
        self._is_closing = True

        # 필터 타이머 정리
        if hasattr(self, 'filter_timer') and self.filter_timer:
            self.filter_timer.stop()
        if hasattr(self, '_render_timer') and self._render_timer:
            self._render_timer.stop()
        self._request_scope_signatures.clear()
        self._pending_append_request_ids.clear()
        self._pending_scroll_restore = 0
        self._render_scheduled = False
        
        # DB 워커 정리
        if hasattr(self, 'worker') and self.worker:
            self._detach_worker_signals(self.worker, ("finished", "error"))
            try:
                if self.worker.isRunning():
                    self.worker.stop()
                    if not self.worker.wait(1000):
                        logger.warning("DBWorker cleanup wait timeout: %s", self.keyword)
            except Exception as e:
                logger.warning("DBWorker cleanup failed (%s): %s", self.keyword, e)
            finally:
                self.worker = None
        
        # Job 워커 정리
        if hasattr(self, 'job_worker') and self.job_worker:
            self._detach_worker_signals(self.job_worker, ("finished", "error"))
            try:
                if self.job_worker.isRunning():
                    try:
                        self.job_worker.stop()
                    except Exception:
                        self.job_worker.requestInterruption()
                        self.job_worker.quit()
                        self.job_worker.wait(100)
                    if not self.job_worker.wait(300):
                        try:
                            self.job_worker.setParent(None)
                        except Exception:
                            pass
                        try:
                            self.job_worker.finished.connect(self.job_worker.deleteLater)
                        except Exception:
                            pass
                        logger.warning("AsyncJobWorker cleanup wait timeout: %s", self.keyword)
                else:
                    try:
                        self.job_worker.deleteLater()
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("AsyncJobWorker cleanup failed (%s): %s", self.keyword, e)
            finally:
                self.job_worker = None
        
        logger.debug(f"NewsTab 정리 완료: {self.keyword}")
