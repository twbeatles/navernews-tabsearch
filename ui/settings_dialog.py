from typing import Dict, Optional, cast

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QTabWidget, QVBoxLayout

from core.startup import StartupManager
from core.startup import StartupStatus
from core.validation import ValidationUtils
from core.workers import AsyncJobWorker
from ui._settings_dialog_content import _SettingsDialogContentMixin
from ui._settings_dialog_docs import _SettingsDialogDocsMixin
from ui._settings_dialog_tasks import _SettingsDialogTasksMixin
from ui.protocols import SettingsDialogParentProtocol


class SettingsDialog(
    _SettingsDialogContentMixin,
    _SettingsDialogDocsMixin,
    _SettingsDialogTasksMixin,
    QDialog,
):
    """설정 다이얼로그 (검증 기능 + 도움말 추가)"""

    def __init__(self, config: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 및 도움말")
        self.resize(600, 550)
        self.config = config
        self._api_validate_worker: Optional[AsyncJobWorker] = None
        self._data_task_worker: Optional[AsyncJobWorker] = None
        self._is_closing = False
        self._maintenance_active_for_data_task = False
        self._startup_status: Optional[StartupStatus] = None
        self.is_dark = False
        if parent and hasattr(parent, "theme_idx"):
            self.is_dark = parent.theme_idx == 1
        self.setup_ui()

    def _typed_parent(self) -> Optional[SettingsDialogParentProtocol]:
        candidate = self.parent()
        if candidate is None:
            return None
        required_attrs = (
            "begin_database_maintenance",
            "end_database_maintenance",
            "on_database_maintenance_completed",
            "export_settings",
            "import_settings",
            "show_log_viewer",
            "show_keyword_groups",
        )
        if not all(hasattr(candidate, attr) for attr in required_attrs):
            return None
        return cast(SettingsDialogParentProtocol, candidate)

    def refresh_startup_status(self):
        if not hasattr(self, "lbl_auto_start_status"):
            return

        if not hasattr(self, "btn_repair_auto_start"):
            return

        if not hasattr(self, "chk_auto_start"):
            return

        if not StartupManager.is_available():
            self._startup_status = None
            self.lbl_auto_start_status.setText("자동 시작 상태: Windows 환경에서만 지원됩니다.")
            self.btn_repair_auto_start.setEnabled(False)
            return

        desired_minimized = bool(
            hasattr(self, "chk_start_minimized") and self.chk_start_minimized.isChecked()
        )
        status = StartupManager.get_startup_status(start_minimized=desired_minimized)
        self._startup_status = status

        if not self.chk_auto_start.isChecked():
            if status.get("has_registry_value"):
                self.lbl_auto_start_status.setText(
                    "자동 시작 상태: 기존 등록이 남아 있습니다. 저장하면 해제됩니다."
                )
            else:
                self.lbl_auto_start_status.setText("자동 시작 상태: 비활성화됨")
            self.btn_repair_auto_start.setEnabled(False)
            return

        if status.get("is_healthy"):
            self.lbl_auto_start_status.setText("자동 시작 상태: 정상")
            self.btn_repair_auto_start.setEnabled(False)
            return

        if status.get("has_registry_value"):
            reasons = []
            if not status.get("command_matches"):
                reasons.append("명령 불일치")
            if status.get("actual_target") and not status.get("target_exists"):
                reasons.append("대상 경로 없음")
            reason_text = ", ".join(reasons) if reasons else "상태 불일치"
            self.lbl_auto_start_status.setText(f"자동 시작 상태: 수리 필요 ({reason_text})")
            self.btn_repair_auto_start.setEnabled(True)
            return

        self.lbl_auto_start_status.setText("자동 시작 상태: 저장하면 등록됩니다.")
        self.btn_repair_auto_start.setEnabled(False)

    def repair_startup_registration(self):
        if not StartupManager.is_available():
            QMessageBox.warning(self, "자동 시작", "Windows 환경에서만 자동 시작 수리를 지원합니다.")
            return

        if not hasattr(self, "chk_auto_start") or not self.chk_auto_start.isChecked():
            QMessageBox.information(self, "자동 시작", "먼저 '윈도우 시작 시 자동 실행'을 켜주세요.")
            return

        desired_minimized = bool(
            hasattr(self, "chk_start_minimized") and self.chk_start_minimized.isChecked()
        )
        if StartupManager.enable_startup(desired_minimized):
            QMessageBox.information(self, "자동 시작", "자동 시작 등록을 현재 설정 기준으로 다시 작성했습니다.")
        else:
            QMessageBox.warning(self, "자동 시작", "자동 시작 등록 수리에 실패했습니다.")
        self.refresh_startup_status()

    def setup_ui(self):
        """테마 적용 UI 설정"""
        layout = QVBoxLayout(self)
        bg_color, text_color = self._theme_colors()

        tab_widget = QTabWidget()
        tab_widget.addTab(self._build_settings_tab(bg_color, text_color), "⚙ 설정")
        tab_widget.addTab(self._build_help_tab(bg_color, text_color), "📖 도움말")
        tab_widget.addTab(self._build_shortcuts_tab(bg_color, text_color), "⌨ 단축키")
        layout.addWidget(tab_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept_with_validation)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_with_validation(self):
        """검증 후 저장"""
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()

        if client_id or client_secret:
            valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
            if not valid:
                reply = QMessageBox.question(
                    self,
                    "API 키 확인",
                    f"{msg}\n\n그래도 저장하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return

        self.accept()

    def closeEvent(self, a0: Optional[QCloseEvent]):
        self._is_closing = True
        self._shutdown_worker(self._api_validate_worker, wait_ms=400)
        self._shutdown_worker(self._data_task_worker, wait_ms=800)
        if self._maintenance_active_for_data_task:
            parent = self._typed_parent()
            if parent is not None:
                try:
                    parent.end_database_maintenance()
                except Exception:
                    pass
            self._maintenance_active_for_data_task = False
        self._api_validate_worker = None
        self._data_task_worker = None
        super().closeEvent(a0)

    def get_data(self) -> Dict:
        """설정 데이터 반환"""
        keywords_text = self.txt_alert_keywords.text().strip()
        alert_keywords = []
        if keywords_text:
            alert_keywords = [kw.strip() for kw in keywords_text.split(",") if kw.strip()][:10]

        return {
            "id": self.txt_id.text().strip(),
            "secret": self.txt_sec.text().strip(),
            "interval": self.cb_time.currentIndex(),
            "theme": self.cb_theme.currentIndex(),
            "notification_enabled": self.chk_notification.isChecked(),
            "alert_keywords": alert_keywords,
            "sound_enabled": self.chk_sound.isChecked(),
            "minimize_to_tray": self.chk_minimize_to_tray.isChecked(),
            "close_to_tray": self.chk_close_to_tray.isChecked(),
            "auto_start_enabled": self.chk_auto_start.isChecked(),
            "start_minimized": self.chk_start_minimized.isChecked(),
            "notify_on_refresh": self.chk_notify_on_refresh.isChecked(),
            "api_timeout": int(self.spn_api_timeout.value()),
        }
