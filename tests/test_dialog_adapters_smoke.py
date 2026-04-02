import os
import unittest
from unittest import mock

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from ui.dialog_adapters import QtDialogAdapter


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestDialogAdaptersSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_qt_dialog_adapter_forwards_to_qt_static_dialogs(self):
        adapter = QtDialogAdapter()
        parent = QWidget()
        self.addCleanup(parent.deleteLater)

        with mock.patch("ui.dialog_adapters.QFileDialog.getSaveFileName", return_value=("C:\\tmp\\file.csv", "CSV")) as save_mock:
            with mock.patch("ui.dialog_adapters.QFileDialog.getOpenFileName", return_value=("C:\\tmp\\config.json", "JSON")) as open_mock:
                with mock.patch("ui.dialog_adapters.QMessageBox.information") as info_mock:
                    with mock.patch("ui.dialog_adapters.QMessageBox.warning") as warning_mock:
                        with mock.patch(
                            "ui.dialog_adapters.QMessageBox.question",
                            return_value=QMessageBox.StandardButton.Yes,
                        ) as question_mock:
                            save_result = adapter.get_save_file_name(parent, "저장", "export.csv", "CSV (*.csv)")
                            open_result = adapter.get_open_file_name(parent, "열기", "", "JSON (*.json)")
                            adapter.information(parent, "완료", "saved")
                            adapter.warning(parent, "오류", "failed")
                            answer = adapter.ask_yes_no(parent, "확인", "진행할까요?")

        self.assertEqual(save_result, ("C:\\tmp\\file.csv", "CSV"))
        self.assertEqual(open_result, ("C:\\tmp\\config.json", "JSON"))
        self.assertTrue(answer)
        save_mock.assert_called_once()
        open_mock.assert_called_once()
        info_mock.assert_called_once()
        warning_mock.assert_called_once()
        question_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
