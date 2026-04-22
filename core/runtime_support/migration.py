from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
from typing import Optional

from .paths import (
    BACKUP_DIRNAME,
    CONFIG_BACKUP_FILENAME,
    CONFIG_FILENAME,
    DB_FILENAME,
    KEYWORD_GROUPS_FILENAME,
    LOG_FILENAME,
    PENDING_RESTORE_FILENAME,
    RuntimePaths,
    get_app_dir,
    get_runtime_paths,
)

logger = logging.getLogger(__name__)


def _copy_path_if_missing(src_path: str, dst_path: str) -> bool:
    if not os.path.exists(src_path) or os.path.exists(dst_path):
        return False

    parent_dir = os.path.dirname(os.path.abspath(dst_path)) or "."
    os.makedirs(parent_dir, exist_ok=True)
    shutil.copy2(src_path, dst_path)
    return True


def _write_json_atomic(path: str, payload: dict) -> None:
    parent_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".runtime_", suffix=".tmp", dir=parent_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _sqlite_integrity_state(db_path: str) -> tuple[str, str]:
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row and str(row[0]).lower() == "ok":
            return "ok", ""
        detail = str(row[0]) if row and row[0] is not None else "unknown"
        return "corrupt", detail
    except (sqlite3.Error, OSError) as exc:
        return "unreadable", str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _cleanup_db_target_set(db_path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = f"{db_path}{suffix}"
        if not os.path.exists(candidate):
            continue
        try:
            os.remove(candidate)
        except OSError:
            pass


def _copy_db_set(src_db_path: str, dst_db_path: str) -> None:
    parent_dir = os.path.dirname(os.path.abspath(dst_db_path)) or "."
    os.makedirs(parent_dir, exist_ok=True)
    shutil.copy2(src_db_path, dst_db_path)
    for suffix in ("-wal", "-shm"):
        src_sidecar = f"{src_db_path}{suffix}"
        dst_sidecar = f"{dst_db_path}{suffix}"
        if os.path.exists(src_sidecar):
            shutil.copy2(src_sidecar, dst_sidecar)
        elif os.path.exists(dst_sidecar):
            os.remove(dst_sidecar)


def _sqlite_backup_copy(src_db_path: str, dst_db_path: str) -> tuple[bool, str]:
    src_conn: Optional[sqlite3.Connection] = None
    dst_conn: Optional[sqlite3.Connection] = None
    try:
        parent_dir = os.path.dirname(os.path.abspath(dst_db_path)) or "."
        os.makedirs(parent_dir, exist_ok=True)
        src_conn = sqlite3.connect(src_db_path, timeout=10.0)
        dst_conn = sqlite3.connect(dst_db_path, timeout=10.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
        return True, ""
    except Exception as exc:
        return False, str(exc)
    finally:
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass


def _migrate_legacy_database(src_db_path: str, dst_db_path: str) -> bool:
    if not os.path.exists(src_db_path) or os.path.exists(dst_db_path):
        return False

    backup_ok, backup_error = _sqlite_backup_copy(src_db_path, dst_db_path)
    if backup_ok:
        state, detail = _sqlite_integrity_state(dst_db_path)
        if state == "ok":
            logger.info("Legacy DB migrated with SQLite backup API: %s", dst_db_path)
            return True
        logger.warning(
            "Legacy DB backup migration did not verify cleanly; retrying with raw copy. state=%s detail=%s",
            state,
            detail,
        )
        _cleanup_db_target_set(dst_db_path)
    elif backup_error:
        logger.warning("Legacy DB backup migration failed, using raw copy fallback: %s", backup_error)

    try:
        _copy_db_set(src_db_path, dst_db_path)
    except OSError as exc:
        logger.warning("Legacy DB raw copy fallback failed: %s", exc)
        _cleanup_db_target_set(dst_db_path)
        return False

    state, detail = _sqlite_integrity_state(dst_db_path)
    if state == "ok":
        logger.info("Legacy DB migrated with raw copy fallback: %s", dst_db_path)
        return True

    logger.warning(
        "Legacy DB fallback copy did not pass integrity validation. state=%s detail=%s",
        state,
        detail,
    )
    _cleanup_db_target_set(dst_db_path)
    return False


def _merge_backup_directories(source_backup_dir: str, destination_backup_dir: str) -> bool:
    if not os.path.isdir(source_backup_dir):
        return False

    copied_any = False
    os.makedirs(destination_backup_dir, exist_ok=True)
    for entry_name in sorted(os.listdir(source_backup_dir)):
        if not entry_name.startswith("backup_"):
            continue
        source_entry = os.path.join(source_backup_dir, entry_name)
        destination_entry = os.path.join(destination_backup_dir, entry_name)
        if not os.path.isdir(source_entry) or os.path.exists(destination_entry):
            continue
        try:
            shutil.copytree(source_entry, destination_entry)
            copied_any = True
        except OSError as exc:
            logger.warning("Legacy backup directory merge skipped for %s: %s", source_entry, exc)
    return copied_any


def _migrate_pending_restore_file(src_path: str, dst_path: str, runtime_paths: RuntimePaths) -> bool:
    if not os.path.exists(src_path) or os.path.exists(dst_path):
        return False

    try:
        with open(src_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("pending restore payload is not a JSON object")
        payload["backup_dir"] = runtime_paths.backup_dir
        _write_json_atomic(dst_path, payload)
        return True
    except Exception as exc:
        logger.warning("Legacy pending restore payload could not be rebased; copying raw file instead: %s", exc)
        try:
            return _copy_path_if_missing(src_path, dst_path)
        except OSError:
            return False


def migrate_legacy_runtime_files(
    legacy_dir: Optional[str] = None,
    data_dir: Optional[str] = None,
    *,
    runtime_paths: Optional[RuntimePaths] = None,
) -> list[str]:
    source_dir = os.path.abspath(legacy_dir or get_app_dir())
    resolved_runtime_paths = runtime_paths or get_runtime_paths(app_dir=source_dir, data_dir=data_dir)
    target_dir = resolved_runtime_paths.data_dir
    if source_dir == target_dir:
        return []

    os.makedirs(target_dir, exist_ok=True)

    migrated: list[str] = []
    file_pairs = [
        (CONFIG_FILENAME, resolved_runtime_paths.config_file),
        (CONFIG_BACKUP_FILENAME, resolved_runtime_paths.config_backup_file),
        (LOG_FILENAME, resolved_runtime_paths.log_file),
        (KEYWORD_GROUPS_FILENAME, resolved_runtime_paths.keyword_groups_file),
    ]

    for source_name, destination_path in file_pairs:
        source_path = os.path.join(source_dir, source_name)
        try:
            if _copy_path_if_missing(source_path, destination_path):
                migrated.append(destination_path)
        except OSError:
            continue

    source_db_path = os.path.join(source_dir, DB_FILENAME)
    try:
        if _migrate_legacy_database(source_db_path, resolved_runtime_paths.db_file):
            migrated.append(resolved_runtime_paths.db_file)
    except Exception as exc:
        logger.warning("Legacy DB migration failed: %s", exc)

    source_pending_restore = os.path.join(source_dir, PENDING_RESTORE_FILENAME)
    try:
        if _migrate_pending_restore_file(
            source_pending_restore,
            resolved_runtime_paths.pending_restore_file,
            resolved_runtime_paths,
        ):
            migrated.append(resolved_runtime_paths.pending_restore_file)
    except Exception as exc:
        logger.warning("Legacy pending restore migration failed: %s", exc)

    source_backup_dir = os.path.join(source_dir, BACKUP_DIRNAME)
    if _merge_backup_directories(source_backup_dir, resolved_runtime_paths.backup_dir):
        migrated.append(resolved_runtime_paths.backup_dir)

    return migrated


__all__ = ["migrate_legacy_runtime_files"]
