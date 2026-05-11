import json
import logging
import os
import sys
import tempfile
from typing import Callable, Dict, Optional

from core.backup_support.constants import DEFAULT_BACKUP_DIR
from core.backup_support.fs import (
    _atomic_copy_replace,
    _cleanup_restore_stage_dir,
    _rollback_files_from_snapshot,
    _snapshot_files_for_rollback,
)
from core.backup_support.validation import verify_backup_payload

logger = logging.getLogger(__name__)


def _facade_override(name: str, default: Callable) -> Callable:
    facade = sys.modules.get("core.backup")
    if facade is None:
        return default
    candidate = getattr(facade, name, default)
    if callable(candidate) and candidate is not default:
        return candidate
    return default


def cleanup_applied_pending_restore_files(pending_file: str) -> int:
    """Remove already-applied pending restore metadata left after a locked delete."""
    applied_file = f"{pending_file}.applied"
    if not os.path.exists(applied_file):
        return 0
    try:
        os.remove(applied_file)
        logger.info("잔여 pending restore applied 파일 정리: %s", applied_file)
        return 1
    except OSError as e:
        logger.warning("잔여 pending restore applied 파일 정리 실패: %s", e)
        return 0
def _validate_restore_sources(
    backup_path: str,
    config_file: str,
    db_file: str,
    restore_db: bool,
    context_label: str,
) -> Optional[Dict[str, str]]:
    verification = verify_backup_payload(
        backup_path=backup_path,
        config_file=config_file,
        db_file=db_file,
        require_db=restore_db,
    )
    if not verification.get("backup_exists", False):
        logger.error("%s validation failed: backup path is invalid (%s)", context_label, backup_path)
        return None
    if not verification.get("is_restorable", False):
        logger.error(
            "%s validation failed: %s",
            context_label,
            verification.get("restore_error", "backup is not restorable"),
        )
        return None

    return {
        "config_backup": str(verification.get("config_backup", "")),
        "db_backup": str(verification.get("db_backup", "")),
    }
def _apply_restore_sidecars(src_db_path: str, dst_db_path: str) -> None:
    atomic_copy_replace = _facade_override("_atomic_copy_replace", _atomic_copy_replace)
    for suffix in ("-wal", "-shm"):
        src_sidecar = f"{src_db_path}{suffix}"
        dst_sidecar = f"{dst_db_path}{suffix}"
        if os.path.exists(src_sidecar):
            atomic_copy_replace(src_sidecar, dst_sidecar)
        elif os.path.exists(dst_sidecar):
            os.remove(dst_sidecar)
def _apply_restore_from_backup(
    backup_path: str,
    config_file: str,
    db_file: str,
    restore_db: bool,
    context_label: str,
) -> bool:
    validated = _validate_restore_sources(
        backup_path=backup_path,
        config_file=config_file,
        db_file=db_file,
        restore_db=restore_db,
        context_label=context_label,
    )
    if validated is None:
        return False

    rollback_targets = [config_file]
    if restore_db:
        rollback_targets.extend([db_file, f"{db_file}-wal", f"{db_file}-shm"])

    staging_parent = os.path.dirname(os.path.abspath(config_file)) or "."
    try:
        staging_dir = tempfile.mkdtemp(prefix=".restore_stage_", dir=staging_parent)
    except Exception as e:
        logger.error("%s staging failed: %s", context_label, e)
        return False
    try:
        snapshots = _snapshot_files_for_rollback(
            rollback_targets,
            os.path.join(staging_dir, "snapshots"),
        )
        try:
            atomic_copy_replace = _facade_override("_atomic_copy_replace", _atomic_copy_replace)
            atomic_copy_replace(validated["config_backup"], config_file)
            if restore_db:
                atomic_copy_replace(validated["db_backup"], db_file)
                _apply_restore_sidecars(validated["db_backup"], db_file)
        except Exception as apply_error:
            logger.error("%s apply failed, rolling back: %s", context_label, apply_error)
            _rollback_files_from_snapshot(snapshots)
            return False
    except Exception as e:
        logger.error("%s staging failed: %s", context_label, e)
        return False
    finally:
        _cleanup_restore_stage_dir(staging_dir)

    return True
def apply_pending_restore_if_any(
    pending_file: str,
    config_file: str,
    db_file: str,
) -> bool:
    if not os.path.exists(pending_file):
        return False

    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.error("pending restore payload parse failed (file is kept): %s", e)
        return False

    if not isinstance(payload, dict):
        logger.error("pending restore payload is not a JSON object (file is kept)")
        return False

    backup_name = str(payload.get("backup_name", "") or "").strip()
    restore_db = bool(payload.get("restore_db", True))
    requested_backup_dir = str(payload.get("backup_dir", "") or "").strip()
    runtime_backup_dir = os.path.join(
        os.path.dirname(os.path.abspath(config_file)), DEFAULT_BACKUP_DIR
    )

    backup_path = ""
    candidate_dirs = []
    if requested_backup_dir:
        candidate_dirs.append(requested_backup_dir)
    if runtime_backup_dir not in candidate_dirs:
        candidate_dirs.append(runtime_backup_dir)

    for backup_dir in candidate_dirs:
        candidate_path = os.path.join(str(backup_dir), backup_name)
        if os.path.isdir(candidate_path):
            backup_path = candidate_path
            break

    if not backup_name or not backup_path:
        logger.error("pending restore validation failed: backup path is invalid (file is kept)")
        return False

    applied_file = f"{pending_file}.applied"
    try:
        os.replace(pending_file, applied_file)
    except OSError as rename_err:
        logger.warning("pending restore archive failed before apply: %s", rename_err)
        return False

    apply_restore_from_backup = _facade_override(
        "_apply_restore_from_backup",
        _apply_restore_from_backup,
    )
    restored = apply_restore_from_backup(
        backup_path=backup_path,
        config_file=config_file,
        db_file=db_file,
        restore_db=restore_db,
        context_label="pending restore",
    )
    if not restored:
        try:
            os.replace(applied_file, pending_file)
        except OSError as rollback_err:
            logger.warning("pending restore archive rollback failed: %s", rollback_err)
        return False

    try:
        os.remove(applied_file)
    except OSError as remove_err:
        logger.warning("restore applied but archived pending file delete failed: %s", remove_err)

    return True
