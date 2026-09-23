"""Download verification and two-process replacement for the one-file build."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from core.constants import UPDATE_ARTIFACT_MAX_BYTES, UPDATE_BACKUP_KEEP_COUNT, UPDATE_REQUEST_TIMEOUT_SECONDS
from core.update_manifest import ReleaseManifest

logger = logging.getLogger(__name__)


def resolve_update_staging_root(data_dir: str | Path) -> Path:
    root = Path(data_dir).resolve() / "updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def update_result_path(staging_root: str | Path) -> Path:
    return Path(staging_root).resolve() / "last-update-result.json"


def write_update_result(path: str | Path, payload: dict[str, object]) -> None:
    result_path = Path(path).resolve()
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    if str(data.get("status", "")) not in {"applied", "rolled_back", "failed"}:
        raise ValueError("invalid update result status")
    temp_path = result_path.with_name(f".{result_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp_path, result_path)
    finally:
        temp_path.unlink(missing_ok=True)


def consume_update_result(path: str | Path) -> dict[str, object] | None:
    result_path = Path(path).resolve()
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        result_path.unlink(missing_ok=True)
        return None
    result_path.unlink(missing_ok=True)
    if not isinstance(data, dict) or str(data.get("status", "")) not in {"applied", "rolled_back", "failed"}:
        return None
    return data


def cleanup_update_artifacts(staging_root: str | Path, *, max_age_seconds: float = 7 * 24 * 60 * 60) -> list[Path]:
    root = Path(staging_root).resolve()
    if not root.is_dir():
        return []
    cutoff = time.time() - max(0.0, float(max_age_seconds))
    removed: list[Path] = []
    for pattern in ("update-helper-*.exe", "update-*.exe"):
        for candidate in root.glob(pattern):
            try:
                if candidate.stat().st_mtime > cutoff:
                    continue
                candidate.unlink()
                removed.append(candidate)
            except OSError:
                continue
    return removed


def stream_update_artifact(manifest: ReleaseManifest):
    with urlopen(Request(manifest.artifact_url, headers={"User-Agent": "NaverNewsScraperPro-Updater"}), timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response:
        if urlsplit(response.geturl()).scheme != "https":
            raise ValueError("업데이트 파일 리디렉션이 HTTPS가 아닙니다.")
        while chunk := response.read(1024 * 1024):
            yield chunk


def prepare_staged_update(manifest: ReleaseManifest, *, staging_root: str | Path) -> Path:
    root = Path(staging_root).resolve()
    staged = root / f"update-{manifest.version}-{uuid4().hex}.exe"
    digest, total = hashlib.sha256(), 0
    try:
        with staged.open("xb") as handle:
            for chunk in stream_update_artifact(manifest):
                total += len(chunk)
                if total > manifest.artifact_size or total > UPDATE_ARTIFACT_MAX_BYTES:
                    raise ValueError("업데이트 파일 크기가 일치하지 않습니다.")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total != manifest.artifact_size or digest.hexdigest().lower() != manifest.artifact_sha256:
            raise ValueError("업데이트 파일 무결성 검증에 실패했습니다.")
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _wait_for_parent(pid: int, timeout: float = 30.0) -> None:
    """Return once the parent process exits; raise TimeoutError on expiry.

    Windows note: ``os.kill(pid, 0)`` still succeeds for a recently exited PID,
    so the old poll loop never observed the shutdown and always hit the
    timeout. The helper then recorded ``failed`` and the updated program was
    never relaunched. A process-handle wait is used on Windows instead.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return  # PID is already gone.
        try:
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            result = kernel32.WaitForSingleObject(handle, remaining_ms)
            if result == WAIT_OBJECT_0:
                return
            if result == WAIT_TIMEOUT:
                raise TimeoutError("기존 프로그램이 종료되지 않았습니다.")
            raise OSError(f"부모 프로세스 종료 대기에 실패했습니다: {result:#x}")
        finally:
            kernel32.CloseHandle(handle)
    else:
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.2)
        raise TimeoutError("기존 프로그램이 종료되지 않았습니다.")


def _notify_shell_icon_changed(path: Path) -> None:
    """Ask Explorer to re-read the icon after the executable is replaced in place.

    Windows caches the icon for a path. Replacing that file leaves the cache
    pointing at a blank icon until the shell is told the item changed.
    """
    if sys.platform != "win32":
        return
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHChangeNotify.argtypes = [ctypes.c_ulong, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_void_p]
        shell32.SHChangeNotify.restype = None
        shell32.SHChangeNotify(0x00002000, 0x0005, str(path), None)  # SHCNE_UPDATEITEM, SHCNF_PATHW
    except Exception as exc:
        logger.warning("업데이트된 실행 파일의 아이콘 갱신 알림에 실패했습니다: %s", exc)


def apply_staged_update(*, target: Path, staged: Path, backup: Path, expected_sha256: str, expected_size: int) -> None:
    target, staged, backup = target.resolve(), staged.resolve(), backup.resolve()
    if len({target, staged, backup}) != 3 or target.suffix.lower() != ".exe" or staged.suffix.lower() != ".exe" or backup.parent != target.parent:
        raise ValueError("업데이트 교체 경로가 올바르지 않습니다.")
    if not target.is_file() or not staged.is_file() or backup.exists() or staged.stat().st_size != expected_size:
        raise ValueError("업데이트 교체 파일을 확인할 수 없습니다.")
    digest_builder = hashlib.sha256()
    with staged.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest().lower()
    if digest != expected_sha256.lower():
        raise ValueError("업데이트 파일 무결성 재검증에 실패했습니다.")
    shutil.copy2(target, backup)
    try:
        os.replace(staged, target)
        completed = subprocess.run([str(target), "--smoke"], timeout=60, check=False, capture_output=True)
        if completed.returncode:
            raise RuntimeError("업데이트된 프로그램의 시작 점검에 실패했습니다.")
        subprocess.Popen([str(target)], close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        if backup.is_file():
            os.replace(backup, target)
            _notify_shell_icon_changed(target)
            raise RuntimeError("업데이트 실패 후 이전 버전으로 복구했습니다.") from exc
        raise
    _notify_shell_icon_changed(target)
    try:
        backups = sorted(target.parent.glob(f"{target.name}.v*.bak"), key=lambda path: path.stat().st_mtime, reverse=True)
        for old in backups[UPDATE_BACKUP_KEEP_COUNT:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def launch_update_helper(*, target: Path, staged: Path, version: str, sha256: str, size: int, result_file: Path) -> None:
    helper = staged.parent / f"update-helper-{uuid4().hex}.exe"
    shutil.copy2(Path(sys.executable).resolve(), helper)
    backup = target.with_name(f"{target.name}.v{version}.{uuid4().hex[:8]}.bak")
    try:
        subprocess.Popen([str(helper), "--apply-update", "--target", str(target), "--staged", str(staged), "--backup", str(backup), "--parent-pid", str(os.getpid()), "--expected-sha256", sha256, "--expected-size", str(size), "--result-file", str(result_file.resolve())], close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        helper.unlink(missing_ok=True)
        raise


def handle_update_helper_args(argv: list[str] | None = None) -> int | None:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in args:
        return 0
    if "--apply-update" not in args:
        return None
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-update", action="store_true")
    parser.add_argument("--target", required=True)
    parser.add_argument("--staged", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", required=True, type=int)
    parser.add_argument("--result-file", required=True)
    parsed = parser.parse_args(args)
    result_file = Path(parsed.result_file)
    base_result = {
        "target": str(Path(parsed.target).resolve()),
        "backup": str(Path(parsed.backup).resolve()),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _wait_for_parent(parsed.parent_pid)
        apply_staged_update(target=Path(parsed.target), staged=Path(parsed.staged), backup=Path(parsed.backup), expected_sha256=parsed.expected_sha256, expected_size=parsed.expected_size)
    except Exception as exc:
        status = "rolled_back" if "복구" in str(exc) else "failed"
        write_update_result(result_file, {**base_result, "status": status, "error": str(exc)})
        return 1
    write_update_result(result_file, {**base_result, "status": "applied"})
    return 0
