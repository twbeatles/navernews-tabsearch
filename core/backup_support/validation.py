import json
import os
import shutil
import sqlite3
import tempfile
from typing import Any, Dict

from core.backup_support.fs import _rmtree_force

def _validate_sidecar_policy(db_backup: str) -> str:
    wal_exists = os.path.exists(f"{db_backup}-wal")
    shm_exists = os.path.exists(f"{db_backup}-shm")
    if shm_exists and not wal_exists:
        return "데이터베이스 백업 sidecar 정책이 일관되지 않습니다. (-shm만 존재)"
    return ""
def _validate_config_backup_payload(cfg_backup: str) -> str:
    try:
        with open(cfg_backup, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return "설정 백업 파일이 JSON object가 아닙니다."
    except Exception as e:
        return f"설정 백업 파일이 손상되었습니다. ({e})"
    return ""
def _validate_sqlite_backup(db_backup: str) -> str:
    conn = None
    temp_dir = None
    temp_db_path = db_backup
    try:
        temp_dir = tempfile.mkdtemp(prefix=".backup_verify_")
        temp_db_path = os.path.join(temp_dir, os.path.basename(db_backup))
        shutil.copy2(db_backup, temp_db_path)
        for suffix in ("-wal", "-shm"):
            src_sidecar = f"{db_backup}{suffix}"
            if os.path.exists(src_sidecar):
                shutil.copy2(src_sidecar, f"{temp_db_path}{suffix}")

        conn = sqlite3.connect(temp_db_path)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            return f"데이터베이스 무결성 검사 실패: {row[0] if row else 'unknown'}"
        return ""
    except Exception as e:
        return f"데이터베이스 백업 파일이 손상되었습니다. ({e})"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if temp_dir is not None:
            try:
                _rmtree_force(temp_dir)
            except Exception:
                pass
def verify_backup_payload(
    backup_path: str,
    config_file: str,
    db_file: str,
    require_db: bool = False,
) -> Dict[str, Any]:
    cfg_backup = os.path.join(backup_path, os.path.basename(config_file))
    db_backup = os.path.join(backup_path, os.path.basename(db_file))
    result: Dict[str, Any] = {
        "backup_exists": os.path.isdir(backup_path),
        "config_backup": cfg_backup,
        "db_backup": db_backup,
        "is_corrupt": False,
        "error": "",
        "is_restorable": False,
        "restore_error": "",
        "verification_state": "failed",
        "verification_error": "",
    }

    if not result["backup_exists"]:
        result["restore_error"] = "백업 경로가 존재하지 않습니다."
        result["verification_error"] = result["restore_error"]
        return result

    if not os.path.exists(cfg_backup):
        result["restore_error"] = "설정 백업 파일이 없습니다."
        result["verification_error"] = result["restore_error"]
        return result

    config_error = _validate_config_backup_payload(cfg_backup)
    if config_error:
        result["is_corrupt"] = True
        result["error"] = config_error
        result["restore_error"] = config_error
        result["verification_error"] = config_error
        return result

    if require_db:
        if not os.path.exists(db_backup):
            result["restore_error"] = "데이터베이스 백업 파일이 없습니다."
            result["verification_error"] = result["restore_error"]
            return result

        sidecar_error = _validate_sidecar_policy(db_backup)
        if sidecar_error:
            result["is_corrupt"] = True
            result["error"] = sidecar_error
            result["restore_error"] = sidecar_error
            result["verification_error"] = sidecar_error
            return result

        db_error = _validate_sqlite_backup(db_backup)
        if db_error:
            result["is_corrupt"] = True
            result["error"] = db_error
            result["restore_error"] = db_error
            result["verification_error"] = db_error
            return result

    result["is_restorable"] = True
    result["verification_state"] = "ok"
    result["verification_error"] = ""
    return result
