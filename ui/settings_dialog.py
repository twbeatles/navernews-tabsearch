from typing import Dict, Optional, cast

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QTabWidget, QVBoxLayout

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
