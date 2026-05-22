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
from ui.news_tab_support.actions_support.article_state import _NewsTabArticleActionsMixin

logger = logging.getLogger(__name__)


class _NewsTabLinkOpeningMixin:
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
        if not url.isValid() or url.scheme().lower() not in {"http", "https"}:
            self._emit_local_action_failure(failure_message)
            return False
        safe_url = _normalized_http_url(url.toString())
        if not safe_url:
            self._emit_local_action_failure(failure_message)
            return False
        url = QUrl(safe_url)

        desktop_services = _NewsTabArticleActionsMixin._runtime_attr(self, "QDesktopServices", QDesktopServices)
        if not desktop_services.openUrl(url):
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

    def on_link_clicked(self, url: QUrl):
        """링크 클릭 처리"""
        scheme = url.scheme()
        if scheme != "app":
            return

        action = url.host()
        link_hash = url.path().lstrip("/")

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

        elif action == "tag":
            self._edit_tags_for_target(target)
            return

        elif action == "ext":
            self._open_external_link_and_mark_read(target)
            return

    def on_browser_action(self, action, link_hash):
        """브라우저 컨텍스트 메뉴 액션 처리"""
        target = self._target_by_hash(link_hash)
        if not target:
            return

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

        elif action == "tag":
            self._edit_tags_for_target(target)

        elif action == "block_publisher":
            self._add_publisher_filter_for_target(target, preferred=False)

        elif action == "prefer_publisher":
            self._add_publisher_filter_for_target(target, preferred=True)

        elif action == "delete":
            self._delete_target(target)
