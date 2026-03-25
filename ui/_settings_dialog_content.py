# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.notifications import NotificationSound
from core.startup import StartupManager
from ui.widgets import NoScrollComboBox

if TYPE_CHECKING:
    from ui.settings_dialog import SettingsDialog


class _SettingsDialogContentMixin:
    def _theme_colors(self: SettingsDialog) -> tuple[str, str]:
        if self.is_dark:
            return "#1A1A1D", "#FFFFFF"
        return "#FFFFFF", "#000000"

    def _build_settings_tab(
        self: SettingsDialog,
        bg_color: str,
        text_color: str,
    ) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {bg_color}; border: none; }}"
        )

        settings_widget = QWidget()
        settings_widget.setStyleSheet(
            f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}"
        )
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.addWidget(self._build_api_group())
        settings_layout.addWidget(self._build_general_group())
        settings_layout.addWidget(self._build_tray_group())
        settings_layout.addWidget(self._build_data_group())
        settings_layout.addWidget(self._build_notification_group())
        settings_layout.addStretch()

        scroll_area.setWidget(settings_widget)
        return scroll_area

    def _build_help_tab(
        self: SettingsDialog,
        bg_color: str,
        text_color: str,
    ) -> QWidget:
        help_widget = QWidget()
        help_widget.setStyleSheet(
            f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}"
        )
        help_layout = QVBoxLayout(help_widget)
        help_browser = QTextBrowser()
        help_browser.setOpenExternalLinks(True)
        help_browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}"
        )
        help_browser.setHtml(self.get_help_html())
        help_layout.addWidget(help_browser)
        return help_widget

    def _build_shortcuts_tab(
        self: SettingsDialog,
        bg_color: str,
        text_color: str,
    ) -> QWidget:
        shortcuts_widget = QWidget()
        shortcuts_widget.setStyleSheet(
            f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}"
        )
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        shortcuts_browser = QTextBrowser()
        shortcuts_browser.setOpenExternalLinks(False)
        shortcuts_browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}"
        )
        shortcuts_browser.setHtml(self.get_shortcuts_html())
        shortcuts_layout.addWidget(shortcuts_browser)
        return shortcuts_widget

    def _build_api_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("📡 네이버 API 설정")
        form = QGridLayout()

        self.txt_id = QLineEdit(self.config.get("client_id", ""))
        self.txt_id.setPlaceholderText("네이버 개발자센터에서 발급받은 Client ID")

        self.txt_sec = QLineEdit(self.config.get("client_secret", ""))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_sec.setPlaceholderText("Client Secret")

        self.chk_show_pw = QCheckBox("비밀번호 표시")
        self.chk_show_pw.stateChanged.connect(
            lambda: self.txt_sec.setEchoMode(
                QLineEdit.EchoMode.Normal
                if self.chk_show_pw.isChecked()
                else QLineEdit.EchoMode.Password
            )
        )

        btn_get_key = QPushButton("🔑 API 키 발급받기")
        btn_get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://developers.naver.com/apps/#/register")
            )
        )

        self.btn_validate = QPushButton("✓ API 키 검증")
        self.btn_validate.clicked.connect(self.validate_api_key)

        form.addWidget(QLabel("Client ID:"), 0, 0)
        form.addWidget(self.txt_id, 0, 1, 1, 2)
        form.addWidget(QLabel("Client Secret:"), 1, 0)
        form.addWidget(self.txt_sec, 1, 1, 1, 2)
        form.addWidget(self.chk_show_pw, 2, 1)
        form.addWidget(btn_get_key, 3, 0, 1, 2)
        form.addWidget(self.btn_validate, 3, 2)

        group.setLayout(form)
        return group

    def _build_general_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("⚙ 일반 설정")
        form = QGridLayout()

        self.cb_time = NoScrollComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "2시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get("interval", 2)
        self.cb_time.setCurrentIndex(idx if isinstance(idx, int) and 0 <= idx <= 5 else 2)

        self.cb_theme = NoScrollComboBox()
        self.cb_theme.addItems(["☀ 라이트 모드", "🌙 다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get("theme", 0))

        self.spn_api_timeout = QSpinBox()
        self.spn_api_timeout.setRange(5, 60)
        self.spn_api_timeout.setSuffix("초")
        timeout_value = self.config.get("api_timeout", 15)
        try:
            timeout_value = int(timeout_value)
        except (TypeError, ValueError):
            timeout_value = 15
        self.spn_api_timeout.setValue(max(5, min(60, timeout_value)))

        form.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form.addWidget(self.cb_time, 0, 1)
        form.addWidget(QLabel("테마:"), 1, 0)
        form.addWidget(self.cb_theme, 1, 1)
        form.addWidget(QLabel("API 타임아웃:"), 2, 0)
        form.addWidget(self.spn_api_timeout, 2, 1)

        group.setLayout(form)
        return group

    def _build_tray_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("🖥️ 시스템 트레이 및 시작 설정")
        layout = QVBoxLayout()

        self.chk_minimize_to_tray = QCheckBox("최소화 버튼 클릭 시 트레이로 최소화")
        self.chk_minimize_to_tray.setChecked(self.config.get("minimize_to_tray", True))
        layout.addWidget(self.chk_minimize_to_tray)

        self.chk_close_to_tray = QCheckBox("X 버튼 클릭 시 트레이로 최소화 (종료하지 않음)")
        self.chk_close_to_tray.setChecked(self.config.get("close_to_tray", True))
        layout.addWidget(self.chk_close_to_tray)

        self.chk_auto_start = QCheckBox("윈도우 시작 시 자동 실행")
        if StartupManager.is_available():
            desired_minimized = bool(self.config.get("start_minimized", False))
            startup_status = StartupManager.get_startup_status(start_minimized=desired_minimized)
            self.chk_auto_start.setChecked(
                bool(startup_status.get("has_registry_value"))
                or bool(self.config.get("auto_start_enabled", False))
            )
        else:
            self.chk_auto_start.setEnabled(False)
            self.chk_auto_start.setToolTip("Windows에서만 사용 가능합니다.")
        layout.addWidget(self.chk_auto_start)

        self.chk_start_minimized = QCheckBox("시작 시 최소화 상태로 시작 (트레이로)")
        tray_supported = QSystemTrayIcon.isSystemTrayAvailable()
        configured = bool(self.config.get("start_minimized", False))
        self.chk_start_minimized.setChecked(configured and tray_supported)
        if not tray_supported:
            self.chk_start_minimized.setEnabled(False)
            self.chk_start_minimized.setToolTip(
                "시스템 트레이를 사용할 수 없는 환경에서는 적용되지 않습니다."
            )
        layout.addWidget(self.chk_start_minimized)

        self.lbl_auto_start_status = QLabel("")
        self.lbl_auto_start_status.setWordWrap(True)
        self.lbl_auto_start_status.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(self.lbl_auto_start_status)

        self.btn_repair_auto_start = QPushButton("🔧 자동 시작 등록 수리")
        self.btn_repair_auto_start.clicked.connect(self.repair_startup_registration)
        layout.addWidget(self.btn_repair_auto_start)

        self.chk_notify_on_refresh = QCheckBox("자동 새로고침 완료 시 알림 표시")
        self.chk_notify_on_refresh.setChecked(self.config.get("notify_on_refresh", False))
        layout.addWidget(self.chk_notify_on_refresh)

        tray_info = QLabel(
            "💡 트레이로 최소화하면 백그라운드에서 뉴스를 계속 수집합니다.\n"
            "트레이 미지원 환경에서는 시작 최소화가 적용되지 않습니다."
        )
        tray_info.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(tray_info)

        self.chk_auto_start.toggled.connect(lambda _checked: self.refresh_startup_status())
        self.chk_start_minimized.toggled.connect(lambda _checked: self.refresh_startup_status())
        self.refresh_startup_status()

        group.setLayout(layout)
        return group

    def _build_data_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("🗂 데이터 관리")
        layout = QVBoxLayout()

        self.btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        self.btn_clean.clicked.connect(self.clean_data)
        layout.addWidget(self.btn_clean)

        self.btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        self.btn_all.clicked.connect(self.clean_all)
        layout.addWidget(self.btn_all)

        backup_layout = QHBoxLayout()
        btn_export_settings = QPushButton("📤 설정 내보내기")
        btn_export_settings.clicked.connect(self.export_settings_dialog)
        btn_import_settings = QPushButton("📥 설정 가져오기")
        btn_import_settings.clicked.connect(self.import_settings_dialog)
        backup_layout.addWidget(btn_export_settings)
        backup_layout.addWidget(btn_import_settings)
        layout.addLayout(backup_layout)

        tools_layout = QHBoxLayout()
        btn_log = QPushButton("📋 로그 보기")
        btn_log.clicked.connect(self.show_log_dialog)
        btn_folder = QPushButton("📁 데이터 폴더")
        btn_folder.clicked.connect(self.open_data_folder)
        btn_groups = QPushButton("🗂 키워드 그룹")
        btn_groups.clicked.connect(self.show_groups_dialog)
        tools_layout.addWidget(btn_log)
        tools_layout.addWidget(btn_folder)
        tools_layout.addWidget(btn_groups)
        layout.addLayout(tools_layout)

        group.setLayout(layout)
        return group

    def _build_notification_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("🔔 알림 설정")
        layout = QVBoxLayout()

        self.chk_notification = QCheckBox("데스크톱 알림 활성화 (새 뉴스 도착 시)")
        self.chk_notification.setChecked(self.config.get("notification_enabled", True))
        layout.addWidget(self.chk_notification)

        layout.addWidget(QLabel("알림 키워드 (쉼표로 구분, 최대 10개):"))

        self.txt_alert_keywords = QLineEdit()
        current_keywords = self.config.get("alert_keywords", [])
        self.txt_alert_keywords.setText(", ".join(current_keywords) if current_keywords else "")
        self.txt_alert_keywords.setPlaceholderText("예: 긴급, 속보, 단독")
        layout.addWidget(self.txt_alert_keywords)

        keywords_info = QLabel("💡 위 키워드가 기사 제목이나 내용에 포함되면 알림이 표시됩니다.")
        keywords_info.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(keywords_info)

        self.chk_sound = QCheckBox("알림 소리 활성화")
        self.chk_sound.setChecked(self.config.get("sound_enabled", True))
        layout.addWidget(self.chk_sound)

        btn_test_sound = QPushButton("🔊 소리 테스트")
        btn_test_sound.clicked.connect(lambda: NotificationSound.play("success"))
        layout.addWidget(btn_test_sound)

        group.setLayout(layout)
        return group
