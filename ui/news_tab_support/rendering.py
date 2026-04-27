# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import hashlib
import html
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QTimer

from core.text_utils import TextUtils, parse_date_string, perf_timer
from ui.styles import AppStyle, Colors


class _NewsTabRenderingMixin:
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
            str(item.get("tags", "") or ""),
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
        publisher_html = html.escape(str(item.get("publisher", "출처없음") or "출처없음"))
        date_html = html.escape(str(date_str or ""))
        tags = [
            tag.strip()
            for tag in str(item.get("tags", "") or "").split(",")
            if tag.strip()
        ]
        tags_html = "".join(
            f"<span class='keyword-tag'>#{html.escape(tag)}</span>"
            for tag in tags
        )

        has_note = bool(item.get("notes") and str(item.get("notes", "")).strip())
        note_indicator = " 📝" if has_note else ""

        actions = f"""
            <a href='app://share/{link_hash}'>공유</a>
            <a href='app://ext/{link_hash}'>외부</a>
            <a href='app://note/{link_hash}'>메모{note_indicator}</a>
            <a href='app://tag/{link_hash}'>태그</a>
        """
        if item.get("is_read", 0):
            actions += f"<a href='app://unread/{link_hash}'>안읽음</a>"
        actions += f"<a href='app://bm/{link_hash}' style='color:{bk_col}'>{bk_txt}</a>"

        badges = base_badges_html

        if item.get("is_duplicate", 0):
            badges += "<span class='duplicate-badge'>유사</span>"
        badges += tags_html

        rendered = f"""
        <div class="news-item{is_read_cls}{is_dup_cls}">
            <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
            <div class="meta-info">
                <span class="meta-left">📰 {publisher_html} · {date_html} {badges}</span>
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
