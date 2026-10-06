# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import hashlib
import html
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QTimer

from core.publisher_aliases import canonical_publisher
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
        # 걸린 필터가 원인인 경우를 먼저 안내한다. 북마크 탭에서도 필터 때문에
        # 비어 보이는 것과 실제로 북마크가 없는 것을 구분해야 한다.
        if self._current_filter_text() or self._has_advanced_filters():
            title = "조건에 맞는 기사가 없습니다"
            body = "필터를 바꾸거나 <b>초기화</b>해 보세요."
        elif self.chk_unread.isChecked():
            title = "모두 읽었습니다"
            body = "새 기사가 도착하면 여기에 표시됩니다."
        elif self.is_bookmark_tab:
            title = "북마크한 기사가 없습니다"
            body = "기사 아래의 <b>북마크</b>를 누르면 여기에 모입니다."
        else:
            title = "아직 기사가 없습니다"
            body = "위의 <b>새로고침</b>을 눌러 최신 뉴스를 가져오세요."
        return (
            f"<p class='empty-state-title' align='center'>{title}</p>"
            f"<p class='empty-state' align='center'>{body}</p>"
        )

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
            str(getattr(self._main_window(), "publisher_aliases", {}) or {}),
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
                render_context = self._render_context_key(filter_word)
                can_append = (
                    append_from_index is not None
                    and append_from_index == self._rendered_item_count
                    and self._render_context_signature == render_context
                    and 0 <= append_from_index <= len(self.filtered_data_cache)
                )
                if can_append:
                    new_fragments = [
                        self._render_single_item(item, filter_word)
                        for item in self.filtered_data_cache[append_from_index:]
                    ]
                    self._rendered_body_html += "".join(new_fragments)
                else:
                    self._rendered_body_html = "".join(
                        self._render_single_item(item, filter_word)
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
                update_badge_cache = getattr(parent, "update_badge_cache_from_tab_load", None)
                if callable(update_badge_cache) and not self.is_bookmark_tab:
                    update_badge_cache(self.keyword, self._unread_count_cache)
                    return
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

    def _render_single_item(self, item: Dict[str, Any], filter_word: str, extra_badges_html: str = "") -> str:
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

        is_read = bool(item.get("is_read", 0))
        is_bookmarked = bool(item.get("is_bookmarked", 0))
        read_sfx = "-read" if is_read else ""
        title_pfx = "<span class='star'>★</span> " if is_bookmarked else ""

        item_title = item.get("title", "(제목 없음)")
        item_desc = item.get("description", "")

        if filter_word:
            title = TextUtils.highlight_text(item_title, filter_word)
            desc = TextUtils.highlight_text(item_desc, filter_word)
        else:
            title = html.escape(item_title)
            desc = html.escape(item_desc)

        date_str = item.get("_date_fmt") or parse_date_string(item.get("pubDate", ""))
        item["_date_fmt"] = date_str
        raw_publisher = str(item.get("publisher", "출처없음") or "출처없음")
        aliases = getattr(self._main_window(), "publisher_aliases", {}) or {}
        display_publisher = canonical_publisher(raw_publisher, aliases) or raw_publisher
        if display_publisher != raw_publisher:
            publisher_html = (
                f"<span title='{html.escape(raw_publisher)}'>{html.escape(display_publisher)}</span>"
            )
        else:
            publisher_html = html.escape(raw_publisher)

        # 메타 줄: 출처 · 시간 뒤에 부가 표시(유사/태그/메모)를 같은 줄로 잇는다.
        meta_parts = [publisher_html, html.escape(str(date_str or ""))]
        if extra_badges_html:
            meta_parts.append(extra_badges_html)
        if item.get("is_duplicate", 0):
            meta_parts.append("<span class='dup'>유사</span>")
        tags = [
            tag.strip()
            for tag in str(item.get("tags", "") or "").split(",")
            if tag.strip()
        ]
        if tags:
            meta_parts.append(" ".join(f"<span class='tag'>#{html.escape(tag)}</span>" for tag in tags))
        if item.get("notes") and str(item.get("notes", "")).strip():
            meta_parts.append(f"<a href='app://note/{link_hash}'>메모</a>")
        meta_html = " · ".join(part for part in meta_parts if part)

        bk_txt = "북마크 해제" if is_bookmarked else "북마크"
        actions = (
            f"<a href='app://bm/{link_hash}'>{bk_txt}</a>"
            f"&nbsp;&nbsp;&nbsp;<a href='app://share/{link_hash}'>공유</a>"
        )

        rendered = f"""
        <div class="news-item">
            <div><a href="app://open/{link_hash}" class="title-link{read_sfx}">{title_pfx}{title}</a></div>
            <div class="description{read_sfx}">{desc}</div>
            <table width="100%" cellspacing="0" cellpadding="0" style="margin-top:6px;"><tr>
                <td class="meta">{meta_html}</td>
                <td class="actions" align="right">{actions}</td>
            </tr></table>
        </div>
        <table width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0;"><tr>
            <td class="rule" height="1"></td>
        </tr></table>
        """
        self._item_html_cache[cache_key] = rendered
        return rendered

    def _get_load_more_html(self, remaining: int) -> str:
        """저장된 기사 중 아직 표시하지 않은 항목을 더 보여주는 링크"""
        return (
            "<div class='load-more' align='center'>"
            f"<a href='app://load_more'>더 보기 ({remaining}개 남음)</a></div>"
        )

    def render_html(self):
        """Schedule an HTML render on the next event-loop tick."""
        self._schedule_render()

    def update_status_label(self):
        """상태 레이블 업데이트 - 캐시 기반 최적화"""
        loaded_count = len(self.filtered_data_cache)
        total_filtered = max(self._total_filtered_count, loaded_count)
        active_start_date, active_end_date = self._current_date_range()
        has_filters = self._has_active_filters()
        parts = []

        if not self.is_bookmark_tab:
            overall_total = max(int(self.total_api_count or 0), total_filtered)
            if has_filters:
                parts.append(f"{total_filtered:,}개 일치 (전체 {overall_total:,}개)")
            else:
                parts.append(f"기사 {total_filtered:,}개")
        else:
            parts.append(f"북마크 {total_filtered:,}개")

        if loaded_count < total_filtered:
            parts.append(f"{loaded_count:,}개 표시 중")
        if active_start_date and active_end_date:
            parts.append(f"{active_start_date} ~ {active_end_date}")
        if not self.is_bookmark_tab:
            if self._unread_count_cache > 0:
                parts.append(f"안 읽음 {self._unread_count_cache:,}")
            if self.last_update:
                parts.append(f"{self.last_update} 업데이트")

        self.lbl_status.setText(" · ".join(parts))
        update_filter_indicator = getattr(self, "_update_filter_indicator", None)
        if callable(update_filter_indicator):
            update_filter_indicator()
