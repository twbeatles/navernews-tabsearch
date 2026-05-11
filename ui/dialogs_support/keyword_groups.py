import html
import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QCloseEvent, QDesktopServices
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
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from core.backup import AutoBackup
from core.automation_rules import normalize_automation_rules
from core.keyword_groups import KeywordGroupManager
from core.logging_setup import configure_logging
from core.constants import LOG_FILE
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases
from core.workers import IterativeJobWorker, delete_qthread_when_finished, retain_worker_until_finished
from ui.dialog_adapters import get_dialog_adapter

configure_logging()
logger = logging.getLogger(__name__)

class KeywordGroupDialog(QDialog):
    """키워드 그룹 관리 다이얼로그"""

    def __init__(self, group_manager: KeywordGroupManager, current_tabs: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("📁 키워드 그룹 관리")
        self.resize(600, 500)
        self.group_manager = group_manager
        self.current_tabs = current_tabs
        self.edit_groups = self.group_manager._normalize_groups(dict(self.group_manager.groups))

        self.setup_ui()
        self.load_groups()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 설명
        info = QLabel("키워드를 그룹(폴더)으로 정리하여 관리할 수 있습니다. 변경 내용은 저장 시에만 반영됩니다.")
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _group_names(self) -> List[str]:
        return list(self.edit_groups.keys())

    def _selected_group_name(self) -> Optional[str]:
        current_row = self.group_list.currentRow()
        groups = self._group_names()
        if 0 <= current_row < len(groups):
            return groups[current_row]
        return None

    def accept(self):
        normalized_groups = self.group_manager._normalize_groups(self.edit_groups)
        if not self.group_manager.replace_groups(normalized_groups):
            error_detail = self.group_manager.last_error or "알 수 없는 오류"
            QMessageBox.warning(
                self,
                "저장 실패",
                f"키워드 그룹을 저장하지 못했습니다.\n\n{error_detail}",
            )
            return
        super().accept()

    def load_groups(self):
        """그룹 및 키워드 목록 로드"""
        selected_group = self._selected_group_name()
        self.group_list.clear()
        groups = self._group_names()
        for group in groups:
            count = len(self.edit_groups.get(group, []))
            self.group_list.addItem(f"📁 {group} ({count})")

        if groups:
            target_index = groups.index(selected_group) if selected_group in groups else 0
            self.group_list.setCurrentRow(target_index)

        self.update_keyword_lists()

    def update_keyword_lists(self):
        """키워드 목록 업데이트"""
        self.group_keywords_list.clear()
        self.unassigned_list.clear()

        # 현재 선택된 그룹의 키워드
        group_name = self._selected_group_name()
        if group_name:
            for kw in self.edit_groups.get(group_name, []):
                self.group_keywords_list.addItem(kw)

        # 미분류 키워드 (어떤 그룹에도 속하지 않은 탭)
        assigned = set()
        for keywords in self.edit_groups.values():
            assigned.update(keywords)

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
            group_name = name.strip()
            if group_name not in self.edit_groups:
                self.edit_groups[group_name] = []
                self.load_groups()
            else:
                QMessageBox.warning(self, "오류", "이미 존재하는 그룹 이름입니다.")

    def delete_group(self):
        """그룹 삭제"""
        group_name = self._selected_group_name()
        if not group_name:
            return

        reply = QMessageBox.question(
            self, "그룹 삭제",
            f"'{group_name}' 그룹을 삭제하시겠습니까?\n(그룹 내 키워드는 미분류로 이동됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.edit_groups.pop(group_name, None)
            self.load_groups()

    def add_keyword_to_group(self):
        """선택한 키워드를 그룹에 추가"""
        group_name = self._selected_group_name()
        keyword_item = self.unassigned_list.currentItem()

        if not group_name or not keyword_item:
            return

        keyword = keyword_item.text()
        keywords = self.edit_groups.setdefault(group_name, [])
        if keyword not in keywords:
            keywords.append(keyword)
        self.load_groups()

    def remove_keyword_from_group(self):
        """그룹에서 키워드 제거"""
        group_name = self._selected_group_name()
        keyword_item = self.group_keywords_list.currentItem()

        if not group_name or not keyword_item:
            return

        keyword = keyword_item.text()
        keywords = self.edit_groups.get(group_name, [])
        if keyword in keywords:
            keywords.remove(keyword)
        self.load_groups()
