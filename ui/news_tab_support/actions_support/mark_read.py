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


class _NewsTabMarkReadMixin:
    def mark_all_read(self):
        """모두 읽음으로 표시 (비동기)"""
        if getattr(self, "_is_closing", False):
            return
        if _NewsTabArticleActionsMixin._should_block_local_db_action(self, "mark all read"):
            return
        message_box_cls = _NewsTabArticleActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
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
        publisher_filter_settings = getattr(self, "_publisher_filter_settings", lambda: ((), ()))
        blocked_publishers, preferred_publishers = publisher_filter_settings()
        only_preferred_enabled = getattr(self, "_only_preferred_publishers_enabled", lambda: False)
        current_tag_filter = getattr(self, "_current_tag_filter", lambda: "")

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
                "blocked_publishers": list(blocked_publishers),
                "preferred_publishers": list(preferred_publishers),
                "only_preferred_publishers": bool(only_preferred_enabled()),
                "tag_filter": str(current_tag_filter()),
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
                "blocked_publishers": list(blocked_publishers),
                "preferred_publishers": list(preferred_publishers),
                "only_preferred_publishers": False,
                "tag_filter": "",
                "start_date": None,
                "end_date": None,
                "query_key": self.query_key,
            }

        if not self._begin_mark_all_read_maintenance():
            self.btn_read_all.setEnabled(True)
            self.lbl_status.setText("읽음 처리 작업을 시작하지 않았습니다.")
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
            worker_cls = _NewsTabArticleActionsMixin._runtime_attr(self, "IterativeJobWorker", IterativeJobWorker)
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
            message_box_cls = _NewsTabArticleActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
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
        if not delete_qthread_when_finished(worker):
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
        message_box_cls = _NewsTabArticleActionsMixin._runtime_attr(self, "QMessageBox", QMessageBox)
        message_box_cls.critical(self, "오류", f"처리 중 오류가 발생했습니다:\n\n{error_message}")

    def _on_mark_all_read_done(self, count):
        """모두 읽음 처리 완료"""
        self._finalize_mark_all_read(count=int(count or 0))

    def _on_mark_all_read_error(self, err_msg):
        """모두 읽음 처리 오류"""
        self._finalize_mark_all_read(error_message=str(err_msg or "알 수 없는 오류"))

    def _on_mark_all_read_cancelled(self):
        self._finalize_mark_all_read(cancelled=True)
