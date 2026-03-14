# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query
from core.validation import ValidationUtils
from ui.news_tab import NewsTab

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)


class _MainWindowTabsMixin:
    def close_current_tab(self: MainApp):
        """현재 탭 닫기"""
        idx = self.tabs.currentIndex()
        if idx > 0:
            self.close_tab(idx)

    def _normalize_tab_keyword(self: MainApp, raw_keyword: str) -> Optional[str]:
        if not isinstance(raw_keyword, str):
            return None
        keyword = ValidationUtils.sanitize_keyword(raw_keyword).strip()
        if not keyword:
            return None
        if not has_positive_keyword(keyword):
            return None
        return keyword

    def _is_fetch_key_referenced(
        self: MainApp,
        fetch_key: str,
        skip_keyword: Optional[str] = None,
    ) -> bool:
        if not fetch_key:
            return False
        for _index, widget in self._iter_news_tabs(start_index=1):
            tab_keyword = widget.keyword
            if skip_keyword is not None and tab_keyword == skip_keyword:
                continue
            search_query, exclude_words = parse_search_query(tab_keyword)
            if not search_query:
                continue
            if build_fetch_key(search_query, exclude_words) == fetch_key:
                return True
        return False

    def _prune_fetch_key_state(
        self: MainApp,
        fetch_key: str,
        skip_keyword: Optional[str] = None,
    ) -> None:
        if not fetch_key:
            return
        if self._is_fetch_key_referenced(fetch_key, skip_keyword=skip_keyword):
            return
        self._fetch_cursor_by_key.pop(fetch_key, None)
        self._fetch_total_by_key.pop(fetch_key, None)
        self._last_fetch_request_ts.pop(fetch_key, None)

    def add_news_tab(self: MainApp, keyword: str):
        """뉴스 탭 추가"""
        normalized_keyword = self._normalize_tab_keyword(keyword)
        if not normalized_keyword:
            logger.warning("유효하지 않은 탭 키워드로 add_news_tab 요청이 무시되었습니다.")
            return

        keyword = normalized_keyword

        for i, widget in self._iter_news_tabs():
            if widget.keyword == keyword:
                self.tabs.setCurrentIndex(i)
                return

        tab = NewsTab(keyword, self._require_db(), self.theme_idx, self)
        tab.btn_load.clicked.connect(lambda _checked=False, tab_ref=tab: self.fetch_news(tab_ref.keyword, is_more=True))
        search_query, exclude_words = parse_search_query(keyword)
        fetch_key = build_fetch_key(search_query, exclude_words)
        fetch_state = self._tab_fetch_state.setdefault(keyword, self._make_tab_fetch_state())
        persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
        if persisted_cursor > fetch_state.last_api_start_index:
            fetch_state.last_api_start_index = persisted_cursor
        tab.total_api_count = int(self._fetch_total_by_key.get(fetch_key, 0) or 0)
        self.tabs.addTab(tab, self._format_tab_title(keyword, unread_count=0))
        self.sync_tab_load_more_state(keyword)

    def add_tab_dialog(self: MainApp):
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

        if self.search_history:
            history_label = QLabel("📋 최근 검색:")
            history_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
            layout.addWidget(history_label)

            history_layout = QHBoxLayout()
            for kw in self.search_history[:5]:
                btn = QPushButton(kw)
                btn.setStyleSheet("padding: 4px 8px; font-size: 9pt;")
                btn.clicked.connect(lambda checked, text=kw: input_field.setText(text))
                history_layout.addWidget(btn)
            history_layout.addStretch()
            layout.addLayout(history_layout)

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

            for i, w in self._iter_news_tabs(start_index=1):
                if w.keyword == keyword:
                    QMessageBox.information(
                        self,
                        "중복 태브",
                        f"'{keyword}' 탭이 이미 존재합니다.\n해당 탭으로 이동합니다."
                    )
                    self.tabs.setCurrentIndex(i)
                    return

            self.add_news_tab(keyword)
            self.fetch_news(keyword)

            if keyword not in self.search_history:
                self.search_history.insert(0, keyword)
                self.search_history = self.search_history[:10]

            self.save_config()

    def close_tab(self: MainApp, idx: int):
        """탭 닫기"""
        if idx == 0:
            return

        widget = self._news_tab_at(idx)
        removed_keyword = None
        if widget is not None:
            removed_keyword = widget.keyword
            active_request_id = self._worker_registry.get_active_request_id(removed_keyword)
            if active_request_id is not None:
                self.cleanup_worker(
                    keyword=removed_keyword,
                    request_id=active_request_id,
                    only_if_active=False,
                )
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
            self._prune_fetch_key_state(removed_fetch_key)
        self.save_config()

    def rename_tab(self: MainApp, idx: int):
        """탭 이름 변경"""
        if idx == 0:
            return

        w = self._news_tab_at(idx)
        if w is None:
            return

        text, ok = QInputDialog.getText(
            self,
            "탭 이름 변경",
            "새 검색 키워드를 입력하세요:",
            QLineEdit.EchoMode.Normal,
            w.keyword,
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

            for i, target in self._iter_news_tabs(start_index=1):
                if i == idx:
                    continue
                if target.keyword == new_keyword:
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
                self._last_fetch_request_ts.pop(new_fetch_key, None)
                self._prune_fetch_key_state(old_fetch_key, skip_keyword=new_keyword)
                self._tab_fetch_state[new_keyword] = self._make_tab_fetch_state()
                persisted_cursor = int(self._fetch_cursor_by_key.get(new_fetch_key, 0) or 0)
                if persisted_cursor > 0:
                    self._tab_fetch_state[new_keyword].last_api_start_index = persisted_cursor
                w.total_api_count = int(self._fetch_total_by_key.get(new_fetch_key, 0) or 0)
                w.last_update = None
            elif fetch_state is not None:
                self._tab_fetch_state[new_keyword] = fetch_state
                w.total_api_count = int(self._fetch_total_by_key.get(new_fetch_key, w.total_api_count) or 0)
            else:
                self._tab_fetch_state.setdefault(new_keyword, self._make_tab_fetch_state())
                persisted_cursor = int(self._fetch_cursor_by_key.get(new_fetch_key, 0) or 0)
                if persisted_cursor > self._tab_fetch_state[new_keyword].last_api_start_index:
                    self._tab_fetch_state[new_keyword].last_api_start_index = persisted_cursor
                w.total_api_count = int(self._fetch_total_by_key.get(new_fetch_key, 0) or 0)

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

            try:
                w.load_data_from_db()
            except Exception as e:
                logger.warning(f"리네임 직후 탭 재조회 실패: {e}")

            self.fetch_news(new_keyword)
            self.save_config()

    def on_tab_context_menu(self: MainApp, pos):
        """탭 바 컨텍스트 메뉴"""
        tab_bar = self._tab_bar()
        idx = tab_bar.tabAt(pos)
        if idx <= 0:
            return

        widget = self._news_tab_at(idx)
        if widget is None:
            return

        keyword = widget.keyword

        menu = QMenu(self)

        act_refresh = self._add_menu_action(menu, "🔄 새로고침")
        act_rename = self._add_menu_action(menu, "✏️ 이름 변경")
        menu.addSeparator()

        group_menu = menu.addMenu("📁 그룹에 추가")
        if group_menu is None:
            raise RuntimeError("Failed to create group menu")
        groups = self.keyword_group_manager.get_all_groups()
        if groups:
            for group in groups:
                act = self._add_menu_action(group_menu, group)
                act.triggered.connect(lambda checked, g=group, k=keyword: self._add_to_group_callback(g, k))
        else:
            group_menu.setDisabled(True)

        menu.addSeparator()
        act_close = self._add_menu_action(menu, "❌ 탭 닫기")

        action = menu.exec(tab_bar.mapToGlobal(pos))

        if action == act_refresh:
            self.fetch_news(keyword)
        elif action == act_rename:
            self.rename_tab(idx)
        elif action == act_close:
            self.close_tab(idx)

    def _add_to_group_callback(self: MainApp, group: str, keyword: str):
        """컨텍스트 메뉴에서 그룹 추가 콜백"""
        if self.keyword_group_manager.add_keyword_to_group(group, keyword):
            self.show_success_toast(f"'{keyword}'을(를) '{group}' 그룹에 추가했습니다.")
        else:
            self.show_warning_toast(f"이미 '{group}' 그룹에 존재하는 키워드입니다.")
