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
from ui._settings_dialog_tasks import CLEAN_ALL_LABEL, CLEAN_OLD_LABEL
from ui.widgets import NoScrollComboBox

if TYPE_CHECKING:
    from ui.settings_dialog import SettingsDialog


class _SettingsDialogContentMixin:
    def _build_settings_page(self: SettingsDialog, groups: list[QGroupBox]) -> QScrollArea:
        """설정 그룹 묶음을 스크롤 가능한 한 페이지로 만든다."""
        scroll_area = QScrollArea()
        scroll_area.setObjectName("SettingsScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("SettingsPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 4, 12, 12)
        page_layout.setSpacing(4)
        for group in groups:
            page_layout.addWidget(group)
        page_layout.addStretch()

        scroll_area.setWidget(page)
        return scroll_area

    def _build_general_page(self: SettingsDialog) -> QScrollArea:
        return self._build_settings_page([self._build_api_group(), self._build_general_group()])

    def _build_alerts_page(self: SettingsDialog) -> QScrollArea:
        return self._build_settings_page([self._build_notification_group(), self._build_tray_group()])

    def _build_data_page(self: SettingsDialog) -> QScrollArea:
        return self._build_settings_page(
            [
                self._build_cleanup_group(),
                self._build_transfer_group(),
                self._build_cloud_group(),
                self._build_tools_group(),
            ]
        )

    def _build_doc_browser(self: SettingsDialog, html_text: str, *, open_external: bool) -> QTextBrowser:
        browser = QTextBrowser()
        browser.setObjectName("DocBrowser")
        browser.setOpenExternalLinks(open_external)
        browser.setHtml(html_text)
        return browser

    def _build_help_tab(self: SettingsDialog) -> QTextBrowser:
        return self._build_doc_browser(self.get_help_html(), open_external=True)

    def _build_shortcuts_tab(self: SettingsDialog) -> QTextBrowser:
        return self._build_doc_browser(self.get_shortcuts_html(), open_external=False)

    def _hint_label(self: SettingsDialog, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Hint")
        label.setWordWrap(True)
        return label

    def _build_api_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("네이버 API 키")
        form = QGridLayout()

        self.txt_id = QLineEdit(self.config.get("client_id", ""))
        self.txt_id.setPlaceholderText("NAVER API HUB에서 발급받은 Client ID")

        self.txt_sec = QLineEdit(self.config.get("client_secret", ""))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_sec.setPlaceholderText("Client Secret (API HUB)")

        self.chk_show_pw = QCheckBox("Secret 표시")
        self.chk_show_pw.stateChanged.connect(
            lambda: self.txt_sec.setEchoMode(
                QLineEdit.EchoMode.Normal
                if self.chk_show_pw.isChecked()
                else QLineEdit.EchoMode.Password
            )
        )

        btn_get_key = QPushButton("API 키 발급받기")
        btn_get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://www.ncloud.com/product/applicationService/naverApiHub")
            )
        )

        self.btn_validate = QPushButton("키 확인")
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
        group = QGroupBox("일반")
        form = QGridLayout()

        self.cb_time = NoScrollComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "2시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get("interval", 2)
        self.cb_time.setCurrentIndex(idx if isinstance(idx, int) and 0 <= idx <= 5 else 2)

        self.cb_theme = NoScrollComboBox()
        self.cb_theme.addItems(["라이트", "다크", "시스템 설정 따름"])
        self.cb_theme.setCurrentIndex(self.config.get("theme", 0))

        self.cb_auto_backup = NoScrollComboBox()
        for label, minutes in [
            ("사용 안함", 0),
            ("30분", 30),
            ("1시간", 60),
            ("180분", 180),
            ("6시간", 360),
        ]:
            self.cb_auto_backup.addItem(label, minutes)
        configured_backup_minutes = int(self.config.get("auto_backup_minutes", 60) or 0)
        backup_values = [0, 30, 60, 180, 360]
        self.cb_auto_backup.setCurrentIndex(
            backup_values.index(configured_backup_minutes)
            if configured_backup_minutes in backup_values
            else 2
        )

        self.spn_api_timeout = QSpinBox()
        self.spn_api_timeout.setRange(5, 60)
        self.spn_api_timeout.setSuffix("초")
        timeout_value = self.config.get("api_timeout", 15)
        try:
            timeout_value = int(timeout_value)
        except (TypeError, ValueError):
            timeout_value = 15
        self.spn_api_timeout.setValue(max(5, min(60, timeout_value)))

        self.txt_blocked_publishers = QLineEdit(
            ", ".join(str(item) for item in self.config.get("blocked_publishers", []))
        )
        self.txt_blocked_publishers.setPlaceholderText("예: example.com, badnews.co.kr")

        self.txt_preferred_publishers = QLineEdit(
            ", ".join(str(item) for item in self.config.get("preferred_publishers", []))
        )
        self.txt_preferred_publishers.setPlaceholderText("예: yna.co.kr, news.naver.com")

        form.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form.addWidget(self.cb_time, 0, 1)
        form.addWidget(QLabel("테마:"), 1, 0)
        form.addWidget(self.cb_theme, 1, 1)
        form.addWidget(QLabel("설정 자동 백업:"), 2, 0)
        form.addWidget(self.cb_auto_backup, 2, 1)
        form.addWidget(QLabel("API 타임아웃:"), 3, 0)
        form.addWidget(self.spn_api_timeout, 3, 1)
        form.addWidget(QLabel("차단 출처:"), 4, 0)
        form.addWidget(self.txt_blocked_publishers, 4, 1)
        form.addWidget(QLabel("선호 출처:"), 5, 0)
        form.addWidget(self.txt_preferred_publishers, 5, 1)

        group.setLayout(form)
        return group

    def _build_tray_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("트레이와 시작")
        layout = QVBoxLayout()

        self.chk_minimize_to_tray = QCheckBox("최소화하면 트레이로 보내기")
        self.chk_minimize_to_tray.setChecked(self.config.get("minimize_to_tray", True))
        layout.addWidget(self.chk_minimize_to_tray)

        self.chk_close_to_tray = QCheckBox("닫기(X)를 눌러도 종료하지 않고 트레이로 보내기")
        self.chk_close_to_tray.setChecked(self.config.get("close_to_tray", True))
        layout.addWidget(self.chk_close_to_tray)

        self.chk_auto_start = QCheckBox("Windows 시작 시 자동 실행")
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

        self.chk_start_minimized = QCheckBox("시작할 때 트레이로 최소화")
        tray_supported = QSystemTrayIcon.isSystemTrayAvailable()
        configured = bool(self.config.get("start_minimized", False))
        self.chk_start_minimized.setChecked(configured and tray_supported)
        if not tray_supported:
            self.chk_start_minimized.setEnabled(False)
            self.chk_start_minimized.setToolTip(
                "시스템 트레이를 사용할 수 없는 환경에서는 적용되지 않습니다."
            )
        layout.addWidget(self.chk_start_minimized)

        self.lbl_auto_start_status = self._hint_label("")
        layout.addWidget(self.lbl_auto_start_status)

        self.btn_repair_auto_start = QPushButton("자동 시작 등록 수리")
        self.btn_repair_auto_start.clicked.connect(self.repair_startup_registration)
        layout.addWidget(self.btn_repair_auto_start)

        layout.addWidget(self._hint_label("트레이에 있는 동안에도 설정한 간격으로 뉴스를 계속 가져옵니다."))

        self.chk_auto_start.toggled.connect(lambda _checked: self.refresh_startup_status())
        self.chk_start_minimized.toggled.connect(lambda _checked: self.refresh_startup_status())
        self.refresh_startup_status()

        group.setLayout(layout)
        return group

    def _build_cleanup_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("기사 정리")
        layout = QVBoxLayout()

        buttons = QHBoxLayout()
        self.btn_clean = QPushButton(CLEAN_OLD_LABEL)
        self.btn_clean.setToolTip("북마크한 기사는 지우지 않습니다.")
        self.btn_clean.clicked.connect(self.clean_data)
        self.btn_all = QPushButton(CLEAN_ALL_LABEL)
        self.btn_all.setToolTip("북마크한 기사는 지우지 않습니다.")
        self.btn_all.clicked.connect(self.clean_all)
        self.btn_optimize_db = QPushButton("DB 최적화")
        self.btn_optimize_db.clicked.connect(self.optimize_database)
        buttons.addWidget(self.btn_clean)
        buttons.addWidget(self.btn_all)
        buttons.addWidget(self.btn_optimize_db)
        buttons.addStretch()
        layout.addLayout(buttons)

        retention_layout = QHBoxLayout()
        retention_layout.addWidget(QLabel("삭제 기록 보존:"))
        self.cb_tombstone_retention = NoScrollComboBox()
        for label, days in [
            ("영구 보존", 0),
            ("7일", 7),
            ("30일", 30),
            ("90일 (권장)", 90),
            ("180일", 180),
            ("365일", 365),
        ]:
            self.cb_tombstone_retention.addItem(label, days)
        configured_retention = int(self.config.get("tombstone_retention_days", 90) or 0)
        retention_values = [0, 7, 30, 90, 180, 365]
        self.cb_tombstone_retention.setCurrentIndex(
            retention_values.index(configured_retention)
            if configured_retention in retention_values
            else 3
        )
        self.cb_tombstone_retention.setToolTip(
            "목록에서 삭제한 기사는 다른 PC로 삭제를 전파하기 위해 '삭제 기록'으로 남습니다.\n"
            "이 기간이 지난 삭제 기록은 정리 작업에서 실제로 제거되어 저장공간이 회수됩니다.\n"
            "'영구 보존'을 고르면 삭제 기록은 회수되지 않습니다."
        )
        retention_layout.addWidget(self.cb_tombstone_retention)
        retention_layout.addStretch()
        layout.addLayout(retention_layout)
        layout.addWidget(
            self._hint_label("삭제한 기사가 다른 PC에서 되살아나지 않도록 남겨 두는 기록의 보존 기간입니다.")
        )

        group.setLayout(layout)
        return group

    def _build_transfer_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("가져오기 · 내보내기")
        layout = QHBoxLayout()
        btn_export_settings = QPushButton("설정 내보내기")
        btn_export_settings.clicked.connect(self.export_settings_dialog)
        btn_import_settings = QPushButton("설정 가져오기")
        btn_import_settings.clicked.connect(self.import_settings_dialog)
        btn_import_csv = QPushButton("CSV 메모/북마크 가져오기")
        btn_import_csv.clicked.connect(self.import_csv_dialog)
        layout.addWidget(btn_export_settings)
        layout.addWidget(btn_import_settings)
        layout.addWidget(btn_import_csv)
        layout.addStretch()
        group.setLayout(layout)
        return group

    def _build_tools_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("도구")
        layout = QHBoxLayout()
        btn_groups = QPushButton("키워드 그룹")
        btn_groups.clicked.connect(self.show_groups_dialog)
        btn_folder = QPushButton("데이터 폴더 열기")
        btn_folder.clicked.connect(self.open_data_folder)
        btn_log = QPushButton("로그 보기")
        btn_log.clicked.connect(self.show_log_dialog)
        layout.addWidget(btn_groups)
        layout.addWidget(btn_folder)
        layout.addWidget(btn_log)
        layout.addStretch()
        group.setLayout(layout)
        return group

    def _build_cloud_group(self: SettingsDialog) -> QGroupBox:
        cloud_group = QGroupBox("클라우드 동기화")
        cloud_layout = QVBoxLayout()
        self.chk_cloud_sync_enabled = QCheckBox("주기적으로 동기화")
        self.chk_cloud_sync_enabled.setChecked(bool(self.config.get("cloud_sync_enabled", True)))
        cloud_layout.addWidget(self.chk_cloud_sync_enabled)

        cloud_dir_layout = QHBoxLayout()
        self.txt_cloud_sync_dir = QLineEdit(str(self.config.get("cloud_sync_dir", "") or ""))
        self.txt_cloud_sync_dir.setPlaceholderText("OneDrive/Google Drive 스냅샷 폴더")
        btn_cloud_browse = QPushButton("폴더 선택")
        btn_cloud_browse.clicked.connect(self.choose_cloud_sync_folder)
        cloud_dir_layout.addWidget(self.txt_cloud_sync_dir)
        cloud_dir_layout.addWidget(btn_cloud_browse)
        cloud_layout.addLayout(cloud_dir_layout)

        cloud_actions = QHBoxLayout()
        cloud_actions.addWidget(QLabel("간격:"))
        self.cb_cloud_sync_interval = NoScrollComboBox()
        for minutes in (10, 30, 60, 120, 360):
            self.cb_cloud_sync_interval.addItem(f"{minutes}분", minutes)
        current_interval = int(self.config.get("cloud_sync_interval_minutes", 30) or 30)
        interval_index = self.cb_cloud_sync_interval.findData(current_interval)
        self.cb_cloud_sync_interval.setCurrentIndex(interval_index if interval_index >= 0 else 1)
        cloud_actions.addWidget(self.cb_cloud_sync_interval)
        cloud_actions.addStretch()
        btn_cloud_export = QPushButton("지금 내보내기")
        btn_cloud_export.clicked.connect(self.cloud_sync_export_dialog)
        btn_cloud_import = QPushButton("지금 병합")
        btn_cloud_import.clicked.connect(self.cloud_sync_import_dialog)
        btn_cloud_quarantine = QPushButton("격리 관리")
        btn_cloud_quarantine.clicked.connect(self.cloud_sync_quarantine_dialog)
        cloud_actions.addWidget(btn_cloud_export)
        cloud_actions.addWidget(btn_cloud_import)
        cloud_actions.addWidget(btn_cloud_quarantine)
        cloud_layout.addLayout(cloud_actions)

        self.lbl_cloud_sync_status = self._hint_label(str(self.config.get("cloud_sync_last_status", "") or ""))
        cloud_layout.addWidget(self.lbl_cloud_sync_status)
        cloud_group.setLayout(cloud_layout)
        return cloud_group

    def _build_notification_group(self: SettingsDialog) -> QGroupBox:
        group = QGroupBox("알림")
        layout = QVBoxLayout()

        self.chk_notification = QCheckBox("새 기사가 도착하면 데스크톱 알림 표시")
        self.chk_notification.setChecked(self.config.get("notification_enabled", True))
        layout.addWidget(self.chk_notification)

        self.chk_notify_on_refresh = QCheckBox("자동 새로고침이 끝나면 알림 표시")
        self.chk_notify_on_refresh.setChecked(self.config.get("notify_on_refresh", False))
        layout.addWidget(self.chk_notify_on_refresh)

        sound_layout = QHBoxLayout()
        self.chk_sound = QCheckBox("알림 소리")
        self.chk_sound.setChecked(self.config.get("sound_enabled", True))
        btn_test_sound = QPushButton("소리 테스트")
        btn_test_sound.clicked.connect(lambda: NotificationSound.play("success"))
        sound_layout.addWidget(self.chk_sound)
        sound_layout.addWidget(btn_test_sound)
        sound_layout.addStretch()
        layout.addLayout(sound_layout)

        layout.addWidget(QLabel("알림 키워드"))
        self.txt_alert_keywords = QLineEdit()
        current_keywords = self.config.get("alert_keywords", [])
        self.txt_alert_keywords.setText(", ".join(current_keywords) if current_keywords else "")
        self.txt_alert_keywords.setPlaceholderText("예: 긴급, 속보, 단독")
        layout.addWidget(self.txt_alert_keywords)
        layout.addWidget(
            self._hint_label("쉼표로 구분해 최대 10개. 제목이나 내용에 이 단어가 있으면 따로 알려 줍니다.")
        )

        group.setLayout(layout)
        return group
