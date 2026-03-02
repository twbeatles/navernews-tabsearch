import json
import os
from typing import Any, Callable, Dict, Optional

import requests
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.constants import CONFIG_FILE, DB_FILE
from core.database import DatabaseManager
from core.notifications import NotificationSound
from core.startup import StartupManager
from core.validation import ValidationUtils
from core.workers import AsyncJobWorker
from ui.widgets import NoScrollComboBox

class SettingsDialog(QDialog):
    """설정 다이얼로그 (검증 기능 + 도움말 추가)"""
    
    def __init__(self, config: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 및 도움말")
        self.resize(600, 550)
        self.config = config
        self._api_validate_worker: Optional[AsyncJobWorker] = None
        self._data_task_worker: Optional[AsyncJobWorker] = None
        self._is_closing = False
        # 테마 설정 (부모에서 가져오기)
        self.is_dark = False
        if parent and hasattr(parent, 'theme_idx'):
            self.is_dark = parent.theme_idx == 1
        self.setup_ui()

    def setup_ui(self):
        """테마 적용 UI 설정"""
        layout = QVBoxLayout(self)
        
        # 테마별 색상
        if self.is_dark:
            bg_color = "#1A1A1D"
            text_color = "#FFFFFF"
        else:
            bg_color = "#FFFFFF"
            text_color = "#000000"
        # 탭 위젯 생성
        tab_widget = QTabWidget()
        
        # === 설정 탭 (스크롤 가능) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"QScrollArea {{ background-color: {bg_color}; border: none; }}")
        
        settings_widget = QWidget()
        settings_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        settings_layout = QVBoxLayout(settings_widget)
        
        gp_api = QGroupBox("📡 네이버 API 설정")
        form = QGridLayout()
        
        self.txt_id = QLineEdit(self.config.get('client_id', ''))
        self.txt_id.setPlaceholderText("네이버 개발자센터에서 발급받은 Client ID")
        
        self.txt_sec = QLineEdit(self.config.get('client_secret', ''))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_sec.setPlaceholderText("Client Secret")
        
        self.chk_show_pw = QCheckBox("비밀번호 표시")
        self.chk_show_pw.stateChanged.connect(
            lambda: self.txt_sec.setEchoMode(
                QLineEdit.EchoMode.Normal if self.chk_show_pw.isChecked() 
                else QLineEdit.EchoMode.Password
            )
        )
        
        btn_get_key = QPushButton("🔑 API 키 발급받기")
        btn_get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://developers.naver.com/apps/#/register"))
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
        
        gp_api.setLayout(form)
        settings_layout.addWidget(gp_api)
        
        gp_app = QGroupBox("⚙ 일반 설정")
        form2 = QGridLayout()
        
        self.cb_time = NoScrollComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "2시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get('interval', 2)
        if isinstance(idx, int) and 0 <= idx <= 5:
            self.cb_time.setCurrentIndex(idx)
        else:
            self.cb_time.setCurrentIndex(2)
        
        self.cb_theme = NoScrollComboBox()
        self.cb_theme.addItems(["☀ 라이트 모드", "🌙 다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get('theme', 0))
        self.spn_api_timeout = QSpinBox()
        self.spn_api_timeout.setRange(5, 60)
        self.spn_api_timeout.setSuffix("초")
        timeout_value = self.config.get("api_timeout", 15)
        try:
            timeout_value = int(timeout_value)
        except (TypeError, ValueError):
            timeout_value = 15
        self.spn_api_timeout.setValue(max(5, min(60, timeout_value)))
        
        form2.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form2.addWidget(self.cb_time, 0, 1)
        form2.addWidget(QLabel("테마:"), 1, 0)
        form2.addWidget(self.cb_theme, 1, 1)
        form2.addWidget(QLabel("API 타임아웃:"), 2, 0)
        form2.addWidget(self.spn_api_timeout, 2, 1)
        
        gp_app.setLayout(form2)
        settings_layout.addWidget(gp_app)
        
        # 시스템 트레이 및 자동 시작 설정
        gp_tray = QGroupBox("🖥️ 시스템 트레이 및 시작 설정")
        tray_layout = QVBoxLayout()
        
        # 트레이로 최소화 옵션
        self.chk_minimize_to_tray = QCheckBox("최소화 버튼 클릭 시 트레이로 최소화")
        self.chk_minimize_to_tray.setChecked(self.config.get('minimize_to_tray', True))
        tray_layout.addWidget(self.chk_minimize_to_tray)

        # 닫기(X) 동작 옵션
        self.chk_close_to_tray = QCheckBox("X 버튼 클릭 시 트레이로 최소화 (종료하지 않음)")
        self.chk_close_to_tray.setChecked(self.config.get('close_to_tray', True))
        tray_layout.addWidget(self.chk_close_to_tray)
        
        # 자동 시작 옵션 (Windows만)
        self.chk_auto_start = QCheckBox("윈도우 시작 시 자동 실행")
        if StartupManager.is_available():
            self.chk_auto_start.setChecked(StartupManager.is_startup_enabled())
        else:
            self.chk_auto_start.setEnabled(False)
            self.chk_auto_start.setToolTip("Windows에서만 사용 가능합니다.")
        tray_layout.addWidget(self.chk_auto_start)
        
        # 최소화 상태로 시작 옵션
        self.chk_start_minimized = QCheckBox("시작 시 최소화 상태로 시작 (트레이로)")
        tray_supported = QSystemTrayIcon.isSystemTrayAvailable()
        configured_start_minimized = bool(self.config.get('start_minimized', False))
        self.chk_start_minimized.setChecked(configured_start_minimized and tray_supported)
        if not tray_supported:
            self.chk_start_minimized.setEnabled(False)
            self.chk_start_minimized.setToolTip("시스템 트레이를 사용할 수 없는 환경에서는 적용되지 않습니다.")
        tray_layout.addWidget(self.chk_start_minimized)
        
        # 자동 새로고침 완료 알림 옵션
        self.chk_notify_on_refresh = QCheckBox("자동 새로고침 완료 시 알림 표시")
        self.chk_notify_on_refresh.setChecked(self.config.get('notify_on_refresh', False))
        tray_layout.addWidget(self.chk_notify_on_refresh)
        
        # 안내 메시지
        tray_info = QLabel(
            "💡 트레이로 최소화하면 백그라운드에서 뉴스를 계속 수집합니다.\n"
            "트레이 미지원 환경에서는 시작 최소화가 적용되지 않습니다."
        )
        tray_info.setStyleSheet("color: #666; font-size: 9pt;")
        tray_layout.addWidget(tray_info)
        
        gp_tray.setLayout(tray_layout)
        settings_layout.addWidget(gp_tray)
        
        gp_data = QGroupBox("🗂 데이터 관리")
        vbox = QVBoxLayout()
        
        self.btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        self.btn_clean.clicked.connect(self.clean_data)
        
        self.btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        self.btn_all.clicked.connect(self.clean_all)
        
        # JSON 설정 백업/복원 버튼
        backup_layout = QHBoxLayout()
        btn_export_settings = QPushButton("📤 설정 내보내기")
        btn_export_settings.clicked.connect(self.export_settings_dialog)
        btn_import_settings = QPushButton("📥 설정 가져오기")
        btn_import_settings.clicked.connect(self.import_settings_dialog)
        backup_layout.addWidget(btn_export_settings)
        backup_layout.addWidget(btn_import_settings)
        
        # 고급 도구 버튼 (툴바에서 이동)
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
        
        vbox.addWidget(self.btn_clean)
        vbox.addWidget(self.btn_all)
        vbox.addLayout(backup_layout)
        vbox.addLayout(tools_layout)
        gp_data.setLayout(vbox)
        settings_layout.addWidget(gp_data)
        
        # 알림 설정 그룹
        gp_notification = QGroupBox("🔔 알림 설정")
        notif_layout = QVBoxLayout()
        
        self.chk_notification = QCheckBox("데스크톱 알림 활성화 (새 뉴스 도착 시)")
        self.chk_notification.setChecked(self.config.get('notification_enabled', True))
        notif_layout.addWidget(self.chk_notification)
        
        keywords_label = QLabel("알림 키워드 (쉼표로 구분, 최대 10개):")
        notif_layout.addWidget(keywords_label)
        
        self.txt_alert_keywords = QLineEdit()
        current_keywords = self.config.get('alert_keywords', [])
        self.txt_alert_keywords.setText(", ".join(current_keywords) if current_keywords else "")
        self.txt_alert_keywords.setPlaceholderText("예: 긴급, 속보, 단독")
        notif_layout.addWidget(self.txt_alert_keywords)
        
        keywords_info = QLabel("💡 위 키워드가 기사 제목이나 내용에 포함되면 알림이 표시됩니다.")
        keywords_info.setStyleSheet("color: #666; font-size: 9pt;")
        notif_layout.addWidget(keywords_info)
        
        # 알림 소리 설정
        self.chk_sound = QCheckBox("알림 소리 활성화")
        self.chk_sound.setChecked(self.config.get('sound_enabled', True))
        notif_layout.addWidget(self.chk_sound)
        
        # 소리 테스트 버튼
        btn_test_sound = QPushButton("🔊 소리 테스트")
        btn_test_sound.clicked.connect(lambda: NotificationSound.play('success'))
        notif_layout.addWidget(btn_test_sound)
        
        gp_notification.setLayout(notif_layout)
        settings_layout.addWidget(gp_notification)
        
        settings_layout.addStretch()
        
        # === 도움말 탭 ===
        help_widget = QWidget()
        help_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        help_layout = QVBoxLayout(help_widget)
        
        help_browser = QTextBrowser()
        help_browser.setOpenExternalLinks(True)
        help_browser.setStyleSheet(f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}")
        help_browser.setHtml(self.get_help_html())
        help_layout.addWidget(help_browser)
        
        # === 단축키 탭 ===
        shortcuts_widget = QWidget()
        shortcuts_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        
        shortcuts_browser = QTextBrowser()
        shortcuts_browser.setOpenExternalLinks(False)
        shortcuts_browser.setStyleSheet(f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}")
        shortcuts_browser.setHtml(self.get_shortcuts_html())
        shortcuts_layout.addWidget(shortcuts_browser)
        
        # 스크롤 영역에 설정 위젯 추가
        scroll_area.setWidget(settings_widget)
        
        # 탭에 추가
        tab_widget.addTab(scroll_area, "⚙ 설정")
        tab_widget.addTab(help_widget, "📖 도움말")
        tab_widget.addTab(shortcuts_widget, "⌨ 단축키")
        
        layout.addWidget(tab_widget)
        
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept_with_validation)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
    
    def get_help_html(self) -> str:
        """도움말 HTML 생성"""
        return """
        <html>
        <head>
            <style>
                body { font-family: '맑은 고딕', sans-serif; padding: 15px; line-height: 1.6; }
                h2 { color: #007AFF; border-bottom: 2px solid #007AFF; padding-bottom: 5px; }
                h3 { color: #333; margin-top: 20px; }
                .section { margin-bottom: 25px; }
                .tip { background-color: #FFF3CD; padding: 10px; border-left: 4px solid #FFC107; margin: 10px 0; }
                .warning { background-color: #F8D7DA; padding: 10px; border-left: 4px solid #DC3545; margin: 10px 0; }
                .info { background-color: #D1ECF1; padding: 10px; border-left: 4px solid #17A2B8; margin: 10px 0; }
                code { background-color: #F5F5F5; padding: 2px 6px; border-radius: 3px; font-family: monospace; }
                ul { margin-left: 20px; }
                li { margin: 5px 0; }
                a { color: #007AFF; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <h2>🎯 빠른 시작 가이드</h2>
            
            <div class="section">
                <h3>1️⃣ API 키 설정</h3>
                <ul>
                    <li><a href="https://developers.naver.com/apps/#/register">네이버 개발자센터</a>에서 애플리케이션 등록</li>
                    <li>검색 API 선택 (뉴스 검색)</li>
                    <li>Client ID와 Client Secret을 설정 탭에 입력</li>
                    <li>"✓ API 키 검증" 버튼으로 정상 작동 확인</li>
                </ul>
                <div class="tip">
                    <strong>💡 팁:</strong> API 키는 안전하게 로컬 파일에만 저장됩니다.
                </div>
            </div>
            
            <div class="section">
                <h3>2️⃣ 탭 추가 및 검색</h3>
                <ul>
                    <li><strong>기본 검색:</strong> <code>주식</code></li>
                    <li><strong>제외 키워드:</strong> <code>주식 -코인</code> (코인 제외)</li>
                    <li><strong>복합 검색:</strong> <code>인공지능 AI -광고 -채용</code></li>
                </ul>
                <div class="info">
                    <strong>ℹ️ 정보:</strong> API 검색은 양(+) 키워드를 모두 사용합니다.
                    DB 그룹핑은 첫 번째 양(+) 키워드 기준으로 관리됩니다.
                </div>
            </div>
            
            <div class="section">
                <h3>3️⃣ 기사 관리</h3>
                <ul>
                    <li><strong>읽음 표시:</strong> 제목 클릭 시 자동으로 읽음 처리</li>
                    <li><strong>북마크:</strong> ⭐ 버튼으로 중요 기사 저장</li>
                    <li><strong>메모:</strong> 📝 버튼으로 기사별 메모 작성</li>
                    <li><strong>공유:</strong> 📋 버튼으로 제목+링크 클립보드 복사</li>
                    <li><strong>미리보기:</strong> 제목에 마우스 올리면 내용 미리보기</li>
                </ul>
            </div>
            
            <div class="section">
                <h3>4️⃣ 필터링 및 정렬</h3>
                <ul>
                    <li><strong>실시간 필터:</strong> 검색창에 입력하면 즉시 반영</li>
                    <li><strong>안 읽은 것만:</strong> 읽지 않은 기사만 표시</li>
                    <li><strong>중복 숨김:</strong> 유사한 기사 자동 숨김</li>
                    <li><strong>정렬:</strong> 최신순 / 오래된순 선택</li>
                </ul>
                <div class="tip">
                    <strong>💡 팁:</strong> Ctrl+F를 누르면 필터 검색창에 즉시 포커스됩니다.
                </div>
            </div>
            
            <div class="section">
                <h3>5️⃣ 데이터 관리</h3>
                <ul>
                    <li><strong>내보내기:</strong> Ctrl+S로 현재 탭의 기사를 CSV로 저장</li>
                    <li><strong>통계:</strong> 📊 버튼으로 전체 통계 확인</li>
                    <li><strong>분석:</strong> 📈 버튼으로 언론사별 기사 수 분석</li>
                    <li><strong>오래된 데이터 정리:</strong> 30일 이전 기사 삭제 (북마크 제외)</li>
                </ul>
                <div class="warning">
                    <strong>⚠️ 주의:</strong> 북마크하지 않은 기사는 데이터 정리 시 삭제될 수 있습니다.
                </div>
            </div>
            
            <div class="section">
                <h3>6️⃣ 자동 새로고침</h3>
                <ul>
                    <li>설정에서 간격 선택: 10분 / 30분 / 1시간 / 2시간 / 6시간</li>
                    <li>백그라운드에서 자동으로 새 기사 수집</li>
                    <li>새 기사 발견 시 토스트 알림 표시</li>
                </ul>
            </div>
            
            <div class="section">
                <h3>7️⃣ 문제 해결</h3>
                <ul>
                    <li><strong>검색 결과가 없을 때:</strong> 키워드 철자 확인, 제외 키워드 줄이기</li>
                    <li><strong>API 오류:</strong> 설정에서 "✓ API 키 검증" 실행</li>
                    <li><strong>앱이 느릴 때:</strong> 오래된 데이터 정리 실행</li>
                    <li><strong>중복 기사가 많을 때:</strong> "중복 숨김" 체크박스 활성화</li>
                </ul>
            </div>
            
            <div class="info" style="margin-top: 30px;">
                <strong>📚 더 많은 정보:</strong> 단축키는 "⌨ 단축키" 탭을 참고하세요.
            </div>
        </body>
        </html>
        """
    
    def get_shortcuts_html(self) -> str:
        """단축키 안내 HTML 생성"""
        return """
        <html>
        <head>
            <style>
                body { font-family: '맑은 고딕', sans-serif; padding: 15px; line-height: 1.6; }
                h2 { color: #007AFF; border-bottom: 2px solid #007AFF; padding-bottom: 5px; }
                h3 { color: #333; margin-top: 20px; background-color: #F5F5F5; padding: 8px; border-radius: 5px; }
                .shortcut-table { width: 100%; border-collapse: collapse; margin: 15px 0; }
                .shortcut-table th { background-color: #007AFF; color: white; padding: 10px; text-align: left; }
                .shortcut-table td { padding: 10px; border-bottom: 1px solid #E0E0E0; }
                .shortcut-table tr:hover { background-color: #F8F9FA; }
                .key { background-color: #FFFFFF; border: 2px solid #CCCCCC; border-radius: 5px; padding: 3px 8px; font-family: monospace; font-weight: bold; color: #333; display: inline-block; margin: 0 2px; box-shadow: 0 2px 3px rgba(0,0,0,0.1); }
                .description { color: #555; }
                .category { background-color: #E3F2FD; padding: 5px 10px; border-radius: 3px; font-weight: bold; color: #1976D2; margin-top: 15px; }
            </style>
        </head>
        <body>
            <h2>⌨️ 키보드 단축키 가이드</h2>
            
            <div class="category">🔄 새로고침 & 탭 관리</div>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><span class="key">Ctrl</span> + <span class="key">R</span> 또는 <span class="key">F5</span></td>
                    <td class="description">모든 탭 새로고침</td>
                </tr>
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">T</span></td>
                    <td class="description">새 탭 추가</td>
                </tr>
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">W</span></td>
                    <td class="description">현재 탭 닫기 (북마크 탭은 제외)</td>
                </tr>
                <tr>
                    <td><span class="key">Alt</span> + <span class="key">1</span>~<span class="key">9</span></td>
                    <td class="description">탭 빠른 전환 (1=북마크, 2=첫 번째 탭, ...)</td>
                </tr>
            </table>
            
            <div class="category">🔍 검색 & 필터링</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">F</span></td>
                    <td class="description">필터 검색창에 포커스 (전체 선택)</td>
                </tr>
            </table>
            
            <div class="category">💾 데이터 관리</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">S</span></td>
                    <td class="description">현재 탭 데이터 CSV로 내보내기</td>
                </tr>
            </table>
            
            <div class="category">⚙️ 설정 & 도움말</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">,</span></td>
                    <td class="description">설정 창 열기</td>
                </tr>
                <tr>
                    <td><span class="key">F1</span></td>
                    <td class="description">도움말 열기</td>
                </tr>
            </table>
            
            <h3>🖱️ 마우스 동작</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>제목 클릭</strong></td>
                    <td class="description">기사 열기 (자동으로 읽음 처리)</td>
                </tr>
                <tr>
                    <td><strong>제목 호버</strong></td>
                    <td class="description">기사 내용 미리보기 (툴팁)</td>
                </tr>
                <tr>
                    <td><strong>탭 더블클릭</strong></td>
                    <td class="description">탭 이름(키워드) 변경</td>
                </tr>
                <tr>
                    <td><strong>탭 X 버튼</strong></td>
                    <td class="description">탭 닫기</td>
                </tr>
            </table>
            
            <h3>📋 기사 카드 버튼</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>공유</strong></td>
                    <td class="description">제목과 링크를 클립보드에 복사</td>
                </tr>
                <tr>
                    <td><strong>외부</strong></td>
                    <td class="description">기본 브라우저에서 열기</td>
                </tr>
                <tr>
                    <td><strong>메모 📝</strong></td>
                    <td class="description">기사에 메모 작성/편집 (메모가 있으면 📝 표시)</td>
                </tr>
                <tr>
                    <td><strong>안읽음</strong></td>
                    <td class="description">읽음 → 안읽음으로 변경</td>
                </tr>
                <tr>
                    <td><strong>북마크 / 북마크 해제</strong></td>
                    <td class="description">중요 기사로 표시/해제 (⭐ 북마크 탭에서 모아보기)</td>
                </tr>
            </table>
            
            <h3>💡 유용한 팁</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>탭 드래그</strong></td>
                    <td class="description">탭 순서 변경 가능</td>
                </tr>
                <tr>
                    <td><strong>필터 검색</strong></td>
                    <td class="description">입력하는 즉시 실시간으로 필터링 적용</td>
                </tr>
                <tr>
                    <td><strong>중복 숨김</strong></td>
                    <td class="description">유사한 제목의 기사 자동 숨김</td>
                </tr>
                <tr>
                    <td><strong>안 읽은 것만</strong></td>
                    <td class="description">읽지 않은 기사만 표시</td>
                </tr>
            </table>
            
            <div style="margin-top: 30px; padding: 15px; background-color: #E8F5E9; border-radius: 8px; border-left: 4px solid #4CAF50;">
                <strong>🎯 프로 팁:</strong> 단축키를 조합하여 사용하면 훨씬 빠르게 작업할 수 있습니다!<br>
                예: <span class="key">Alt</span>+<span class="key">2</span> (탭 전환) → <span class="key">Ctrl</span>+<span class="key">F</span> (필터 포커스) → 검색어 입력
            </div>
        </body>
        </html>
        """

    def _detach_worker_signals(self, worker: Optional[AsyncJobWorker]):
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

    def _shutdown_worker(self, worker: Optional[AsyncJobWorker], wait_ms: int = 500):
        if not worker:
            return
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
            worker.wait(wait_ms)
        except Exception:
            pass

    def closeEvent(self, event):
        self._is_closing = True
        self._shutdown_worker(self._api_validate_worker, wait_ms=400)
        self._shutdown_worker(self._data_task_worker, wait_ms=800)
        self._api_validate_worker = None
        self._data_task_worker = None
        super().closeEvent(event)
    
    def validate_api_key(self):
        """API 키 검증"""
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

        def validate_job() -> Dict[str, Any]:
            headers = {
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            }
            url = "https://openapi.naver.com/v1/search/news.json"
            params = {"query": "테스트", "display": 1}

            resp = requests.get(url, headers=headers, params=params, timeout=10)
            payload: Dict[str, Any] = {"status_code": resp.status_code, "error_message": ""}
            if resp.status_code != 200:
                try:
                    error_data = resp.json()
                    payload["error_message"] = error_data.get("errorMessage", "알 수 없는 오류")
                except (ValueError, TypeError, KeyError):
                    payload["error_message"] = resp.text[:200] if resp.text else "응답 파싱 실패"
            return payload

        self._api_validate_worker = AsyncJobWorker(validate_job, parent=self)
        self._api_validate_worker.finished.connect(self._on_validate_api_key_done)
        self._api_validate_worker.error.connect(self._on_validate_api_key_error)
        self._api_validate_worker.finished.connect(self._on_validate_api_key_finished)
        self._api_validate_worker.error.connect(self._on_validate_api_key_finished)
        self._api_validate_worker.start()

    def _on_validate_api_key_done(self, result: Dict[str, Any]):
        if self._is_closing or not self.isVisible():
            return
        status_code = int(result.get("status_code", 0))
        if status_code == 200:
            QMessageBox.information(self, "검증 성공", "✓ API 키가 정상적으로 작동합니다!")
            return
        error_msg = str(result.get("error_message", "알 수 없는 오류"))
        QMessageBox.warning(
            self,
            "검증 실패",
            f"API 키가 올바르지 않습니다.\n\n오류: {error_msg}",
        )

    def _on_validate_api_key_error(self, error_msg: str):
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.critical(
            self,
            "검증 오류",
            f"API 키 검증 중 오류가 발생했습니다:\n\n{error_msg}",
        )

    def _on_validate_api_key_finished(self, *_args):
        if self._is_closing:
            self._api_validate_worker = None
            return
        self.btn_validate.setEnabled(True)
        self.btn_validate.setText("✓ API 키 검증")
        self._api_validate_worker = None
    
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
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        
        self.accept()

    def clean_data(self):
        """오래된 데이터 정리"""
        reply = QMessageBox.question(
            self,
            "데이터 정리",
            "30일 이전의 기사를 삭제하시겠습니까?\n\n(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        def job_func() -> int:
            db = DatabaseManager(DB_FILE)
            try:
                return int(db.delete_old_news(30))
            finally:
                db.close()

        self._start_data_task(job_func, self._on_clean_data_done)

    def clean_all(self):
        """모든 기사 삭제"""
        reply = QMessageBox.warning(
            self,
            "⚠ 경고",
            "정말 모든 기사를 삭제하시겠습니까?\n\n"
            "이 작업은 취소할 수 없습니다.\n"
            "(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        def job_func() -> int:
            db = DatabaseManager(DB_FILE)
            try:
                return int(db.delete_all_news())
            finally:
                db.close()

        self._start_data_task(job_func, self._on_clean_all_done)

    def _start_data_task(self, job_func: Callable[[], int], done_handler: Callable[[Any], None]):
        if self._is_closing:
            return
        if self._data_task_worker and self._data_task_worker.isRunning():
            QMessageBox.information(self, "진행 중", "이미 데이터 정리 작업이 진행 중입니다.")
            return

        self.btn_clean.setEnabled(False)
        self.btn_all.setEnabled(False)
        self.btn_clean.setText("⏳ 작업 중...")
        self.btn_all.setText("⏳ 작업 중...")

        self._data_task_worker = AsyncJobWorker(job_func, parent=self)
        self._data_task_worker.finished.connect(done_handler)
        self._data_task_worker.error.connect(self._on_data_task_error)
        self._data_task_worker.finished.connect(self._on_data_task_finished)
        self._data_task_worker.error.connect(self._on_data_task_finished)
        self._data_task_worker.start()

    def _on_clean_data_done(self, result: Any):
        if self._is_closing or not self.isVisible():
            return
        count = int(result)
        QMessageBox.information(self, "완료", f"✓ {count:,}개의 오래된 기사를 삭제했습니다.")

    def _on_clean_all_done(self, result: Any):
        if self._is_closing or not self.isVisible():
            return
        count = int(result)
        QMessageBox.information(self, "완료", f"✓ {count:,}개의 기사를 삭제했습니다.")

    def _on_data_task_error(self, error_msg: str):
        if self._is_closing or not self.isVisible():
            return
        QMessageBox.critical(self, "작업 오류", f"데이터 작업 중 오류가 발생했습니다:\n\n{error_msg}")

    def _on_data_task_finished(self, *_args):
        if self._is_closing:
            self._data_task_worker = None
            return
        self.btn_clean.setEnabled(True)
        self.btn_all.setEnabled(True)
        self.btn_clean.setText("🧹 오래된 데이터 정리 (30일 이전)")
        self.btn_all.setText("🗑 모든 기사 삭제 (북마크 제외)")
        self._data_task_worker = None
    
    def export_settings_dialog(self):
        """설정 내보내기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'export_settings'):
            self.parent().export_settings()
    
    def import_settings_dialog(self):
        """설정 가져오기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'import_settings'):
            self.parent().import_settings()
    
    def show_log_dialog(self):
        """로그 뷰어 표시 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_log_viewer'):
            self.parent().show_log_viewer()
    
    def open_data_folder(self):
        """데이터 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE))))
    
    def show_groups_dialog(self):
        """키워드 그룹 관리 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_keyword_groups'):
            self.parent().show_keyword_groups()

    def get_data(self) -> Dict:
        """설정 데이터 반환"""
        # 알림 키워드 파싱 (쉼표로 구분, 최대 10개)
        keywords_text = self.txt_alert_keywords.text().strip()
        alert_keywords = []
        if keywords_text:
            alert_keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()][:10]
        
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex(),
            'notification_enabled': self.chk_notification.isChecked(),
            'alert_keywords': alert_keywords,
            'sound_enabled': self.chk_sound.isChecked(),
            'minimize_to_tray': self.chk_minimize_to_tray.isChecked(),
            'close_to_tray': self.chk_close_to_tray.isChecked(),
            'auto_start_enabled': self.chk_auto_start.isChecked(),
            'start_minimized': self.chk_start_minimized.isChecked(),
            'notify_on_refresh': self.chk_notify_on_refresh.isChecked(),
            'api_timeout': int(self.spn_api_timeout.value()),
        }
