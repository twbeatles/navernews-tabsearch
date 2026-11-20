import threading
import time
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from core.constants import get_runtime_paths
from core.workers_support.lifecycle import request_background_shutdown
from ui.main_window import MainApp
from ui.main_window_support.auto_backup import _AutoBackupRelay, auto_backup_status_text


def pump_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_timer_backup_runs_off_gui_thread_and_restores_article_state(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainApp(
        runtime_paths=get_runtime_paths(data_dir=str(tmp_path)), smoke_mode=True
    )
    try:
        window.save_config()
        assert window.db is not None
        link = "https://example.com/backup"
        window.db.upsert_news(
            [
                dict(
                    link=link,
                    title="Title",
                    description="summary",
                    publisher="example.com",
                    pubDate="Mon, 01 Jan 2024 00:00:00 +0000",
                )
            ],
            "audit",
        )
        window.db.save_note(link, "메모")
        window.db.set_tags(link, ["important"])
        original = window.auto_backup.create_backup
        called_threads = []
        entered = threading.Event()
        release = threading.Event()

        def delayed_backup(*args, **kwargs):
            called_threads.append(QThread.currentThread() == app.thread())
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)

        with mock.patch.object(
            window.auto_backup, "create_backup", side_effect=delayed_backup
        ) as create:
            window._run_auto_backup_once()
            assert entered.wait(1)
            window._run_auto_backup_once()
            assert create.call_count == 1
            assert not request_background_shutdown(
                [window._auto_backup_worker], wait_ms=1
            )
            QTimer.singleShot(0, release.set)
            pump_until(app, lambda: window._auto_backup_worker is None)
        assert called_threads == [False]
        status = window.auto_backup.get_auto_backup_status()
        assert status["last_success_include_db"]
        path = Path(status["last_success_path"])
        assert (path / Path(window.runtime_paths.db_file).name).exists()
        assert "DB + 설정" in auto_backup_status_text(window.auto_backup)
    finally:
        window.real_quit()
        app.processEvents()
        window.deleteLater()
        app.processEvents()


def test_backup_error_is_gui_delivered_throttled_and_cleared_on_success(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainApp(
        runtime_paths=get_runtime_paths(data_dir=str(tmp_path)), smoke_mode=True
    )
    try:
        window.save_config()
        with mock.patch.object(window, "show_warning_toast") as warn:
            with mock.patch.object(
                window.auto_backup, "_snapshot_db", side_effect=OSError("disk full")
            ):
                window._run_auto_backup_once()
                pump_until(app, lambda: window._auto_backup_worker is None)
            assert warn.call_count == 1
            assert "disk full" in str(warn.call_args)
            assert "disk full" in auto_backup_status_text(window.auto_backup)
            relay = _AutoBackupRelay(window)
            relay.completed({"path": None, "error": "disk full"})
            assert warn.call_count == 1
            relay.completed({"path": "success", "error": ""})
            relay.completed({"path": None, "error": "disk full"})
            assert warn.call_count == 2
            window._shutdown_in_progress = True
            relay.completed({"path": None, "error": "different"})
            assert warn.call_count == 2
    finally:
        window.real_quit()
        app.processEvents()
        window.deleteLater()
        app.processEvents()
