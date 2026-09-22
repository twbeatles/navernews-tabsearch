"""Main-window integration for signed GitHub Release updates."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, cast

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from core.constants import (
    UPDATE_ARTIFACT_MAX_BYTES,
    UPDATE_MANIFEST_URL,
    UPDATE_PUBLIC_KEY_B64,
    UPDATE_RELEASES_URL,
    VERSION,
)
from core.update_installer import (
    cleanup_update_artifacts,
    consume_update_result,
    launch_update_helper,
    prepare_staged_update,
    resolve_update_staging_root,
    update_result_path,
)
from core.update_manifest import NoUpdateAvailableError, ReleaseManifest, download_release_manifest, verify_release_manifest

logger = logging.getLogger(__name__)


class _UpdateBridge(QObject):
    checked = pyqtSignal(object, object, bool)
    downloaded = pyqtSignal(object, object)


def _fit_dialog_buttons(dialog: QMessageBox, horizontal_slack: int = 28) -> None:
    """업데이트 팝업 버튼의 텍스트가 잘리지 않도록 최소 너비를 보장한다.

    QMessageBox 버튼 박스는 가장 넓은 버튼 기준으로 너비를 맞추는데, 폰트·DPI
    차이가 있는 환경에서는 끝 글자가 잘려 "글자가 안 보인다"는 민원으로
    이어진다. sizeHint 기준으로 여유를 더해 잘림을 방지한다.
    """
    for button in dialog.findChildren(QPushButton):
        button.setMinimumWidth(max(button.minimumWidth(), button.sizeHint().width() + horizontal_slack))


class _MainWindowUpdateMixin:
    def init_update_support(self) -> None:
        self._update_busy = False
        self._update_shutdown_requested = False
        self._update_bridge = _UpdateBridge(cast(QObject, self))
        self._update_bridge.checked.connect(self._on_update_checked)
        self._update_bridge.downloaded.connect(self._on_update_downloaded)
        staging_root = resolve_update_staging_root(self._data_dir())
        cleanup_update_artifacts(staging_root)
        self._pending_update_result = consume_update_result(update_result_path(staging_root))
        QTimer.singleShot(0, self._show_pending_update_result)

    def check_for_updates(self, interactive: bool = True) -> None:
        if self._update_busy:
            if interactive:
                self._toast("이미 업데이트를 확인하고 있습니다.")
            return
        self._update_busy = True
        if interactive:
            self._status().showMessage("GitHub 릴리스 업데이트를 확인 중...", 0)

        def work() -> None:
            try:
                manifest = verify_release_manifest(
                    download_release_manifest(UPDATE_MANIFEST_URL),
                    public_key=UPDATE_PUBLIC_KEY_B64,
                    current_version=VERSION,
                    max_artifact_bytes=UPDATE_ARTIFACT_MAX_BYTES,
                )
                self._emit_checked(manifest, None, interactive)
            except Exception as exc:
                self._emit_checked(None, exc, interactive)

        threading.Thread(target=work, name="UpdateCheckWorker", daemon=True).start()

    def on_update_button_clicked(self, _checked: bool = False) -> None:
        """Run an interactive check; QPushButton.clicked supplies a bool argument."""
        self.check_for_updates(interactive=True)

    def _on_update_checked(self, manifest: object, error: object, interactive: bool) -> None:
        self._update_busy = False
        if isinstance(error, NoUpdateAvailableError):
            if interactive:
                QMessageBox.information(self._widget(), "업데이트", "현재 최신 버전을 사용 중입니다.")
            return
        if error is not None:
            logger.warning("Update check failed: %s", error)
            if interactive:
                self._show_update_error(str(error))
            return
        if not isinstance(manifest, ReleaseManifest):
            if interactive:
                self._show_update_error("업데이트 응답 형식이 올바르지 않습니다.")
            return
        if not getattr(sys, "frozen", False):
            if interactive:
                QMessageBox.information(self._widget(), "업데이트", f"새 버전 {manifest.version}이 있습니다. 개발 실행에서는 자동 설치를 사용할 수 없습니다.")
            return
        dialog = QMessageBox(self._widget())
        dialog.setWindowTitle("업데이트 발견")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(f"새 버전 {manifest.version}이 있습니다.\n\n현재 버전: {VERSION}\n최신 버전: {manifest.version}")
        install = dialog.addButton("다운로드 및 설치", QMessageBox.ButtonRole.AcceptRole)
        release = dialog.addButton("릴리스 페이지 보기", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        _fit_dialog_buttons(dialog)
        dialog.exec()
        if dialog.clickedButton() is release:
            QDesktopServices.openUrl(QUrl(UPDATE_RELEASES_URL))
        elif dialog.clickedButton() is install:
            self._download_update(manifest)

    def _download_update(self, manifest: ReleaseManifest) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        self._status().showMessage(f"업데이트 {manifest.version} 다운로드 및 검증 중...", 0)

        def work() -> None:
            try:
                staged = prepare_staged_update(manifest, staging_root=resolve_update_staging_root(self._data_dir()))
                if self._update_shutdown_requested:
                    staged.unlink(missing_ok=True)
                    return
                self._update_bridge.downloaded.emit((manifest, staged), None)
            except Exception as exc:
                if not self._update_shutdown_requested:
                    self._update_bridge.downloaded.emit(None, exc)

        threading.Thread(target=work, name="UpdateDownloadWorker", daemon=True).start()

    def _on_update_downloaded(self, payload: object, error: object) -> None:
        self._update_busy = False
        if error is not None or not isinstance(payload, tuple):
            self._show_update_error(str(error or "업데이트 파일을 준비하지 못했습니다."))
            return
        manifest, staged = payload
        if not isinstance(manifest, ReleaseManifest) or not isinstance(staged, Path):
            self._show_update_error("업데이트 설치 정보가 올바르지 않습니다.")
            return
        if QMessageBox.question(self._widget(), "업데이트 검증 완료", f"업데이트 {manifest.version}의 서명과 파일 무결성을 확인했습니다. 지금 설치하시겠습니까?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            staged.unlink(missing_ok=True)
            self._status().showMessage("업데이트 설치를 취소했습니다.", 3000)
            return
        try:
            safe_to_close, reason = self._prepare_update_shutdown()
            if not safe_to_close:
                staged.unlink(missing_ok=True)
                self._show_update_error(reason)
                return
            launch_update_helper(
                target=Path(sys.executable),
                staged=staged,
                version=VERSION,
                sha256=manifest.artifact_sha256,
                size=manifest.artifact_size,
                result_file=update_result_path(resolve_update_staging_root(self._data_dir())),
            )
        except Exception as exc:
            staged.unlink(missing_ok=True)
            self._update_shutdown_requested = False
            self._show_update_error(f"업데이트 설치를 시작하지 못했습니다: {exc}")
            return
        self._status().showMessage("업데이트 설치를 위해 프로그램을 종료합니다.", 3000)
        cast(Any, self).real_quit()

    def _show_update_error(self, detail: str) -> None:
        logger.warning("Update error: %s", detail)
        dialog = QMessageBox(self._widget())
        dialog.setWindowTitle("업데이트 실패")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(f"자동 업데이트를 완료하지 못했습니다.\n\n오류: {detail}")
        release = dialog.addButton("릴리스 페이지 열기", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        _fit_dialog_buttons(dialog)
        dialog.exec()
        if dialog.clickedButton() is release:
            QDesktopServices.openUrl(QUrl(UPDATE_RELEASES_URL))

    def _widget(self) -> QWidget:
        return cast(QWidget, self)

    def _status(self) -> Any:
        return cast(Any, self)._status_bar()

    def _data_dir(self) -> str:
        return str(cast(Any, self).runtime_paths.data_dir)

    def _toast(self, message: str) -> None:
        cast(Any, self).show_toast(message)

    def _prepare_update_shutdown(self) -> tuple[bool, str]:
        window = cast(Any, self)
        if window.is_maintenance_mode_active():
            return False, "다른 유지보수 작업이 진행 중이라 업데이트를 설치할 수 없습니다."
        ok, unfinished = window._cancel_active_fetch_workers(wait_ms=3000)
        if not ok:
            return False, "활성 작업을 안전하게 종료하지 못했습니다: " + ", ".join(unfinished)
        for worker_name in ("_fts_backfill_worker", "_cloud_sync_worker", "_tray_unread_worker"):
            worker = getattr(window, worker_name, None)
            if worker is None or not worker.isRunning():
                continue
            try:
                request_stop = getattr(worker, "requestInterruption", None) or getattr(worker, "stop", None)
                if callable(request_stop):
                    request_stop()
                if not worker.wait(3000):
                    return False, f"{worker_name} 작업을 안전하게 종료하지 못했습니다."
            except Exception as exc:
                return False, f"{worker_name} 종료 중 오류가 발생했습니다: {exc}"
        self._update_shutdown_requested = True
        return True, ""

    def _show_pending_update_result(self) -> None:
        result = getattr(self, "_pending_update_result", None)
        self._pending_update_result = None
        if not isinstance(result, dict):
            return
        status = str(result.get("status", ""))
        if status == "applied":
            self._status().showMessage("업데이트가 성공적으로 설치되었습니다.", 5000)
            self._toast("업데이트가 성공적으로 설치되었습니다.")
            return
        detail = str(result.get("error", "알 수 없는 오류"))
        message = "업데이트 설치에 실패했습니다." if status == "failed" else "업데이트 설치 후 이전 버전으로 복구했습니다."
        logger.warning("Update helper result (%s): %s", status, detail)
        self._status().showMessage(f"{message} {detail}", 8000)
        self._toast(message)

    def shutdown_update_support(self) -> None:
        self._update_shutdown_requested = True

    def _emit_checked(self, manifest: object, error: object, interactive: bool) -> None:
        if not self._update_shutdown_requested:
            self._update_bridge.checked.emit(manifest, error, interactive)
