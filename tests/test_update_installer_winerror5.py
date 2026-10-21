"""WinError 5(rename-swap) regression tests for the one-file updater."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest import mock

import pytest

from core import update_installer


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(target: Path, staged: Path, backup: Path, *, old: bytes = b"old", new: bytes = b"new") -> None:
    target.write_bytes(old)
    staged.write_bytes(new)
    assert _sha256(new) == hashlib.sha256(new).hexdigest()


def _apply_ok(target: Path, staged: Path, backup: Path, new: bytes = b"new") -> None:
    with mock.patch("core.update_installer.subprocess.run", return_value=mock.Mock(returncode=0)):
        with mock.patch("core.update_installer.subprocess.Popen"):
            with mock.patch("core.update_installer._notify_shell_icon_changed"):
                update_installer.apply_staged_update(
                    target=target,
                    staged=staged,
                    backup=backup,
                    expected_sha256=_sha256(new),
                    expected_size=len(new),
                )


def test_rename_swap_overwrites_stale_backup_without_copy(tmp_path: Path):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "NewsScraperPro_Safe.exe.v32.bak"
    _write(target, staged, backup)
    backup.write_bytes(b"stale-backup")

    with mock.patch("core.update_installer.shutil.copy2", side_effect=AssertionError("copy must not be used")):
        _apply_ok(target, staged, backup)

    assert target.read_bytes() == b"new"
    # Stale backup is overwritten with the previous install, not kept.
    assert backup.read_bytes() == b"old"


def test_first_move_failure_leaves_install_intact(tmp_path: Path):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "NewsScraperPro_Safe.exe.v32.bak"
    _write(target, staged, backup)

    real_replace = os.replace
    calls: list[tuple[Path, Path]] = []

    def locked_first_move(src, dst):
        calls.append((Path(src), Path(dst)))
        if len(calls) == 1:
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst)

    with mock.patch.object(update_installer.os, "replace", side_effect=locked_first_move):
        with mock.patch("core.update_installer.subprocess.run") as smoke:
            try:
                update_installer.apply_staged_update(
                    target=target,
                    staged=staged,
                    backup=backup,
                    expected_sha256=_sha256(b"new"),
                    expected_size=3,
                )
            except PermissionError:
                pass
            else:
                raise AssertionError("first-move failure must propagate")
            smoke.assert_not_called()

    assert target.read_bytes() == b"old"
    assert staged.read_bytes() == b"new"


def test_interrupted_swap_recovers_backup_on_next_run(tmp_path: Path):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "NewsScraperPro_Safe.exe.v32.bak"
    _write(target, staged, backup)
    # Simulate a crash between the two moves: target is gone, backup holds old.
    os.replace(target, backup)
    assert not target.exists()
    assert backup.read_bytes() == b"old"

    _apply_ok(target, staged, backup)

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"


def test_interrupted_swap_recovers_sibling_backup_with_new_backup_name(tmp_path: Path):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    old_backup = tmp_path / "NewsScraperPro_Safe.exe.v32.aaaaaaaa.bak"
    new_backup = tmp_path / "NewsScraperPro_Safe.exe.v33.bbbbbbbb.bak"
    old_backup.write_bytes(b"old")
    staged.write_bytes(b"new")
    assert not target.exists()

    _apply_ok(target, staged, new_backup)

    assert target.read_bytes() == b"new"
    assert new_backup.read_bytes() == b"old"


def test_rollback_after_smoke_failure_restores_previous_exe(tmp_path: Path):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "NewsScraperPro_Safe.exe.v32.bak"
    _write(target, staged, backup)

    with mock.patch("core.update_installer.subprocess.run", return_value=mock.Mock(returncode=1)):
        with mock.patch("core.update_installer.subprocess.Popen") as restart:
            with mock.patch("core.update_installer._notify_shell_icon_changed"):
                with pytest.raises(RuntimeError, match="복구"):
                    update_installer.apply_staged_update(
                        target=target,
                        staged=staged,
                        backup=backup,
                        expected_sha256=_sha256(b"new"),
                        expected_size=3,
                    )
            restart.assert_not_called()

    assert target.read_bytes() == b"old"


def test_child_env_strips_bootloader_variables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    backup = tmp_path / "NewsScraperPro_Safe.exe.v32.bak"
    _write(target, staged, backup)
    monkeypatch.setenv("_MEIPASS", r"C:\fake\_mei123")
    monkeypatch.setenv("_MEI_FOO", r"C:\fake")
    monkeypatch.setenv("_MEIPASS2", r"C:\fake2")
    monkeypatch.setenv("PYINSTALLER_BUNDLE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")

    with mock.patch("core.update_installer.subprocess.run", return_value=mock.Mock(returncode=0)) as smoke:
        with mock.patch("core.update_installer.subprocess.Popen") as restart:
            with mock.patch("core.update_installer._notify_shell_icon_changed"):
                update_installer.apply_staged_update(
                    target=target,
                    staged=staged,
                    backup=backup,
                    expected_sha256=_sha256(b"new"),
                    expected_size=3,
                )

    for name, mocked in (("smoke", smoke), ("restart", restart)):
        assert mocked.call_count == 1, name
        env = mocked.call_args.kwargs.get("env")
        assert env is not None, f"{name} must pass a sanitized env"
        assert "KEEP_ME" in env and env["KEEP_ME"] == "yes"
        for key in env:
            upper = key.upper()
            assert not (upper == "_MEIPASS" or upper.startswith("_MEI") or upper.startswith("_MEIPASS") or upper.startswith("PYINSTALLER_")), key


def test_launch_helper_uses_clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("_MEIPASS", r"C:\fake\_mei123")
    monkeypatch.setenv("PYINSTALLER_RESET", "1")
    target = tmp_path / "NewsScraperPro_Safe.exe"
    staged = tmp_path / "staged.exe"
    staged.write_bytes(b"new")
    result_file = tmp_path / "last-update-result.json"

    with mock.patch("core.update_installer.shutil.copy2"):
        with mock.patch("core.update_installer.subprocess.Popen") as popen:
            with mock.patch("core.update_installer.sys.executable", str(staged)):
                update_installer.launch_update_helper(
                    target=target,
                    staged=staged,
                    version="32.11.3",
                    sha256=_sha256(b"new"),
                    size=3,
                    result_file=result_file,
                )

    assert popen.call_count == 1
    env = popen.call_args.kwargs.get("env")
    assert env is not None
    for key in env:
        upper = key.upper()
        assert not (upper == "_MEIPASS" or upper.startswith("_MEI") or upper.startswith("_MEIPASS") or upper.startswith("PYINSTALLER_")), key
