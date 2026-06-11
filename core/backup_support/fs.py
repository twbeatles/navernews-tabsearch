import json
import logging
import os
import shutil
import stat
import tempfile
import ntpath
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _retry_remove_readonly(func, path: str, _exc_info) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    except OSError:
        pass
    func(path)
def _rmtree_force(path: str) -> None:
    try:
        shutil.rmtree(path, onexc=_retry_remove_readonly)
    except TypeError:
        shutil.rmtree(path, onerror=_retry_remove_readonly)
def _write_json_atomic(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".pending_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _safe_backup_child_dir(root_dir: str, backup_name: str) -> tuple[bool, str, str]:
    root_abs = os.path.abspath(str(root_dir or ""))
    name = str(backup_name or "").strip()
    if not name:
        return False, "", "백업 이름이 비어 있습니다."
    if name in {".", ".."}:
        return False, "", "백업 이름이 안전하지 않습니다."
    if os.path.isabs(name) or ntpath.isabs(name) or ntpath.splitdrive(name)[0]:
        return False, "", "백업 이름은 상대 이름만 허용됩니다."
    if any(separator in name for separator in ("/", "\\")) or ":" in name:
        return False, "", "백업 이름에는 경로 구분자를 사용할 수 없습니다."

    target_abs = os.path.abspath(os.path.join(root_abs, name))
    try:
        if os.path.commonpath([root_abs, target_abs]) != root_abs:
            return False, "", "백업 경로가 백업 폴더 밖을 가리킵니다."
    except ValueError:
        return False, "", "백업 경로가 백업 폴더 밖을 가리킵니다."
    return True, target_abs, ""


def _atomic_copy_replace(src_path: str, dst_path: str) -> None:
    directory = os.path.dirname(os.path.abspath(dst_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".restore_", suffix=".tmp", dir=directory)
    try:
        os.close(fd)
        shutil.copy2(src_path, tmp_path)
        os.replace(tmp_path, dst_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
def _snapshot_files_for_rollback(paths: List[str], staging_dir: str) -> Dict[str, Optional[str]]:
    snapshots: Dict[str, Optional[str]] = {}
    os.makedirs(staging_dir, exist_ok=True)
    for idx, path in enumerate(paths):
        if os.path.exists(path):
            snapshot_path = os.path.join(staging_dir, f"rollback_{idx:03d}")
            shutil.copy2(path, snapshot_path)
            snapshots[path] = snapshot_path
        else:
            snapshots[path] = None
    return snapshots
def _rollback_files_from_snapshot(snapshots: Dict[str, Optional[str]]) -> None:
    for target, snapshot in snapshots.items():
        try:
            if snapshot and os.path.exists(snapshot):
                try:
                    _atomic_copy_replace(snapshot, target)
                except Exception:
                    directory = os.path.dirname(os.path.abspath(target)) or "."
                    os.makedirs(directory, exist_ok=True)
                    shutil.copy2(snapshot, target)
            elif os.path.exists(target):
                os.remove(target)
        except Exception as rollback_error:
            logger.error("rollback failed for %s: %s", target, rollback_error)
def _cleanup_restore_stage_dir(staging_dir: str) -> None:
    try:
        _rmtree_force(staging_dir)
    except FileNotFoundError:
        return
    except Exception as cleanup_error:
        logger.warning("restore staging cleanup failed for %s: %s", staging_dir, cleanup_error)
