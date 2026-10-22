"""Audit boundaries: real startup/shutdown, volume swaps and bounded export."""
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tracemalloc
from unittest import mock
from typing import Any, cast

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("cryptography")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from core import update_installer
from core.workers_support.lifecycle import request_background_shutdown
from core.workers_support.query_scope import DBQueryScope
from ui.main_window_io_support.exports import export_scope_to_json
from test_json_export import ImmediateExportContext


def test_native_worker_must_finish_even_after_result_signal():
    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()

    class Blocked(QThread):
        def run(self):
            entered.set()
            release.wait(5)

    worker = Blocked()
    worker.start()
    try:
        assert entered.wait(2)
        assert not request_background_shutdown([worker], wait_ms=1)
        assert worker.isRunning()
        release.set()
        assert request_background_shutdown([worker], wait_ms=2000)
    finally:
        release.set()
        worker.wait(5000)
        app.processEvents()


def test_cross_directory_update_renames_only_inside_target_volume(tmp_path):
    install, data = tmp_path / "install", tmp_path / "data"
    install.mkdir()
    data.mkdir()
    target, staged, backup = install / "app.exe", data / "new.exe", install / "app.v1.bak"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    real_replace = os.replace

    def same_volume_only(src, dst):
        if Path(src).parent != Path(dst).parent:
            raise OSError(errno.EXDEV, "different volumes")
        real_replace(src, dst)

    with mock.patch.object(update_installer.os, "replace", side_effect=same_volume_only), \
         mock.patch.object(update_installer.subprocess, "run", return_value=mock.Mock(returncode=0)), \
         mock.patch.object(update_installer.subprocess, "Popen"):
        update_installer.apply_staged_update(
            target=target, staged=staged, backup=backup,
            expected_sha256=hashlib.sha256(b"new").hexdigest(), expected_size=3)
    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert not list(install.glob(".update-*.exe"))


@pytest.mark.parametrize("failure", [PermissionError("read-only"), OSError(errno.ENOSPC, "full")])
def test_preflight_failure_does_not_touch_install_or_start_helper(tmp_path, failure):
    target, staged = tmp_path / "app.exe", tmp_path / "new.exe"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")
    with mock.patch.object(update_installer.os, "fsync", side_effect=failure), \
         mock.patch.object(update_installer.subprocess, "Popen") as launch:
        with pytest.raises(OSError):
            update_installer.launch_update_helper(
                target=target, staged=staged, version="1", size=3,
                sha256=hashlib.sha256(b"new").hexdigest(), result_file=tmp_path / "result.json")
        launch.assert_not_called()
    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"
    assert not list(tmp_path.glob(".update-*"))


def test_helper_records_rollback_before_restarting_previous_app(tmp_path):
    target, staged, backup = (tmp_path / name for name in ("app.exe", "new.exe", "app.v1.bak"))
    result = tmp_path / "result.json"
    target.write_bytes(b"old")
    staged.write_bytes(b"new")

    def restarted(*args, **kwargs):
        assert json.loads(result.read_text(encoding="utf-8"))["status"] == "rolled_back"
        assert target.read_bytes() == b"old"

    args = ["--apply-update", "--target", str(target), "--staged", str(staged),
            "--backup", str(backup), "--parent-pid", "1", "--expected-sha256",
            hashlib.sha256(b"new").hexdigest(), "--expected-size", "3", "--result-file", str(result)]
    with mock.patch.object(update_installer, "_wait_for_parent"), \
         mock.patch.object(update_installer.subprocess, "run", return_value=mock.Mock(returncode=1)), \
         mock.patch.object(update_installer.subprocess, "Popen", side_effect=restarted) as launch:
        assert update_installer.handle_update_helper_args(args) == 1
        launch.assert_called_once()


def test_smoke_ignores_inherited_runtime_directory(tmp_path):
    sentinel = tmp_path / "user-data"
    sentinel.mkdir()
    (sentinel / "news_scraper_config.json").write_bytes(b"do not read or change")
    env = dict(os.environ, NEWS_SCRAPER_DATA_DIR=str(sentinel))
    result = subprocess.run([sys.executable, "news_scraper_pro.py", "--smoke"],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert [p.name for p in sentinel.iterdir()] == ["news_scraper_config.json"]
    assert (sentinel / "news_scraper_config.json").read_bytes() == b"do not read or change"


def test_smoke_detects_main_window_initialization_failure(tmp_path):
    code = """
from unittest.mock import patch
from core.runtime_smoke import run_smoke
import os
with patch('ui.main_window.MainApp.init_ui', side_effect=RuntimeError('bad release')):
    run_smoke(os.environ['NEWS_SCRAPER_DATA_DIR'])
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30,
                            env=dict(os.environ, NEWS_SCRAPER_DATA_DIR=str(tmp_path)))
    assert result.returncode != 0
    assert b"bad release" in result.stderr


class GeneratedDB:
    def iter_news_snapshot_batches(self, scope, chunk_size=100):
        def rows():
            for offset in range(0, 2000, chunk_size):
                yield [{"link": str(i), "description": str(i) + "x" * 4096}
                       for i in range(offset, min(offset + chunk_size, 2000))]
        return 2000, rows()


def test_json_export_memory_is_bounded_by_batches(tmp_path):
    output = tmp_path / "news.json"
    tracemalloc.start()
    try:
        result = export_scope_to_json(ImmediateExportContext(), GeneratedDB(), DBQueryScope(keyword="x"),
                                      str(output), "x", chunk_size=50)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["count"] == 2000
    assert peak < 4 * 1024 * 1024
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["count"] == len(payload["items"]) == 2000


def test_cancelled_json_export_closes_snapshot_and_preserves_file(tmp_path):
    output = tmp_path / "news.json"
    output.write_text("original", encoding="utf-8")
    closed = []

    class DB:
        def iter_news_snapshot_batches(self, scope, chunk_size):
            def rows():
                try:
                    yield [{"link": "1"}]
                    yield [{"link": "2"}]
                finally:
                    closed.append(True)
            return 2, rows()

    class Context(ImmediateExportContext):
        def check_cancelled(self):
            if len(self.reports) > 1:
                raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        export_scope_to_json(Context(), DB(), DBQueryScope(keyword="x"), str(output), "x", chunk_size=1)
    assert closed == [True]
    assert output.read_text() == "original"
    assert not list(tmp_path.glob(".export_*.tmp"))


def test_manual_duplicate_repair_preserves_article_state(tmp_path):
    from types import SimpleNamespace
    from core.database import DatabaseManager
    from ui.settings_dialog import SettingsDialog
    from PySide6.QtWidgets import QMessageBox
    paths = SimpleNamespace(db_file=str(tmp_path / "news.db"))
    db = DatabaseManager(paths.db_file)
    try:
        db.upsert_news([{"link": "L1", "title": "one"}, {"link": "L2", "title": "two"}], "A")
        db.update_status("L1", "is_bookmarked", 1)
        db.save_note("L1", "keep note")
        with db.connection() as conn:
            with conn:
                conn.execute("UPDATE news_keywords SET is_duplicate=1")
    finally:
        db.close()
    dialog = SimpleNamespace(_is_closing=False, _runtime_paths=lambda: paths, _start_data_task=mock.Mock())
    with mock.patch("ui._settings_dialog_tasks.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        SettingsDialog.repair_duplicate_flags(cast(Any, dialog))
    job, done, operation = dialog._start_data_task.call_args.args
    assert operation == "repair_duplicates"
    result = job(ImmediateExportContext())
    with mock.patch("ui._settings_dialog_tasks.QMessageBox.information"):
        done(result)
    assert dialog._pending_parent_data_change == ("repair_duplicates", 2)
    db = DatabaseManager(paths.db_file)
    try:
        rows = db.fetch_news("A", hide_duplicates=True)
        assert len(rows) == 2
        preserved = next(row for row in rows if row["link"] == "L1")
        assert preserved["is_bookmarked"] == 1
        assert preserved["notes"] == "keep note"
    finally:
        db.close()


@pytest.mark.parametrize("mode", ["export", "import", "full"])
def test_closing_during_real_cloud_io_waits_and_reopens_cleanly(tmp_path, mode):
    code = r'''
import os, sqlite3, threading
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from core.database import DatabaseManager
from core.constants import VERSION, get_runtime_paths
from core.cloud_sync import create_cloud_snapshot, read_snapshot_manifest
from ui.main_window import MainApp
root = Path(os.environ['AUDIT_TEST_ROOT'])
sync = root / 'sync'
source = DatabaseManager(str(root / 'source.db'))
source.upsert_news([{'link':'https://example.test/1','title':'test','description':'d'}], 'A')
create_cloud_snapshot(sync_dir=str(sync), config={}, db_file=source.db_file,
                      machine_id='remote-test', app_version=VERSION)
source.close()
app = QApplication([])
window = MainApp(runtime_paths=get_runtime_paths(data_dir=str(root / 'local')), smoke_mode=True)
window.show()
entered, release = threading.Event(), threading.Event()
closed = []
db = window.db
original_close = db.close
def checked_close():
    assert release.is_set(), 'DB closed before cloud operation settled'
    closed.append(True)
    original_close()
db.close = checked_close
original_merge = db._merge_cloud_news_rows
def merge(*args):
    original_merge(*args)
    entered.set()
    assert release.wait(10), 'barrier timeout'
db._merge_cloud_news_rows = merge
def snapshot(**kwargs):
    entered.set()
    assert release.wait(10), 'barrier timeout'
    return create_cloud_snapshot(**kwargs)
def close_when_entered():
    if not entered.is_set():
        QTimer.singleShot(10, close_when_entered)
        return
    threading.Timer(1.3, release.set).start()
    window.real_quit()
    assert not closed, 'first close did not defer'
with patch('ui.main_window_io_support.cloud.create_cloud_snapshot', side_effect=snapshot):
    window._run_cloud_sync_once(mode=os.environ['AUDIT_TEST_MODE'], manual=False,
                               sync_dir_override=str(sync), enabled_override=True)
    assert window._cloud_sync_worker is not None
    QTimer.singleShot(10, close_when_entered)
    assert app.exec() == 0
assert closed
with sqlite3.connect(db.db_file) as conn:
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
for snapshot_path in sync.glob('*.zip'):
    read_snapshot_manifest(str(snapshot_path))
assert not list(sync.glob('*.tmp'))
'''
    result = subprocess.run([sys.executable, "-c", code], timeout=25, capture_output=True,
                            env=dict(os.environ, AUDIT_TEST_ROOT=str(tmp_path), AUDIT_TEST_MODE=mode,
                                     NEWS_SCRAPER_DATA_DIR=str(tmp_path / "local")))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
