# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, cast

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from core.database import DatabaseWriteError
from core.content_filters import normalize_tags, tags_to_csv
from core.workers import IterativeJobWorker, _normalized_http_url, delete_qthread_when_finished
from ui.dialogs import NoteDialog
from ui.protocols import MainWindowProtocol

logger = logging.getLogger(__name__)


class _NewsTabArticleActionsMixin:
    def _runtime_attr(self, name: str, default: Any) -> Any:
        try:
            import ui.news_tab as news_tab_module

            return getattr(news_tab_module, name, default)
        except Exception:
            return default

    def _should_block_local_db_action(self, action: str) -> bool:
        should_block_db_action = getattr(self, "_should_block_db_action", None)
        return bool(callable(should_block_db_action) and should_block_db_action(action))

    def _invalidate_local_render_cache(self, target: Dict[str, Any]) -> None:
        invalidate = getattr(self, "_invalidate_item_render_cache", None)
        if callable(invalidate):
            invalidate(target)

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
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "read-state update"):
            return False

        was_read = bool(target.get("is_read", 0))
        now_read = bool(new_read)
        if was_read == now_read:
            return True

        try:
            updated = self.db.update_status(link, "is_read", 1 if now_read else 0)
        except DatabaseWriteError as exc:
            logger.warning("Read-state update failed for %s: %s", link, exc)
            updated = False
        except Exception:
            logger.exception("Unexpected read-state update failure for %s", link)
            updated = False
        if not updated:
            self._emit_local_action_failure(failure_message)
            return False

        target["is_read"] = 1 if now_read else 0
        _NewsTabArticleActionsMixin._invalidate_local_render_cache(self, target)
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
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "bookmark update"):
            return False

        new_value = 1 if bool(new_bookmarked) else 0
        if int(target.get("is_bookmarked", 0) or 0) == new_value:
            return True

        try:
            updated = self.db.update_status(link, "is_bookmarked", new_value)
        except DatabaseWriteError as exc:
            logger.warning("Bookmark update failed for %s: %s", link, exc)
            updated = False
        except Exception:
            logger.exception("Unexpected bookmark update failure for %s", link)
            updated = False
        if not updated:
            self._emit_local_action_failure(failure_message)
            return False

        target["is_bookmarked"] = new_value
        _NewsTabArticleActionsMixin._invalidate_local_render_cache(self, target)

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
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "note save"):
            return False

        new_note = str(note or "")
        if str(target.get("notes", "") or "") == new_note:
            return True
        try:
            updated = self.db.save_note(link, new_note)
        except DatabaseWriteError as exc:
            logger.warning("Note save failed for %s: %s", link, exc)
            updated = False
        except Exception:
            logger.exception("Unexpected note save failure for %s", link)
            updated = False
        if not updated:
            self._emit_local_action_failure(failure_message)
            return False

        target["notes"] = new_note
        _NewsTabArticleActionsMixin._invalidate_local_render_cache(self, target)
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
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "note edit"):
            return False
        try:
            current_note = self.db.get_note(link)
        except Exception:
            self._emit_local_action_failure("메모를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
            return False
        dialog = NoteDialog(current_note, self)
        if not dialog.exec():
            return False
        return self._save_note_state(target, dialog.get_note())

    def _edit_tags_for_target(self, target: Dict[str, Any]) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "tag edit"):
            return False
        current_tags = target.get("tags", "")
        if not current_tags:
            try:
                current_tags = tags_to_csv(self.db.get_tags(link))
            except Exception:
                current_tags = ""
        text, ok = QInputDialog.getText(
            self,
            "태그 편집",
            "쉼표로 태그를 구분하세요.",
            text=str(current_tags or ""),
        )
        if not ok:
            return False
        tags = normalize_tags(text)
        try:
            if not self.db.set_tags(link, tags):
                self._emit_local_action_failure("태그를 저장하지 못했습니다. 기사가 이미 삭제되었을 수 있습니다.")
                return False
        except DatabaseWriteError as exc:
            logger.warning("Tag save failed for %s: %s", link, exc)
            self._emit_local_action_failure("태그를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.")
            return False
        except Exception:
            logger.exception("Unexpected tag save failure for %s", link)
            self._emit_local_action_failure("태그를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.")
            return False
        target["tags"] = ",".join(tags)
        _NewsTabArticleActionsMixin._invalidate_local_render_cache(self, target)
        current_tag_filter = getattr(self, "_current_tag_filter", lambda: "")()
        self._refresh_after_local_change(
            requires_refilter=bool(str(current_tag_filter or "").strip())
        )
        parent = self._main_window()
        if parent is not None:
            if hasattr(parent, "sync_link_state_across_tabs"):
                parent.sync_link_state_across_tabs(self, link, tags=",".join(tags))
            if hasattr(parent, "show_toast"):
                parent.show_toast("🏷 태그가 저장되었습니다.")
        refresh_known_tags = getattr(self, "_refresh_tag_filter_options", None)
        if callable(refresh_known_tags):
            refresh_known_tags()
        return True

    def _add_publisher_filter_for_target(self, target: Dict[str, Any], *, preferred: bool) -> bool:
        publisher = str(target.get("publisher", "") or "").strip()
        if not publisher:
            self._emit_local_action_failure("출처 정보가 없어 필터에 추가할 수 없습니다.")
            return False
        parent = self._main_window()
        if parent is None:
            return False
        method_name = "add_preferred_publisher" if preferred else "add_blocked_publisher"
        method = getattr(parent, method_name, None)
        if not callable(method):
            return False
        method(publisher)
        return True

    def _delete_target(self, target: Dict[str, Any]) -> bool:
        link = str(target.get("link", "") or "").strip()
        if not link:
            return False
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "delete article"):
            return False

        reply = QMessageBox.question(
            self,
            "삭제",
            "이 기사를 목록에서 삭제하시겠습니까?\n(클라우드 동기화용 삭제 기록을 남기며, 아카이브에서 복구할 수 있습니다)",
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
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"삭제 실패: {exc}")
            return False
