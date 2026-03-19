import html
import logging
import os
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from core.backup import AutoBackup
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.constants import LOG_FILE

configure_logging()
logger = logging.getLogger(__name__)

class NoteDialog(QDialog):
    """메모 편집 다이얼로그"""
    
    def __init__(self, current_note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("메모 편집")
        self.resize(500, 300)
        
        layout = QVBoxLayout(self)
        
        label = QLabel("이 기사에 대한 메모를 작성하세요:")
        layout.addWidget(label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(current_note)
        self.text_edit.setPlaceholderText("메모를 입력하세요...")
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_note(self) -> str:
        """메모 내용 반환"""
        return self.text_edit.toPlainText().strip()


class LogViewerDialog(QDialog):
    """애플리케이션 로그 뷰어"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 로그 뷰어")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # 상단 버튼
        btn_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.clicked.connect(self.load_logs)
        
        self.btn_clear = QPushButton("🗑 로그 지우기")
        self.btn_clear.clicked.connect(self.clear_logs)
        
        self.btn_open_file = QPushButton("📁 로그 파일 열기")
        self.btn_open_file.clicked.connect(self.open_log_file)
        
        self.chk_auto_scroll = QCheckBox("자동 스크롤")
        self.chk_auto_scroll.setChecked(True)
        
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_open_file)
        btn_layout.addStretch()
        btn_layout.addWidget(self.chk_auto_scroll)
        layout.addLayout(btn_layout)
        
        # 필터
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("레벨 필터:"))
        
        self.combo_level = QComboBox()
        self.combo_level.addItems(["모두", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.combo_level.currentIndexChanged.connect(self.load_logs)
        filter_layout.addWidget(self.combo_level)
        
        filter_layout.addWidget(QLabel("검색:"))
        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("로그 내용 검색...")
        self.inp_search.textChanged.connect(self.load_logs)
        filter_layout.addWidget(self.inp_search, 1)
        
        layout.addLayout(filter_layout)
        
        # 로그 표시 영역
        self.log_browser = QTextBrowser()
        self.log_browser.setOpenExternalLinks(False)
        self.log_browser.setStyleSheet("""
            QTextBrowser {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
                background-color: #1E1E1E;
                color: #D4D4D4;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.log_browser)
        
        # 상태 레이블
        self.lbl_status = QLabel("대기 중...")
        layout.addWidget(self.lbl_status)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        
        # 로그 로드
        self.load_logs()
    
    def load_logs(self):
        """로그 파일 로드 - 최근 로그만 최적화하여 로드"""
        try:
            if not os.path.exists(LOG_FILE):
                self.log_browser.setPlainText("로그 파일이 없습니다.")
                self.lbl_status.setText("로그 파일 없음")
                return
            
            # 대용량 로그 파일 처리 최적화 - 마지막 50KB만 읽기
            file_size = os.path.getsize(LOG_FILE)
            read_size = 50 * 1024  # 50KB
            
            lines = []
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                if file_size > read_size:
                    f.seek(file_size - read_size)
                    # 첫 줄은 잘릴 수 있으므로 버림
                    f.readline()
                lines = f.readlines()
            
            # 필터 적용
            level_filter = self.combo_level.currentText()
            search_text = self.inp_search.text().strip().lower()
            
            filtered_lines = []
            for line in lines:
                # 레벨 필터
                if level_filter != "모두":
                    if f"[{level_filter}]" not in line:
                        continue
                
                # 검색 필터
                if search_text and search_text not in line.lower():
                    continue
                
                filtered_lines.append(line)
            
            # 색상 코딩된 HTML 생성
            html_lines = []
            for line in filtered_lines:
                if "[ERROR]" in line or "[CRITICAL]" in line:
                    color = "#FF6B6B"
                elif "[WARNING]" in line:
                    color = "#FFD93D"
                elif "[INFO]" in line:
                    color = "#6BCB77"
                else:
                    color = "#D4D4D4"
                
                escaped = html.escape(line.rstrip())
                html_lines.append(f"<span style='color: {color};'>{escaped}</span>")
            
            html_content = "<pre style='margin: 0;'>" + "<br>".join(html_lines) + "</pre>"
            if file_size > read_size:
                html_content = f"<div style='color: #888; margin-bottom: 10px;'>... 이전 로그 생략됨 (전체 크기: {file_size/1024:.1f}KB) ...</div>" + html_content
                
            self.log_browser.setHtml(html_content)
            
            # 자동 스크롤
            if self.chk_auto_scroll.isChecked():
                scroll_bar = self.log_browser.verticalScrollBar()
                if scroll_bar is not None:
                    scroll_bar.setValue(scroll_bar.maximum())
            
            self.lbl_status.setText(f"총 {len(lines)}줄 중 {len(filtered_lines)}줄 표시")
            
        except Exception as e:
            self.log_browser.setPlainText(f"로그 로드 오류: {str(e)}")
            self.lbl_status.setText(f"오류: {str(e)}")
    
    def clear_logs(self):
        """로그 파일 지우기"""
        reply = QMessageBox.question(
            self,
            "로그 지우기",
            "로그 파일을 지우시겠습니까?\n이 작업은 취소할 수 없습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                with open(LOG_FILE, 'w', encoding='utf-8') as f:
                    f.write("")
                self.load_logs()
                logger.info("로그 파일 초기화됨")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"로그 지우기 실패: {str(e)}")
    
    def open_log_file(self):
        """로그 파일을 기본 편집기로 열기"""
        if os.path.exists(LOG_FILE):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(LOG_FILE)))
        else:
            QMessageBox.information(self, "알림", "로그 파일이 아직 생성되지 않았습니다.")


class KeywordGroupDialog(QDialog):
    """키워드 그룹 관리 다이얼로그"""
    
    def __init__(self, group_manager: KeywordGroupManager, current_tabs: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("📁 키워드 그룹 관리")
        self.resize(600, 500)
        self.group_manager = group_manager
        self.current_tabs = current_tabs
        
        self.setup_ui()
        self.load_groups()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 설명
        info = QLabel("키워드를 그룹(폴더)으로 정리하여 관리할 수 있습니다.")
        info.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(info)
        
        # 그룹 관리 영역
        main_layout = QHBoxLayout()
        
        # 왼쪽: 그룹 목록
        left_group = QGroupBox("📁 그룹")
        left_layout = QVBoxLayout(left_group)
        
        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self.on_group_selected)
        left_layout.addWidget(self.group_list)
        
        group_btn_layout = QHBoxLayout()
        self.btn_add_group = QPushButton("➕ 추가")
        self.btn_add_group.clicked.connect(self.add_group)
        self.btn_del_group = QPushButton("🗑 삭제")
        self.btn_del_group.clicked.connect(self.delete_group)
        group_btn_layout.addWidget(self.btn_add_group)
        group_btn_layout.addWidget(self.btn_del_group)
        left_layout.addLayout(group_btn_layout)
        
        main_layout.addWidget(left_group, 1)
        
        # 중앙: 버튼
        center_layout = QVBoxLayout()
        center_layout.addStretch()
        self.btn_add_to_group = QPushButton("→")
        self.btn_add_to_group.setFixedWidth(40)
        self.btn_add_to_group.clicked.connect(self.add_keyword_to_group)
        self.btn_remove_from_group = QPushButton("←")
        self.btn_remove_from_group.setFixedWidth(40)
        self.btn_remove_from_group.clicked.connect(self.remove_keyword_from_group)
        center_layout.addWidget(self.btn_add_to_group)
        center_layout.addWidget(self.btn_remove_from_group)
        center_layout.addStretch()
        main_layout.addLayout(center_layout)
        
        # 오른쪽: 키워드 목록
        right_group = QGroupBox("🔑 키워드")
        right_layout = QVBoxLayout(right_group)
        
        # 그룹의 키워드
        right_layout.addWidget(QLabel("그룹 내 키워드:"))
        self.group_keywords_list = QListWidget()
        right_layout.addWidget(self.group_keywords_list)
        
        # 미분류 키워드
        right_layout.addWidget(QLabel("미분류 키워드:"))
        self.unassigned_list = QListWidget()
        right_layout.addWidget(self.unassigned_list)
        
        main_layout.addWidget(right_group, 1)
        
        layout.addLayout(main_layout)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
    
    def load_groups(self):
        """그룹 및 키워드 목록 로드"""
        self.group_list.clear()
        for group in self.group_manager.get_all_groups():
            count = len(self.group_manager.get_group_keywords(group))
            self.group_list.addItem(f"📁 {group} ({count})")
        
        self.update_keyword_lists()
    
    def update_keyword_lists(self):
        """키워드 목록 업데이트"""
        self.group_keywords_list.clear()
        self.unassigned_list.clear()
        
        # 현재 선택된 그룹의 키워드
        current_row = self.group_list.currentRow()
        if current_row >= 0:
            groups = self.group_manager.get_all_groups()
            if current_row < len(groups):
                group_name = groups[current_row]
                for kw in self.group_manager.get_group_keywords(group_name):
                    self.group_keywords_list.addItem(kw)
        
        # 미분류 키워드 (어떤 그룹에도 속하지 않은 탭)
        assigned = set()
        for group in self.group_manager.get_all_groups():
            assigned.update(self.group_manager.get_group_keywords(group))
        
        for tab in self.current_tabs:
            if tab not in assigned and tab != "북마크":
                self.unassigned_list.addItem(tab)
    
    def on_group_selected(self, row: int):
        """그룹 선택 시"""
        self.update_keyword_lists()
    
    def add_group(self):
        """새 그룹 추가"""
        name, ok = QInputDialog.getText(self, "새 그룹", "그룹 이름:")
        if ok and name.strip():
            if self.group_manager.create_group(name.strip()):
                self.load_groups()
            else:
                QMessageBox.warning(self, "오류", "이미 존재하는 그룹 이름입니다.")
    
    def delete_group(self):
        """그룹 삭제"""
        current_row = self.group_list.currentRow()
        if current_row < 0:
            return
        
        groups = self.group_manager.get_all_groups()
        if current_row < len(groups):
            group_name = groups[current_row]
            reply = QMessageBox.question(
                self, "그룹 삭제",
                f"'{group_name}' 그룹을 삭제하시겠습니까?\n(그룹 내 키워드는 미분류로 이동됩니다)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.group_manager.delete_group(group_name)
                self.load_groups()
    
    def add_keyword_to_group(self):
        """선택한 키워드를 그룹에 추가"""
        group_row = self.group_list.currentRow()
        keyword_item = self.unassigned_list.currentItem()
        
        if group_row < 0 or not keyword_item:
            return
        
        groups = self.group_manager.get_all_groups()
        if group_row < len(groups):
            group_name = groups[group_row]
            keyword = keyword_item.text()
            self.group_manager.add_keyword_to_group(group_name, keyword)
            self.load_groups()
    
    def remove_keyword_from_group(self):
        """그룹에서 키워드 제거"""
        group_row = self.group_list.currentRow()
        keyword_item = self.group_keywords_list.currentItem()
        
        if group_row < 0 or not keyword_item:
            return
        
        groups = self.group_manager.get_all_groups()
        if group_row < len(groups):
            group_name = groups[group_row]
            keyword = keyword_item.text()
            self.group_manager.remove_keyword_from_group(group_name, keyword)
            self.load_groups()


class BackupDialog(QDialog):
    """백업 관리 UI"""
    
    def __init__(self, auto_backup: AutoBackup, parent=None):
        super().__init__(parent)
        self.setWindowTitle("💾 백업 관리")
        self.resize(500, 400)
        self.auto_backup = auto_backup
        self.setup_ui()
        self.load_backups()

    @staticmethod
    def format_backup_timestamp(timestamp: str, created_at: Optional[str] = None) -> str:
        raw_timestamp = str(timestamp or "").strip()
        for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
            try:
                dt = datetime.strptime(raw_timestamp, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

        raw_created_at = str(created_at or "").strip()
        if raw_created_at:
            try:
                dt = datetime.fromisoformat(raw_created_at)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        return raw_timestamp or "Unknown"
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 백업 생성 버튼
        btn_layout = QHBoxLayout()
        
        self.btn_create = QPushButton("📦 새 백업 생성")
        self.btn_create.clicked.connect(self.create_backup)
        
        self.chk_include_db = QCheckBox("데이터베이스 포함")
        self.chk_include_db.setChecked(True)
        
        btn_layout.addWidget(self.btn_create)
        btn_layout.addWidget(self.chk_include_db)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        info_label = QLabel(
            "참고: 시작 시 자동 백업은 설정만 저장합니다. DB 복원 지점이 필요하면 수동 백업에서 "
            "'데이터베이스 포함'을 선택하세요."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; margin-bottom: 8px;")
        layout.addWidget(info_label)
        
        # 백업 목록
        layout.addWidget(QLabel("📁 백업 목록:"))
        self.backup_list = QListWidget()
        self.backup_list.itemDoubleClicked.connect(self.restore_backup)
        layout.addWidget(self.backup_list)
        
        # 하단 버튼
        bottom_layout = QHBoxLayout()
        
        self.btn_restore = QPushButton("♻ 복원")
        self.btn_restore.clicked.connect(self.restore_backup)
        
        self.btn_delete = QPushButton("🗑 삭제")
        self.btn_delete.clicked.connect(self.delete_backup)
        
        self.btn_open_folder = QPushButton("📂 폴더 열기")
        self.btn_open_folder.clicked.connect(self.open_backup_folder)
        
        bottom_layout.addWidget(self.btn_restore)
        bottom_layout.addWidget(self.btn_delete)
        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
    def load_backups(self):
        """백업 목록 로드"""
        self.backup_list.clear()
        backups = self.auto_backup.get_backup_list()

        for backup in backups:
            timestamp = backup.get("timestamp", "Unknown")
            version = backup.get("app_version", "?")
            include_db = "DB 포함" if backup.get("include_db") else "설정만"
            trigger_label = "자동" if str(backup.get("trigger", "manual")).lower() == "auto" else "수동"
            date_str = self.format_backup_timestamp(
                str(timestamp),
                created_at=str(backup.get("created_at", "")),
            )

            is_corrupt = bool(backup.get("is_corrupt", False))
            is_restorable = bool(backup.get("is_restorable", not is_corrupt))
            restore_error = str(backup.get("restore_error", "") or "")
            if is_corrupt:
                item_text = f"[손상됨] {date_str} (v{version})"
            elif not is_restorable:
                item_text = f"[복원 불가] {date_str} (v{version}) {include_db} {trigger_label}"
                if restore_error:
                    item_text += f" - {restore_error}"
            else:
                item_text = f"{date_str} (v{version}) {include_db} {trigger_label} [복원 가능]"
            self.backup_list.addItem(item_text)
            item = self.backup_list.item(self.backup_list.count() - 1)
            if item is not None:
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    {
                        "backup_name": backup.get("name", ""),
                        "include_db": bool(backup.get("include_db", False)),
                        "trigger": str(backup.get("trigger", "manual")).lower(),
                        "is_corrupt": is_corrupt,
                        "error": str(backup.get("error", "") or ""),
                        "is_restorable": is_restorable,
                        "restore_error": restore_error,
                    },
                )

    def create_backup(self):
        """백업 생성"""
        include_db = self.chk_include_db.isChecked()
        if include_db and not os.path.exists(getattr(self.auto_backup, "db_file", "")):
            QMessageBox.warning(
                self,
                "백업 생성 실패",
                "데이터베이스 파일이 없어 '데이터베이스 포함' 백업을 만들 수 없습니다.",
            )
            return
        result = self.auto_backup.create_backup(include_db)
        
        if result:
            QMessageBox.information(self, "완료", f"백업이 생성되었습니다:\n{result}")
            self.load_backups()
        else:
            QMessageBox.warning(self, "오류", "백업 생성에 실패했습니다.")
    def restore_backup(self):
        """백업 복원 예약 (재시작 시 적용)"""
        current_item = self.backup_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "알림", "복원할 백업을 선택하세요.")
            return

        item_meta = current_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_meta, dict):
            backup_name = str(item_meta.get("backup_name", "")).strip()
            include_db_meta = item_meta.get("include_db")
            is_corrupt = bool(item_meta.get("is_corrupt", False))
            corrupt_error = str(item_meta.get("error", "") or "")
            is_restorable = bool(item_meta.get("is_restorable", True))
            restore_error = str(item_meta.get("restore_error", "") or "")
        else:
            backup_name = str(item_meta or "").strip()
            include_db_meta = None
            is_corrupt = False
            corrupt_error = ""
            is_restorable = True
            restore_error = ""

        if not backup_name:
            QMessageBox.warning(self, "오류", "선택한 백업 정보를 읽을 수 없습니다.")
            return

        if is_corrupt:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("손상된 백업")
            dialog.setIcon(QMessageBox.Icon.Warning)
            detail = f"\n\n오류 정보: {corrupt_error}" if corrupt_error else ""
            dialog.setText(f"'{backup_name}' 항목은 손상되어 복원할 수 없습니다.{detail}")
            btn_delete = dialog.addButton("삭제", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton("무시", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()

            if dialog.clickedButton() == btn_delete:
                backup_path = os.path.join(self.auto_backup.backup_dir, backup_name)
                try:
                    import shutil
                    shutil.rmtree(backup_path, ignore_errors=True)
                    self.load_backups()
                    QMessageBox.information(self, "완료", "손상된 백업 항목을 삭제했습니다.")
                except Exception as e:
                    QMessageBox.warning(self, "오류", f"삭제 실패: {str(e)}")
            return

        if not is_restorable:
            QMessageBox.warning(
                self,
                "복원 불가",
                restore_error or "선택한 백업은 필요한 파일이 없어 복원할 수 없습니다.",
            )
            return

        if isinstance(include_db_meta, bool):
            restore_db = include_db_meta
        else:
            db_name = os.path.basename(getattr(self.auto_backup, "db_file", "news_database.db"))
            db_backup_path = os.path.join(self.auto_backup.backup_dir, backup_name, db_name)
            restore_db = os.path.exists(db_backup_path)

        restore_scope = "설정 + 데이터베이스" if restore_db else "설정만"
        restore_notice = (
            "주의: 현재 설정과 데이터가 덮어써집니다."
            if restore_db
            else "주의: 현재 설정만 덮어써집니다. 데이터베이스는 변경되지 않습니다."
        )

        reply = QMessageBox.question(
            self,
            "백업 복원",
            f"'{backup_name}' 백업을 복원하시겠습니까?\n\n"
            f"복원 범위: {restore_scope}\n"
            f"{restore_notice}\n"
            "복원은 프로그램을 재시작해야 적용됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.auto_backup.schedule_restore(backup_name, restore_db=restore_db):
                QMessageBox.information(
                    self,
                    "완료",
                    "복원을 예약했습니다.\n프로그램을 재시작하면 백업이 적용됩니다.",
                )
            else:
                QMessageBox.warning(self, "오류", "백업 복원 예약에 실패했습니다.")

    def delete_backup(self):
        """백업 삭제"""
        current_item = self.backup_list.currentItem()
        if not current_item:
            return

        item_meta = current_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(item_meta, dict):
            backup_name = str(item_meta.get("backup_name", "")).strip()
        else:
            backup_name = str(item_meta or "").strip()

        if not backup_name:
            QMessageBox.warning(self, "오류", "선택한 백업 정보를 읽을 수 없습니다.")
            return

        reply = QMessageBox.question(
            self,
            "백업 삭제",
            f"'{backup_name}' 백업을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            backup_path = os.path.join(self.auto_backup.backup_dir, backup_name)
            try:
                import shutil
                shutil.rmtree(backup_path, ignore_errors=True)
                self.load_backups()
            except Exception as e:
                QMessageBox.warning(self, "오류", f"삭제 실패: {str(e)}")

    def open_backup_folder(self):
        """백업 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.auto_backup.backup_dir))
