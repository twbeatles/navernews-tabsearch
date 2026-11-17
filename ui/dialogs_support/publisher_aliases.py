import json
import logging
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core.logging_setup import configure_logging
from core.publisher_aliases import normalize_publisher_aliases

configure_logging()
logger = logging.getLogger(__name__)


class PublisherAliasDialog(QDialog):
    def __init__(self, aliases, save_callback, parent=None):
        super().__init__(parent)
        self.save_callback = save_callback
        self.aliases: Dict[str, str] = normalize_publisher_aliases(aliases)
        self._editing_source = ""
        self.setWindowTitle("출처 Alias")
        self.resize(720, 520)
        layout = QVBoxLayout(self)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.alias_list = QListWidget()
        left.addWidget(self.alias_list)
        row_buttons = QHBoxLayout()
        btn_add_update = QPushButton("추가/수정")
        btn_delete = QPushButton("삭제")
        row_buttons.addWidget(btn_add_update)
        row_buttons.addWidget(btn_delete)
        left.addLayout(row_buttons)
        body.addLayout(left, 1)

        form_box = QGroupBox("Alias")
        form = QFormLayout(form_box)
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("예: naver:oid:001 또는 example.com")
        self.txt_alias = QLineEdit()
        self.txt_alias.setPlaceholderText("예: 연합뉴스")
        form.addRow("source", self.txt_source)
        form.addRow("alias", self.txt_alias)
        body.addWidget(form_box, 2)
        layout.addLayout(body)

        advanced = QGroupBox("고급 JSON")
        advanced_layout = QVBoxLayout(advanced)
        self.editor = QTextEdit()
        self.editor.setMinimumHeight(120)
        advanced_layout.addWidget(self.editor)
        btn_load_json = QPushButton("JSON에서 목록으로 불러오기")
        advanced_layout.addWidget(btn_load_json)
        layout.addWidget(advanced)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

        self.alias_list.currentRowChanged.connect(self.load_alias_to_form)
        btn_add_update.clicked.connect(lambda: self.apply_form(silent=False))
        btn_delete.clicked.connect(self.delete_selected_alias)
        btn_load_json.clicked.connect(self.load_aliases_from_editor)
        self.refresh_alias_list(select_row=0 if self.aliases else -1)
        self.sync_editor()

    def refresh_alias_list(self, *, select_row: int = -1) -> None:
        self.alias_list.blockSignals(True)
        self.alias_list.clear()
        for source, alias in sorted(
            self.aliases.items(), key=lambda item: item[0].casefold()
        ):
            item = QListWidgetItem(f"{source} -> {alias}")
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.alias_list.addItem(item)
        self.alias_list.blockSignals(False)
        if self.aliases:
            row = min(max(select_row, 0), self.alias_list.count() - 1)
            self.alias_list.setCurrentRow(row)
            self.load_alias_to_form(row)
        else:
            self.load_alias_to_form(-1)

    def load_alias_to_form(self, row: int) -> None:
        if row < 0 or row >= self.alias_list.count():
            self._editing_source = ""
            self.txt_source.clear()
            self.txt_alias.clear()
            return
        item = self.alias_list.item(row)
        if item is None:
            return
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._editing_source = source
        self.txt_source.setText(source)
        self.txt_alias.setText(str(self.aliases.get(source, "")))

    def apply_form(self, *, silent: bool = False) -> bool:
        source = " ".join(self.txt_source.text().strip().split())
        alias = " ".join(self.txt_alias.text().strip().split())
        if not source and not alias:
            return True
        if not source or not alias:
            if not silent:
                QMessageBox.warning(
                    self, "출처 Alias", "source와 alias를 모두 입력하세요."
                )
            return False
        if self._editing_source and self._editing_source != source:
            self.aliases.pop(self._editing_source, None)
        normalized = normalize_publisher_aliases({**self.aliases, source: alias})
        dropped = max(0, len(self.aliases) + 1 - len(normalized))
        self.aliases = normalized
        self._editing_source = source
        self.refresh_alias_list(select_row=0)
        self.sync_editor()
        if not silent:
            QMessageBox.information(
                self,
                "출처 Alias",
                f"Alias를 반영했습니다. 정규화로 제외된 항목: {dropped}개",
            )
        return True

    def delete_selected_alias(self) -> None:
        item = self.alias_list.currentItem()
        if item is None:
            return
        source = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if source:
            self.aliases.pop(source, None)
        self.refresh_alias_list(select_row=max(0, self.alias_list.currentRow() - 1))
        self.sync_editor()

    def sync_editor(self) -> None:
        self.editor.setPlainText(json.dumps(self.aliases, ensure_ascii=False, indent=2))

    def load_aliases_from_editor(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText() or "{}")
            raw_count = len(payload) if isinstance(payload, dict) else 0
            aliases = normalize_publisher_aliases(payload)
            dropped = max(0, raw_count - len(aliases))
            self.aliases = aliases
            self.refresh_alias_list(select_row=0 if self.aliases else -1)
            self.sync_editor()
            QMessageBox.information(
                self,
                "출처 Alias",
                f"JSON에서 {len(aliases)}개 alias를 불러왔습니다. 정규화로 제외된 항목: {dropped}개",
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "출처 Alias", f"JSON 불러오기에 실패했습니다.\n\n{exc}"
            )

    def save(self) -> None:
        try:
            if not self.apply_form(silent=True):
                return
            aliases = normalize_publisher_aliases(self.aliases)
            self.save_callback(aliases)
            self.aliases = aliases
            self.refresh_alias_list(select_row=self.alias_list.currentRow())
            self.sync_editor()
            QMessageBox.information(
                self, "출처 Alias", f"Alias {len(aliases)}개를 저장했습니다."
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "출처 Alias", f"Alias 저장에 실패했습니다.\n\n{exc}"
            )


__all__ = ["PublisherAliasDialog"]
