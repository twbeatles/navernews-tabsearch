# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

import requests
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

from core.constants import CONFIG_FILE, DB_FILE
from core.database import DatabaseManager
from core.http_client import HttpClientConfig
from core.validation import ValidationUtils
from core.workers import AsyncJobWorker, IterativeJobWorker

if TYPE_CHECKING:
    from ui.settings_dialog import SettingsDialog


class _SettingsDialogTasksMixin:
    def _current_api_timeout(self: SettingsDialog) -> int:
        timeout_value = 15
        if hasattr(self, "spn_api_timeout"):
            try:
                timeout_value = int(self.spn_api_timeout.value())
            except Exception:
                timeout_value = 15
        return max(5, min(60, timeout_value))

    def _create_validation_session(self: SettingsDialog):
        parent = self._typed_parent()
        if parent is not None:
            create_http_session = getattr(parent, "create_http_session", None)
            if callable(create_http_session):
                return create_http_session()
        return HttpClientConfig().create_session()

    def _run_api_validation_request(
        self: SettingsDialog,
        client_id: str,
        client_secret: str,
        *,
        timeout: int,
    ) -> Dict[str, Any]:
        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }
        session = self._create_validation_session()
        try:
            response = session.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers=headers,
                params={"query": "테스트", "display": 1},
                timeout=max(5, int(timeout)),
            )
            payload: Dict[str, Any] = {
                "status_code": int(response.status_code),
                "error_kind": "",
                "error_message": "",
            }
            if response.status_code != 200:
                payload["error_kind"] = "http_error"
                try:
                    payload["error_message"] = response.json().get(
                        "errorMessage",
                        "알 수 없는 오류",
                    )
                except (ValueError, TypeError, KeyError):
                    payload["error_message"] = (
                        response.text[:200] if response.text else "응답 파싱 실패"
                    )
            return payload
        except requests.Timeout:
            return {
                "status_code": 0,
                "error_kind": "timeout",
                "error_message": f"{max(5, int(timeout))}초 내 응답이 없어 검증에 실패했습니다.",
            }
        except requests.RequestException as e:
            return {
                "status_code": 0,
                "error_kind": "network_error",
                "error_message": str(e) or "네트워크 요청 실패",
            }
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _detach_worker_signals(
        self: SettingsDialog,
        worker: Optional[Any],
    ):
        if not worker:
            return
        try:
            worker.finished.disconnect()
        except Exception:
            pass
        try:
            worker.error.disconnect()
        except Exception:
            pass
        try:
            worker.cancelled.disconnect()
        except Exception:
            pass
        try:
            worker.progress.disconnect()
        except Exception:
            pass

    def _shutdown_worker(
        self: SettingsDialog,
        worker: Optional[Any],
        wait_ms: int = 500,
    ):
        if not worker:
            return True
        self._detach_worker_signals(worker)
        try:
            worker.requestInterruption()
        except Exception:
            pass
        try:
            worker.quit()
        except Exception:
            pass
        try:
            finished = worker.wait(wait_ms)
        except Exception:
            finished = False

        if finished:
            try:
                worker.deleteLater()
            except Exception:
                pass
            return True

        try:
            worker.setParent(None)
        except Exception:
            pass
        try:
            worker.finished.connect(worker.deleteLater)
        except Exception:
            pass
        return False

    def _create_worker(
        self: SettingsDialog,
        job_func: Callable[..., Any],
    ) -> AsyncJobWorker:
        worker = AsyncJobWorker(job_func, parent=None)
        try:
            worker.finished.connect(worker.deleteLater)
        except Exception:
            pass
        return worker

    def _create_iterative_worker(
        self: SettingsDialog,
        job_func: Callable[..., Any],
    ) -> IterativeJobWorker:
        worker = IterativeJobWorker(job_func, parent=None)
        try:
            worker.finished.connect(worker.deleteLater)
        except Exception:
            pass
        try:
            worker.cancelled.connect(worker.deleteLater)
        except Exception:
            pass
        return worker

    def validate_api_key(self: SettingsDialog):
        if self._is_closing:
            return
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()
        valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
        if not valid:
            QMessageBox.warning(self, "검증 실패", msg)
            return

        if self._api_validate_worker and self._api_validate_worker.isRunning():
            QMessageBox.information(self, "진행 중", "이미 API 키 검증이 진행 중입니다.")
            return

        self.btn_validate.setEnabled(False)
        self.btn_validate.setText("⏳ 검증 중...")
        timeout = self._current_api_timeout()

        def validate_job() -> Dict[str, Any]:
            return self._run_api_validation_request(
                client_id,
                client_secret,
                timeout=timeout,
            )

        self._api_validate_worker = self._create_worker(validate_job)
        self._api_validate_worker.finished.connect(self._on_validate_api_key_done)
        self._api_validate_worker.error.connect(self._on_validate_api_key_error)
        self._api_validate_worker.finished.connect(self._on_validate_api_key_finished)
        self._api_validate_worker.error.connect(self._on_validate_api_key_finished)
        self._api_validate_worker.start()

    def _on_validate_api_key_done(self: SettingsDialog, result: Dict[str, Any]):
        if self._is_closing or not self.isVisible():
            return
        if int(result.get("status_code", 0)) == 200:
            QMessageBox.information(self, "검증 성공", "✓ API 키가 정상적으로 작동합니다!")
            return
        error_kind = str(result.get("error_kind", "") or "")
        error_message = str(result.get("error_message", "알 수 없는 오류") or "알 수 없는 오류")
        if error_kind == "timeout":
            QMessageBox.warning(
                self,
                "검증 시간 초과",
                f"API 키 검증 중 시간이 초과되었습니다.\n\n오류: {error_message}",
            )
            return
        if error_kind == "network_error":
            QMessageBox.warning(
                self,
                "네트워크 오류",
                f"API 키 검증 중 네트워크 오류가 발생했습니다.\n\n오류: {error_message}",
            )
            return
        QMessageBox.warning(
            self,
            "검증 실패",
            f"API 키가 올바르지 않습니다.\n\n오류: {error_message}",
        )

    def _on_validate_api_key_error(self: SettingsDialog, error_msg: str):
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.critical(
            self,
            "검증 오류",
            f"API 키 검증 중 오류가 발생했습니다:\n\n{error_msg}",
        )

    def _on_validate_api_key_finished(self: SettingsDialog, *_args):
        if self._is_closing:
            self._api_validate_worker = None
            return
        self.btn_validate.setEnabled(True)
        self.btn_validate.setText("✓ API 키 검증")
        self._api_validate_worker = None

    def clean_data(self: SettingsDialog):
        reply = QMessageBox.question(
            self,
            "데이터 정리",
            "30일 이전의 기사를 삭제하시겠습니까?\n\n(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def job_func(context) -> int:
            db = DatabaseManager(DB_FILE)
            try:
                return int(
                    db.delete_old_news_chunked(
                        30,
                        chunk_size=200,
                        progress_callback=lambda current, total: context.report(
                            current=current,
                            total=total,
                            message="오래된 기사 삭제 중...",
                        ),
                        cancel_check=context.check_cancelled,
                    )
                )
            finally:
                db.close()

        self._start_data_task(job_func, self._on_clean_data_done, "delete_old_news")

    def clean_all(self: SettingsDialog):
        reply = QMessageBox.warning(
            self,
            "⚠ 경고",
            "정말 모든 기사를 삭제하시겠습니까?\n\n"
            "이 작업은 취소할 수 없습니다.\n"
            "(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def job_func(context) -> int:
            db = DatabaseManager(DB_FILE)
            try:
                return int(
                    db.delete_all_news_chunked(
                        chunk_size=200,
                        progress_callback=lambda current, total: context.report(
                            current=current,
                            total=total,
                            message="기사 삭제 중...",
                        ),
                        cancel_check=context.check_cancelled,
                    )
                )
            finally:
                db.close()

        self._start_data_task(job_func, self._on_clean_all_done, "delete_all_news")

    def _start_data_task(
        self: SettingsDialog,
        job_func: Callable[[Any], int],
        done_handler: Callable[[Any], None],
        operation: str,
    ):
        if self._is_closing:
            return
        if self._data_task_worker and self._data_task_worker.isRunning():
            QMessageBox.information(self, "진행 중", "이미 데이터 정리 작업이 진행 중입니다.")
            return

        maintenance_active = False
        parent = self._typed_parent()
        if parent is not None:
            try:
                started, reason = parent.begin_database_maintenance(operation)
            except Exception as e:
                started = False
                reason = str(e)
            if not started:
                QMessageBox.warning(
                    self,
                    "유지보수 시작 실패",
                    reason or "활성 새로고침 작업을 정리하지 못해 데이터 정리를 시작할 수 없습니다.",
                )
                return
            maintenance_active = True
        setattr(self, "_maintenance_active_for_data_task", maintenance_active)
        setattr(self, "_pending_parent_data_change", None)

        self.btn_clean.setEnabled(False)
        self.btn_all.setEnabled(False)
        self.btn_clean.setText("⏳ 작업 중...")
        self.btn_all.setText("⏳ 작업 중...")

        self._data_task_worker = self._create_iterative_worker(job_func)
        self._data_task_worker.finished.connect(done_handler)
        self._data_task_worker.error.connect(self._on_data_task_error)
        self._data_task_worker.cancelled.connect(self._on_data_task_cancelled)
        self._data_task_worker.finished.connect(self._on_data_task_finished)
        self._data_task_worker.error.connect(self._on_data_task_finished)
        self._data_task_worker.cancelled.connect(self._on_data_task_finished)
        self._data_task_worker.start()

    def _on_clean_data_done(self: SettingsDialog, result: Any):
        count = int(result)
        setattr(self, "_pending_parent_data_change", ("delete_old_news", count))
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.information(self, "완료", f"✓ {count:,}개의 오래된 기사를 삭제했습니다.")

    def _on_clean_all_done(self: SettingsDialog, result: Any):
        count = int(result)
        setattr(self, "_pending_parent_data_change", ("delete_all_news", count))
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.information(self, "완료", f"✓ {count:,}개의 기사를 삭제했습니다.")

    def _on_data_task_error(self: SettingsDialog, error_msg: str):
        setattr(self, "_pending_parent_data_change", None)
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.critical(self, "작업 오류", f"데이터 작업 중 오류가 발생했습니다:\n\n{error_msg}")

    def _on_data_task_cancelled(self: SettingsDialog):
        setattr(self, "_pending_parent_data_change", None)
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.information(self, "작업 취소", "데이터 정리 작업이 취소되었습니다.")

    def _on_data_task_finished(self: SettingsDialog, *_args):
        parent = self._typed_parent()
        maintenance_active = bool(getattr(self, "_maintenance_active_for_data_task", False))
        if maintenance_active:
            if parent is not None:
                try:
                    parent.end_database_maintenance()
                except Exception:
                    pass
        setattr(self, "_maintenance_active_for_data_task", False)
        pending_change = getattr(self, "_pending_parent_data_change", None)
        setattr(self, "_pending_parent_data_change", None)
        if pending_change is not None and parent is not None:
            operation, affected_count = pending_change
            self._notify_parent_data_changed(operation, affected_count)

        if self._is_closing:
            self._data_task_worker = None
            return
        self.btn_clean.setEnabled(True)
        self.btn_all.setEnabled(True)
        self.btn_clean.setText("🧹 오래된 데이터 정리 (30일 이전)")
        self.btn_all.setText("🗑 모든 기사 삭제 (북마크 제외)")
        self._data_task_worker = None

    def _notify_parent_data_changed(
        self: SettingsDialog,
        operation: str,
        affected_count: int,
    ):
        parent = self._typed_parent()
        if parent is not None:
            try:
                parent.on_database_maintenance_completed(operation, affected_count)
            except Exception:
                pass

    def export_settings_dialog(self: SettingsDialog):
        parent = self._typed_parent()
        if parent is not None:
            parent.export_settings()

    def import_settings_dialog(self: SettingsDialog):
        parent = self._typed_parent()
        if parent is not None:
            parent.import_settings()

    def show_log_dialog(self: SettingsDialog):
        parent = self._typed_parent()
        if parent is not None:
            parent.show_log_viewer()

    def open_data_folder(self: SettingsDialog):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE))))

    def show_groups_dialog(self: SettingsDialog):
        parent = self._typed_parent()
        if parent is not None:
            parent.show_keyword_groups()
