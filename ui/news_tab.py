import html
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, cast

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
from core.workers import AsyncJobWorker, DBWorker
from ui.dialogs import NoteDialog
from ui.protocols import MainWindowProtocol
from ui.styles import AppStyle, Colors
from ui.widgets import NewsBrowser, NoScrollComboBox

configure_logging()
logger = logging.getLogger(__name__)

class NewsTab(QWidget):
    """개별 뉴스 탭 (메모리 캐싱 및 필터링 최적화) - Phase 3 성능 최적화"""
    
    # 렌더링 최적화 상수
    INITIAL_RENDER_COUNT = 50   # 초기 렌더링 개수
    LOAD_MORE_COUNT = 30        # 추가 로딩 개수
    MAX_RENDER_COUNT = 500      # 최대 렌더링 개수
    FILTER_DEBOUNCE_MS = 250    # 필터 디바운싱 시간 (ms) - 성능 최적화
    
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
        self._css_cache_by_theme: Dict[int, str] = {}
        self._unread_count_cache = 0
        self._load_request_id = 0
        self._data_version = 0
        self._last_render_signature: Optional[Tuple[Any, ...]] = None
        self._last_filter_text = ""
        self._cached_badge_keyword = ""
        self._cached_badges_html = ""
        
        # 렌더링 최적화 변수 (Phase 3)
        self._rendered_count = 0           # 현재 렌더링된 항목 수
        self._is_loading_more = False      # 추가 로딩 중 여부
        
        # Async DB Worker
        self.worker: Optional[DBWorker] = None
        self.job_worker: Optional[AsyncJobWorker] = None
        self._mark_all_mode_label = "탭 전체"
        
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

    def _prepare_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        link = item.get("link", "")
        title = item.get("title", "")
        desc = item.get("description", "")
        if not item.get("_link_hash"):
            item["_link_hash"] = hashlib.md5(link.encode()).hexdigest() if link else ""
        item["_title_lc"] = title.lower()
        item["_desc_lc"] = desc.lower()
        if not item.get("_date_fmt"):
            item["_date_fmt"] = parse_date_string(item.get("pubDate", ""))
        return item

    def _rebuild_item_indexes(self):
        self._item_by_hash = {}
        for item in self.news_data_cache:
            prepared = self._prepare_item(item)
            link_hash = prepared.get("_link_hash")
            if link_hash:
                self._item_by_hash[link_hash] = prepared

    def _target_by_hash(self, link_hash: str) -> Optional[Dict[str, Any]]:
        return self._item_by_hash.get(link_hash)

    def _target_by_link(self, link: str) -> Optional[Dict[str, Any]]:
        normalized_link = str(link or "").strip()
        if not normalized_link:
            return None
        for item in self.news_data_cache:
            if str(item.get("link", "") or "").strip() == normalized_link:
                return item
        return None

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

    def _clipboard(self) -> QClipboard:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            raise RuntimeError("Clipboard is unavailable")
        return clipboard

    def _refresh_after_local_change(self, requires_refilter: bool = False):
        self._data_version += 1
        self._last_render_signature = None
        if requires_refilter:
            self.apply_filter()
        else:
            self.render_html()
            self.update_status_label()

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
        self.date_start.dateChanged.connect(self.load_data_from_db)
        
        self.lbl_tilde = QLabel("~")
        
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setMinimumWidth(120)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.dateChanged.connect(self.load_data_from_db)
        
        date_inner_layout.addWidget(self.date_start)
        date_inner_layout.addWidget(self.lbl_tilde)
        date_inner_layout.addWidget(self.date_end)
        
        row2_layout.addWidget(self.btn_date_toggle)
        row2_layout.addWidget(self.date_container)
        row2_layout.addStretch()
        
        filter_layout.addLayout(row2_layout)

        # 초기에는 날짜 필터 숨김
        self.date_container.setVisible(False)
        self._update_date_toggle_style(False)
        
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
        self._update_date_toggle_style(checked)
        if checked:
            self.date_container.adjustSize()
            self.date_container.updateGeometry()
            self.date_container.repaint()

        # 즉시 조회 실행
        self.load_data_from_db()

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

    def _on_filter_changed(self):
        """필터 입력 변경 시 디바운싱 타이머 시작"""
        self.filter_timer.stop()
        self.filter_timer.start(self.FILTER_DEBOUNCE_MS)
    
    def _apply_filter_debounced(self):
        """디바운싱된 필터 적용"""
        self.apply_filter()

    def load_data_from_db(self):
        """DB에서 데이터 로드 (비동기 처리)"""
        with perf_timer("ui.load_data_from_db", f"kw={self.keyword}"):
            if self.worker and self.worker.isRunning():
                self.worker.stop()
                if not self.worker.wait(150):
                    logger.warning(f"DBWorker wait timeout: {self.keyword}")

            self._load_request_id += 1
            current_request_id = self._load_request_id
            self.lbl_status.setText("⏳ 데이터 로딩 중...")
            self.btn_load.setEnabled(False)

            s_date = None
            e_date = None
            if self.btn_date_toggle.isChecked():
                s_date = self.date_start.date().toString("yyyy-MM-dd")
                e_date = self.date_end.date().toString("yyyy-MM-dd")

            self.worker = DBWorker(
                self.db,
                keyword=self.keyword,
                filter_txt="",
                sort_mode=self.combo_sort.currentText(),
                only_bookmark=self.is_bookmark_tab,
                only_unread=self.chk_unread.isChecked(),
                hide_duplicates=self.chk_hide_dup.isChecked(),
                start_date=s_date,
                end_date=e_date,
            )
            self.worker.finished.connect(
                lambda data, total_count, rid=current_request_id: self.on_data_loaded(data, total_count, rid)
            )
            self.worker.error.connect(lambda err_msg, rid=current_request_id: self.on_data_error(err_msg, rid))
            self.worker.start()

    def on_data_loaded(self, data, total_count, request_id: Optional[int] = None):
        """데이터 로드 완료 시 호출"""
        if request_id is not None and request_id != self._load_request_id:
            logger.info(f"PERF|ui.on_data_loaded.stale|0.00ms|kw={self.keyword}|rid={request_id}")
            return

        with perf_timer("ui.on_data_loaded", f"kw={self.keyword}|rows={len(data)}"):
            self.news_data_cache = [self._prepare_item(dict(item)) for item in data]
            self._rebuild_item_indexes()
            if self.total_api_count <= 0 or total_count > self.total_api_count:
                self.total_api_count = total_count
            self._recount_unread_cache()
            self._data_version += 1
            self._last_render_signature = None
            self.btn_load.setEnabled(True)
            self.apply_filter()
            parent = self._main_window()
            if parent is not None:
                parent.sync_tab_load_more_state(self.keyword)
                if not self.news_data_cache and not self.is_bookmark_tab:
                    parent.maybe_show_query_refresh_hint(self.keyword)

    def on_data_error(self, err_msg, request_id: Optional[int] = None):
        """데이터 로드 오류 시 호출"""
        if request_id is not None and request_id != self._load_request_id:
            return
        self.lbl_status.setText(f"⚠️ 오류: {err_msg}")
        self.btn_load.setEnabled(True)
    
    def apply_filter(self):
        """메모리 내 필터링 (DB 쿼리 없이)"""
        with perf_timer("ui.apply_filter", f"kw={self.keyword}|rows={len(self.news_data_cache)}"):
            filter_txt = self.inp_filter.text().strip()
            filter_txt_lc = filter_txt.lower()

            if filter_txt:
                self.inp_filter.setObjectName("FilterActive")
            else:
                self.inp_filter.setObjectName("")
            self.inp_filter.setStyle(self.inp_filter.style())

            prev_filtered = self.filtered_data_cache
            if filter_txt_lc:
                new_filtered = [
                    item
                    for item in self.news_data_cache
                    if filter_txt_lc in item.get("_title_lc", "") or filter_txt_lc in item.get("_desc_lc", "")
                ]
            else:
                new_filtered = self.news_data_cache

            same_filter = filter_txt_lc == self._last_filter_text
            same_items = (
                len(prev_filtered) == len(new_filtered)
                and all(a is b for a, b in zip(prev_filtered, new_filtered))
            )
            self.filtered_data_cache = new_filtered
            self._last_filter_text = filter_txt_lc

            if same_filter and same_items and self._rendered_count > 0:
                self.update_status_label()
                return

            self._rendered_count = 0
            self.render_html()

    def _render_single_item(self, item: Dict[str, Any], filter_word: str, base_badges_html: str) -> str:
        """단일 뉴스 아이템 HTML 렌더링"""
        is_read_cls = " read" if item.get("is_read", 0) else ""
        is_dup_cls = " duplicate" if item.get("is_duplicate", 0) else ""
        title_pfx = "⭐ " if item.get("is_bookmarked", 0) else ""

        item_link = item.get("link", "")
        item_title = item.get("title", "(제목 없음)")
        item_desc = item.get("description", "")
        link_hash = item.get("_link_hash") or (hashlib.md5(item_link.encode()).hexdigest() if item_link else "")
        item["_link_hash"] = link_hash

        if hasattr(self.browser, "preview_data") and link_hash:
            self.browser.preview_data[link_hash] = item_desc

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

        return f"""
        <div class="news-item{is_read_cls}{is_dup_cls}">
            <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
            <div class="meta-info">
                <span class="meta-left">📰 {item.get('publisher', '출처없음')} · {date_str} {badges}</span>
                <span class="actions">{actions}</span>
            </div>
            <div class="description">{desc}</div>
        </div>
        """

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
        """HTML 렌더링 - Colors 헬퍼 사용 버전"""
        with perf_timer("ui.render_html", f"kw={self.keyword}|rows={len(self.filtered_data_cache)}"):
            scroll_pos = self._browser_scroll_bar().value()
            is_dark = self.theme == 1
            filter_word = self.inp_filter.text().strip()

            render_signature = (
                self.theme,
                filter_word,
                self._rendered_count,
                len(self.filtered_data_cache),
                self._data_version,
            )
            if render_signature == self._last_render_signature:
                self.update_status_label()
                return

            if self.theme not in self._css_cache_by_theme:
                colors = Colors.get_html_colors(is_dark)
                self._css_cache_by_theme[self.theme] = AppStyle.HTML_TEMPLATE.format(**colors)
            css = self._css_cache_by_theme[self.theme]

            html_parts = [f"<html><head><meta charset='utf-8'>{css}</head><body>"]

            if hasattr(self.browser, "set_preview_data"):
                self.browser.set_preview_data({})

            if not self.filtered_data_cache:
                if self.is_bookmark_tab:
                    msg = "<div class='empty-state-title'>⭐ 북마크</div>북마크된 기사가 없습니다.<br><br>기사 카드의 [북마크] 버튼을 눌러<br>중요한 기사를 저장하세요."
                elif self.chk_unread.isChecked():
                    msg = "<div class='empty-state-title'>✓ 완료!</div>모든 기사를 읽었습니다."
                else:
                    msg = "<div class='empty-state-title'>📰 뉴스</div>표시할 기사가 없습니다.<br><br>새로고침 버튼을 눌러 최신 뉴스를 가져오세요."
                html_parts.append(f"<div class='empty-state'>{msg}</div>")
            else:
                total_items = len(self.filtered_data_cache)
                if self._rendered_count < self.INITIAL_RENDER_COUNT:
                    self._rendered_count = self.INITIAL_RENDER_COUNT

                render_limit = min(self._rendered_count, total_items)
                items_to_render = self.filtered_data_cache[:render_limit]
                self._rendered_count = len(items_to_render)
                base_badges_html = self._get_keyword_badges_html()

                for item in items_to_render:
                    html_parts.append(self._render_single_item(item, filter_word, base_badges_html))

                remaining = total_items - self._rendered_count
                if remaining > 0:
                    html_parts.append(self._get_load_more_html(remaining))

            html_parts.append("</body></html>")
            self.browser.setHtml("".join(html_parts))
            self._last_render_signature = (
                self.theme,
                filter_word,
                self._rendered_count,
                len(self.filtered_data_cache),
                self._data_version,
            )

            if scroll_pos > 0:
                QTimer.singleShot(0, lambda: self._browser_scroll_bar().setValue(scroll_pos))
            self.update_status_label()

    def append_items(self):
        """추가 아이템 로딩 (최적화: 전체 재렌더링 대신 _rendered_count 증가 후 렌더링)"""
        total_items = len(self.filtered_data_cache)
        start_idx = self._rendered_count
        end_idx = min(start_idx + self.LOAD_MORE_COUNT, total_items)
        
        if start_idx >= end_idx:
            return
        
        # _rendered_count 증가 (render_html에서 이 값까지 렌더링)
        self._rendered_count = end_idx
        
        # 스크롤 위치 저장 후 렌더링
        scroll_pos = self._browser_scroll_bar().value()
        self.render_html()
        
        # 스크롤 위치 복원 (약간의 지연 필요)
        if scroll_pos > 0:
            QTimer.singleShot(10, lambda: self._browser_scroll_bar().setValue(scroll_pos))


    def update_status_label(self):
        """상태 레이블 업데이트 - 캐시 기반 최적화"""
        total_filtered = len(self.filtered_data_cache)
        rendered = self._rendered_count
        
        if not self.is_bookmark_tab:
            unread = self._unread_count_cache
            msg = f"'{self.keyword}': 총 {self.total_api_count}개"
            
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                msg += f" | 필터링: {total_filtered}개"
            else:
                msg += f" | {len(self.news_data_cache)}개"
            
            # Phase 3: 렌더링된 항목 수 표시
            if rendered < total_filtered:
                msg += f" (표시: {rendered}개)"
            
            if unread > 0:
                msg += f" | 안 읽음: {unread}개"
            if self.last_update:
                msg += f" | 업데이트: {self.last_update}"
            self.lbl_status.setText(msg)
        else:
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                status_text = f"⭐ 북마크 {len(self.news_data_cache)}개 중 {total_filtered}개"
            else:
                status_text = f"⭐ 북마크 {len(self.news_data_cache)}개"
            
            # Phase 3: 렌더링된 항목 수 표시
            if rendered < total_filtered:
                status_text += f" (표시: {rendered}개)"
            
            self.lbl_status.setText(status_text)


    def _open_external_link_and_mark_read(self, target: Dict[str, Any]):
        link = target.get("link", "")
        if not link:
            return

        QDesktopServices.openUrl(QUrl(link))
        self._set_read_state(
            target,
            True,
            failure_message="읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
        )

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
            if failure_message:
                self.lbl_status.setText(f"⚠️ {failure_message}")
                parent = self._main_window()
                if parent is not None:
                    parent.show_warning_toast(failure_message)
            return False

        target["is_read"] = 1 if now_read else 0
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
            QDesktopServices.openUrl(QUrl(link))
            self._set_read_state(
                target,
                True,
                failure_message="읽음 상태를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
            )

        elif action == "bm":
            new_val = 0 if target.get("is_bookmarked") else 1
            if self.db.update_status(link, "is_bookmarked", new_val):
                target["is_bookmarked"] = new_val
                requires_refilter = False
                if self.is_bookmark_tab and new_val == 0:
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
                            is_bookmarked=bool(new_val),
                        )
                    msg = "⭐ 북마크에 추가되었습니다." if new_val else "북마크가 해제되었습니다."
                    parent.show_toast(msg)

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
            current_note = self.db.get_note(link)
            dialog = NoteDialog(current_note, self)
            if dialog.exec():
                new_note = dialog.get_note()
                if self.db.save_note(link, new_note):
                    target["notes"] = new_note
                    self._refresh_after_local_change()
                    parent = self._main_window()
                    if parent is not None:
                        if hasattr(parent, "sync_link_state_across_tabs"):
                            parent.sync_link_state_across_tabs(self, link, notes=new_note)
                        parent.show_toast("📝 메모가 저장되었습니다.")
            return

        elif action == "ext":
            self._open_external_link_and_mark_read(target)
            return

    def mark_all_read(self):
        """모두 읽음으로 표시 (비동기)"""
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

        if clicked == btn_visible_only:
            target_links = []
            for item in self.filtered_data_cache:
                link = item.get("link", "")
                if link and link not in target_links:
                    target_links.append(link)

            if not target_links:
                self.btn_read_all.setEnabled(True)
                self.lbl_status.setText("읽음 처리할 기사가 없습니다.")
                parent = self._main_window()
                if parent is not None:
                    parent.show_toast("읽음 처리할 기사가 없습니다.")
                return

            self._mark_all_mode_label = "현재 표시 결과"
            self.job_worker = AsyncJobWorker(self.db.mark_links_as_read, target_links)
        else:
            self._mark_all_mode_label = "탭 전체"
            self.job_worker = AsyncJobWorker(
                self.db.mark_query_as_read,
                self.db_keyword,
                self.exclude_words,
                self.is_bookmark_tab,
                query_key=self.query_key,
            )

        self.job_worker.finished.connect(self._on_mark_all_read_done)
        self.job_worker.error.connect(self._on_mark_all_read_error)
        self.job_worker.start()
             
    def _on_mark_all_read_done(self, count):
        """모두 읽음 처리 완료"""
        self.btn_read_all.setEnabled(True)
        parent = self._main_window()
        if parent is not None:
            if hasattr(parent, "on_database_maintenance_completed"):
                parent.on_database_maintenance_completed("mark_all_read", int(count or 0))
            else:
                self.load_data_from_db()  # UI 갱신 fallback
            mode_label = getattr(self, "_mark_all_mode_label", "선택 범위")
            parent.show_toast(f"✓ {mode_label} {count}개의 기사를 읽음으로 표시했습니다.")
        else:
            self.load_data_from_db()
            
    def _on_mark_all_read_error(self, err_msg):
        """모두 읽음 처리 오류"""
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
            new_val = 0 if target.get("is_bookmarked") else 1
            if self.db.update_status(link, "is_bookmarked", new_val):
                target["is_bookmarked"] = new_val
                requires_refilter = False
                if self.is_bookmark_tab and new_val == 0:
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
                            is_bookmarked=bool(new_val),
                        )
                    msg = "⭐ 북마크됨" if new_val else "북마크 해제됨"
                    parent.show_toast(msg)

        elif action == "toggle_read":
            was_read = bool(target.get("is_read", 0))
            new_val = 0 if was_read else 1
            if self.db.update_status(link, "is_read", new_val):
                target["is_read"] = new_val
                self._adjust_unread_cache(was_read, bool(new_val))
                if self.chk_unread.isChecked() and bool(new_val):
                    self._remove_cached_target(target)
                    self._refresh_after_local_change(requires_refilter=True)
                else:
                    self._refresh_after_local_change()
                self._notify_badge_change()
                parent = self._main_window()
                if parent is not None and hasattr(parent, "sync_link_state_across_tabs"):
                    parent.sync_link_state_across_tabs(self, link, is_read=bool(new_val))

        elif action == "note":
            current_note = self.db.get_note(link)
            dialog = NoteDialog(current_note, self)
            if dialog.exec():
                new_note = dialog.get_note()
                if self.db.save_note(link, new_note):
                    target["notes"] = new_note
                    self._refresh_after_local_change()
                    parent = self._main_window()
                    if parent is not None:
                        if hasattr(parent, "sync_link_state_across_tabs"):
                            parent.sync_link_state_across_tabs(self, link, notes=new_note)
                        parent.show_toast("📝 메모가 저장되었습니다.")

        elif action == "delete":
            reply = QMessageBox.question(
                self,
                "삭제",
                "이 기사를 목록에서 삭제하시겠습니까?\n(DB에서 완전히 삭제됩니다)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if not self.db.delete_link(link):
                        QMessageBox.warning(self, "오류", "삭제 대상 기사를 찾을 수 없습니다.")
                        return
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
                except Exception as e:
                    QMessageBox.warning(self, "오류", f"삭제 실패: {e}")

    def cleanup(self):
        """탭 종료 시 리소스 정리"""
        # 필터 타이머 정리
        if hasattr(self, 'filter_timer') and self.filter_timer:
            self.filter_timer.stop()
        
        # DB 워커 정리
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)
        
        # Job 워커 정리
        if hasattr(self, 'job_worker') and self.job_worker and self.job_worker.isRunning():
            self.job_worker.wait(1000)
        
        logger.debug(f"NewsTab 정리 완료: {self.keyword}")
