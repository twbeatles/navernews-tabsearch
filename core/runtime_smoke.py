"""Actual UI/database startup smoke for the isolated updater subprocess."""

import logging
import os
import sys
from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.constants import DATA_DIR
from core.runtime_support.paths import get_runtime_paths
from ui.main_window import MainApp


def run_smoke(data_dir: str) -> int:
    if os.path.realpath(DATA_DIR) != os.path.realpath(data_dir):
        raise RuntimeError("smoke runtime was imported before isolation")
    app = cast(QApplication, QApplication.instance() or QApplication(["news-smoke"]))
    app.setQuitOnLastWindowClosed(False)
    failed = False
    previous_hook = sys.excepthook

    def record_failure(*exc_info):
        nonlocal failed
        failed = True
        logging.error("Smoke Qt callback failed", exc_info=exc_info)

    sys.excepthook = record_failure
    window = None
    try:
        window = MainApp(runtime_paths=get_runtime_paths(data_dir=data_dir), smoke_mode=True)
        window.show()

        def verify_and_close():
            nonlocal failed
            try:
                if window is None or window.db is None or window.tabs.count() < 1:
                    raise RuntimeError("main UI or database did not initialize")
                with window.db.connection() as conn:
                    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("smoke database check failed")
            except Exception:
                failed = True
                logging.exception("Smoke startup check failed")
            finally:
                if window is not None:
                    window.real_quit()

        QTimer.singleShot(100, verify_and_close)
        exit_code = app.exec()
        return 1 if failed or exit_code else 0
    finally:
        sys.excepthook = previous_hook
        if window is not None:
            if window.db is not None:
                window.db.close()
            window.deleteLater()
        app.processEvents()
