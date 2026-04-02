from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget


class QtDialogAdapter:
    """Thin wrapper around Qt static dialogs for easier testing."""

    def get_save_file_name(
        self,
        parent: QWidget | None,
        title: str,
        default_name: str,
        filters: str,
    ) -> tuple[str, str]:
        return QFileDialog.getSaveFileName(parent, title, default_name, filters)

    def get_open_file_name(
        self,
        parent: QWidget | None,
        title: str,
        directory: str,
        filters: str,
    ) -> tuple[str, str]:
        return QFileDialog.getOpenFileName(parent, title, directory, filters)

    def information(self, parent: QWidget | None, title: str, message: str) -> None:
        QMessageBox.information(parent, title, message)

    def warning(self, parent: QWidget | None, title: str, message: str) -> None:
        QMessageBox.warning(parent, title, message)

    def critical(self, parent: QWidget | None, title: str, message: str) -> None:
        QMessageBox.critical(parent, title, message)

    def ask_yes_no(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        default: QMessageBox.StandardButton = QMessageBox.StandardButton.No,
    ) -> bool:
        reply = QMessageBox.question(
            parent,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default,
        )
        return reply == QMessageBox.StandardButton.Yes

    def ask_corrupt_backup_action(
        self,
        parent: QWidget | None,
        backup_name: str,
        corrupt_error: str,
    ) -> str:
        dialog = QMessageBox(parent)
        dialog.setWindowTitle("손상된 백업")
        dialog.setIcon(QMessageBox.Icon.Warning)
        detail = f"\n\n오류 정보: {corrupt_error}" if corrupt_error else ""
        dialog.setText(f"'{backup_name}' 항목은 손상되어 복원할 수 없습니다.{detail}")
        btn_delete = dialog.addButton("삭제", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("무시", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return "delete" if dialog.clickedButton() == btn_delete else "ignore"


DEFAULT_DIALOG_ADAPTER = QtDialogAdapter()


def get_dialog_adapter(target: Any) -> QtDialogAdapter:
    adapter = getattr(target, "_dialog_adapter", None)
    if adapter is None:
        return DEFAULT_DIALOG_ADAPTER
    return adapter
