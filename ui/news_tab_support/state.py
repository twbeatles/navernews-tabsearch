# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple, cast

from core.query_parser import build_fetch_key, parse_search_query, parse_tab_query
from core.text_utils import parse_date_string
from core.workers import DBQueryScope
from ui.protocols import MainWindowProtocol


class _NewsTabStateMixin:
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
            or self._current_tag_filter()
            or self._only_preferred_publishers_enabled()
            or self._date_filter_active
        )

    def _publisher_filter_settings(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        parent = self.window()
        blocked = getattr(parent, "blocked_publishers", []) if parent is not None else []
        preferred = getattr(parent, "preferred_publishers", []) if parent is not None else []
        return tuple(str(item) for item in blocked), tuple(str(item) for item in preferred)

    def _current_tag_filter(self) -> str:
        combo = getattr(self, "combo_tag_filter", None)
        if combo is None:
            return ""
        text = str(combo.currentText() or "").strip()
        if not text or text == "모든 태그":
            return ""
        return text.lstrip("#").strip()

    def _only_preferred_publishers_enabled(self) -> bool:
        checkbox = getattr(self, "chk_preferred_publishers", None)
        return bool(checkbox is not None and checkbox.isChecked())

    def _build_query_scope(self) -> DBQueryScope:
        start_date, end_date = self._current_date_range()
        blocked_publishers, preferred_publishers = self._publisher_filter_settings()
        return DBQueryScope(
            keyword=self.db_keyword,
            filter_txt=self._current_filter_text(),
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab,
            only_unread=self.chk_unread.isChecked(),
            hide_duplicates=self.chk_hide_dup.isChecked(),
            exclude_words=tuple(self.exclude_words),
            blocked_publishers=blocked_publishers,
            preferred_publishers=preferred_publishers,
            only_preferred_publishers=self._only_preferred_publishers_enabled(),
            tag_filter=self._current_tag_filter(),
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
            scope.blocked_publishers,
            scope.preferred_publishers,
            scope.only_preferred_publishers,
            scope.tag_filter,
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
        tags: Optional[str] = None,
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

        if tags is not None:
            new_tags = str(tags)
            if str(target.get("tags", "") or "") != new_tags:
                target["tags"] = new_tags
                changed = True

        if changed:
            self._invalidate_item_render_cache(target)
            self._refresh_after_local_change()
        return changed

    def _main_window(self) -> Optional[MainWindowProtocol]:
        candidate = self.window()
        if candidate is None:
            return None
        required_attrs = (
            "update_tab_badge",
            "refresh_bookmark_tab",
            "should_block_db_action",
            "show_toast",
            "show_warning_toast",
            "sync_tab_load_more_state",
            "maybe_show_query_refresh_hint",
        )
        if not all(hasattr(candidate, attr) for attr in required_attrs):
            return None
        return cast(MainWindowProtocol, candidate)

    def _should_block_db_action(self, action: str, *, notify: bool = True) -> bool:
        parent = self._main_window()
        if parent is None:
            return False
        should_block_db_action = getattr(parent, "should_block_db_action", None)
        if not callable(should_block_db_action):
            return False
        return bool(should_block_db_action(action, notify=notify))

    def _request_db_reload(self, action: str, *, append: bool = False) -> None:
        if self._should_block_db_action(action):
            return
        self.load_data_from_db(append=append)
