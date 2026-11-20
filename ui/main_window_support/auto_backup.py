"""Background database backups with GUI-thread completion and bounded alerts."""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

logger = logging.getLogger(__name__)


class _AutoBackupWorker(QThread):
    completed = Signal(object)

    def __init__(self, auto_backup: Any, parent: QObject):
        super().__init__(parent)
        self.auto_backup = auto_backup

    def run(self) -> None:
        try:
            path = self.auto_backup.create_backup(include_db=True, trigger="auto")
            self.completed.emit(
                {"path": path, "error": self.auto_backup.last_create_error}
            )
        except Exception as exc:
            logger.exception("자동 백업 실행 실패")
            self.completed.emit({"path": None, "error": str(exc)})


class _AutoBackupRelay(QObject):
    def __init__(self, owner: Any):
        super().__init__(owner)
        self.owner = owner

    @Slot(object)
    def completed(self, result: dict) -> None:
        owner = self.owner
        if getattr(owner, "_shutdown_in_progress", False):
            return
        if result.get("path"):
            owner._auto_backup_last_error_notified = ""
            return
        error = str(result.get("error") or "알 수 없는 오류")
        logger.warning("자동 백업 실패: %s", error)
        now = time.monotonic()
        previous = getattr(owner, "_auto_backup_last_error_notified", "")
        previous_at = getattr(owner, "_auto_backup_last_error_notified_at", 0.0)
        if error != previous or now - previous_at >= 3600:
            owner.show_warning_toast(
                f"자동 백업 실패: {error} (백업 및 복원에서 상태 확인)"
            )
            owner._auto_backup_last_error_notified = error
            owner._auto_backup_last_error_notified_at = now

    @Slot()
    def settled(self) -> None:
        self.owner._auto_backup_worker = None


class _MainWindowAutoBackupMixin:
    def _run_auto_backup_once(self: Any) -> None:
        if getattr(self, "_shutdown_in_progress", False):
            return
        worker = getattr(self, "_auto_backup_worker", None)
        if worker is not None:
            return
        # A SQLite online backup is safe during fetch, but defer during restore/merge.
        if self.is_maintenance_mode_active():
            return
        relay = _AutoBackupRelay(self)
        worker = _AutoBackupWorker(self.auto_backup, self)
        self._auto_backup_worker = worker
        worker.completed.connect(relay.completed)
        worker.finished.connect(relay.settled)
        worker.finished.connect(relay.deleteLater)
        worker.finished.connect(worker.deleteLater)
        worker.start()


def auto_backup_status_text(auto_backup: Any) -> str:
    status = auto_backup.get_auto_backup_status()
    success = str(status.get("last_success_at") or "아직 없음")
    scope = "DB + 설정" if status.get("last_success_include_db") else "설정만"
    text = f"최근 자동 백업 성공: {success}"
    if status.get("last_success_at"):
        text += f" ({scope})"
    if status.get("last_error"):
        text += (
            f"\n최근 실패 ({status.get('last_attempt_at', '')}): {status['last_error']}"
        )
    return text
