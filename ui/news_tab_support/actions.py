# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import Any, Dict, Optional, cast

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

from core.workers import IterativeJobWorker
from ui.dialogs import NoteDialog
from ui.protocols import MainWindowProtocol


class _NewsTabActionsMixin:
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

        desktop_services = _NewsTabActionsMixin._runtime_attr(self, "QDesktopServices", QDesktopServices)
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
        if _NewsTabActionsMixin._should_block_local_db_action(self, "read-state update"):
            return False

        was_read = bool(target.get("is_read", 0))
        now_read = bool(new_read)
        if was_read == now_read:
            return True

        if not self.db.update_status(link, "is_read", 1 if now_read else 0):
            self._emit_local_action_failure(failure_message)
            return False

        target["is_read"] = 1 if now_read else 0
        _NewsTabActionsMixin._invalidate_local_render_cache(self, target)
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
        if _NewsTabActionsMixin._should_block_local_db_action(self, "bookmark update"):
            return False

        new_value = 1 if bool(new_bookmarked) else 0
        if int(target.get("is_bookmarked", 0) or 0) == new_value:
            return True

        if not self.db.update_status(link, "is_bookmarked", new_value):
            self._emit_local_action_failure(failure_message)
            return False

        target["is_bookmarked"] = new_value
        _NewsTabActionsMixin._invalidate_local_render_cache(self, target)

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
        if _NewsTabActionsMixin._should_block_local_db_action(self, "note save"):
            return False

        new_note = str(note or "")
        if not self.db.save_note(link, new_note):
            self._emit_local_action_failure(failure_message)
            return False

        target["notes"] = new_note
        _NewsTabActionsMixin._invalidate_local_render_cache(self, target)
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
        if _NewsTabActionsMixin._should_block_local_db_action(self, "note edit"):
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
        if _NewsTabActionsMixin._should_block_local_db_action(self, "delete article"):
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
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"삭제 실패: {exc}")
            return False

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

        elif action == "ext":
            self._open_external_link_and_mark_read(target)
            return

    def mark_all_read(self):
        """모두 읽음으로 표시 (비동기)"""
        if getattr(self, "_is_closing", False):
            return
        if _NewsTabActionsMixin._should_block_local_db_action(self, "mark all read"):
            return
        message_box_cls = _NewsTabActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
        mode_dialog = message_box_cls(self)
        mode_dialog.setIcon(message_box_cls.Icon.Question)
        mode_dialog.setWindowTitle("모두 읽음으로 표시")
        mode_dialog.setText("읽음 처리 범위를 선택하세요.")
        mode_dialog.setInformativeText(
            "현재 표시 결과는 필터/기간/제외어 조건으로 계산된 전체 결과입니다."
        )

        btn_visible_only = mode_dialog.addButton("현재 표시 결과만", message_box_cls.ButtonRole.AcceptRole)
        btn_tab_all = mode_dialog.addButton("탭 전체", message_box_cls.ButtonRole.ActionRole)
        mode_dialog.addButton(message_box_cls.StandardButton.Cancel)
        mode_dialog.setDefaultButton(btn_visible_only)
        mode_dialog.exec()

        clicked = mode_dialog.clickedButton()
        if clicked not in (btn_visible_only, btn_tab_all):
            return

        self.lbl_status.setText("⏳ 처리 중...")
        self.btn_read_all.setEnabled(False)
        start_date, end_date = self._current_date_range()
        job_kwargs: Dict[str, Any]

        if clicked == btn_visible_only:
            if self._total_filtered_count <= 0:
                self.btn_read_all.setEnabled(True)
                self.lbl_status.setText("읽음 처리할 기사가 없습니다.")
                parent = self._main_window()
                if parent is not None:
                    parent.show_toast("읽음 처리할 기사가 없습니다.")
                return

            self._mark_all_mode_label = "현재 표시 결과"
            job_kwargs = {
                "keyword": self.db_keyword,
                "exclude_words": self.exclude_words,
                "only_bookmark": self.is_bookmark_tab,
                "filter_txt": self._current_filter_text(),
                "hide_duplicates": self.chk_hide_dup.isChecked(),
                "start_date": start_date,
                "end_date": end_date,
                "query_key": self.query_key,
            }
        else:
            self._mark_all_mode_label = "탭 전체"
            job_kwargs = {
                "keyword": self.db_keyword,
                "exclude_words": self.exclude_words,
                "only_bookmark": self.is_bookmark_tab,
                "filter_txt": "",
                "hide_duplicates": False,
                "start_date": None,
                "end_date": None,
                "query_key": self.query_key,
            }

        if not self._begin_mark_all_read_maintenance():
            return

        def job_func(context) -> int:
            def report_progress(current: int, total: int) -> None:
                context.check_cancelled()
                context.report(
                    current=current,
                    total=total,
                    message="읽음 상태 반영 중...",
                )

            return int(
                self.db.mark_query_as_read_chunked(
                    chunk_size=200,
                    progress_callback=report_progress,
                    cancel_check=context.check_cancelled,
                    **job_kwargs,
                )
            )

        try:
            worker_cls = _NewsTabActionsMixin._runtime_attr(self, "IterativeJobWorker", IterativeJobWorker)
            self.job_worker = worker_cls(job_func, parent=None)
            self.job_worker.finished.connect(self._on_mark_all_read_done)
            self.job_worker.error.connect(self._on_mark_all_read_error)
            self.job_worker.cancelled.connect(self._on_mark_all_read_cancelled)
            self.job_worker.start()
        except Exception as exc:
            self._finalize_mark_all_read(error_message=str(exc))

    def _begin_mark_all_read_maintenance(self) -> bool:
        parent = self._main_window()
        if parent is None:
            return True
        begin_database_maintenance = getattr(parent, "begin_database_maintenance", None)
        if not callable(begin_database_maintenance):
            return True
        result = begin_database_maintenance("mark_all_read")
        if isinstance(result, tuple) and len(result) >= 2:
            started = bool(result[0])
            reason = str(result[1] or "")
        else:
            started = bool(result)
            reason = ""
        if not started:
            self.lbl_status.setText("읽음 처리 작업을 시작할 수 없습니다.")
            message_box_cls = _NewsTabActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
            message_box_cls.warning(
                self,
                "유지보수 시작 실패",
                reason or "활성 작업을 정리하지 못해 읽음 처리를 시작할 수 없습니다.",
            )
            return False
        self._mark_all_maintenance_active = True
        return True

    def _release_mark_all_read_worker(self) -> None:
        worker = getattr(self, "job_worker", None)
        if worker is None:
            return
        detach_worker_signals = getattr(self, "_detach_worker_signals", None)
        if callable(detach_worker_signals):
            detach_worker_signals(worker, ("finished", "error", "cancelled", "progress"))
        try:
            worker.deleteLater()
        except Exception:
            pass
        self.job_worker = None

    def _end_mark_all_read_maintenance(self) -> None:
        if not getattr(self, "_mark_all_maintenance_active", False):
            return
        self._mark_all_maintenance_active = False
        parent = self._main_window()
        if parent is None:
            return
        end_database_maintenance = getattr(parent, "end_database_maintenance", None)
        if callable(end_database_maintenance):
            try:
                end_database_maintenance()
            except Exception:
                pass

    def _finalize_mark_all_read(
        self,
        *,
        count: Optional[int] = None,
        error_message: str = "",
        cancelled: bool = False,
    ) -> None:
        self._release_mark_all_read_worker()
        self._end_mark_all_read_maintenance()

        candidate_parent = self._main_window()
        parent = cast(Optional[MainWindowProtocol], candidate_parent) if candidate_parent is not None else None
        if count is not None:
            if parent is not None and hasattr(parent, "on_database_maintenance_completed"):
                parent.on_database_maintenance_completed("mark_all_read", int(count or 0))
            elif not getattr(self, "_is_closing", False):
                self.load_data_from_db()

        if getattr(self, "_is_closing", False):
            return

        self.btn_read_all.setEnabled(True)

        if count is not None:
            mode_label = getattr(self, "_mark_all_mode_label", "선택 범위")
            self.lbl_status.setText(f"✓ {mode_label} {int(count or 0)}개 읽음 처리 완료")
            if parent is not None:
                parent.show_toast(f"✓ {mode_label} {count}개의 기사를 읽음으로 표시했습니다.")
            return

        if cancelled:
            self.lbl_status.setText("읽음 처리 작업이 취소되었습니다.")
            if parent is not None:
                parent.show_warning_toast("읽음 처리 작업이 취소되었습니다.")
            return

        self.lbl_status.setText("오류 발생")
        message_box_cls = _NewsTabActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
        message_box_cls.critical(self, "오류", f"처리 중 오류가 발생했습니다:\n\n{error_message}")

    def _on_mark_all_read_done(self, count):
        """모두 읽음 처리 완료"""
        self._finalize_mark_all_read(count=int(count or 0))

    def _on_mark_all_read_error(self, err_msg):
        """모두 읽음 처리 오류"""
        self._finalize_mark_all_read(error_message=str(err_msg or "알 수 없는 오류"))

    def _on_mark_all_read_cancelled(self):
        self._finalize_mark_all_read(cancelled=True)

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

        elif action == "delete":
            self._delete_target(target)
