import datetime
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import traceback
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

PENDING_RESTORE_FILENAME = "pending_restore.json"


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
        shutil.rmtree(staging_dir)
    except FileNotFoundError:
        return
    except Exception as cleanup_error:
        logger.warning("restore staging cleanup failed for %s: %s", staging_dir, cleanup_error)


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
                shutil.rmtree(temp_dir)
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


def _apply_restore_sidecars(src_db_path: str, dst_db_path: str) -> None:
    for suffix in ("-wal", "-shm"):
        src_sidecar = f"{src_db_path}{suffix}"
        dst_sidecar = f"{dst_db_path}{suffix}"
        if os.path.exists(src_sidecar):
            _atomic_copy_replace(src_sidecar, dst_sidecar)
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
            _atomic_copy_replace(validated["config_backup"], config_file)
            if restore_db:
                _atomic_copy_replace(validated["db_backup"], db_file)
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


class AutoBackup:
    """설정 및 데이터베이스 자동 백업"""

    BACKUP_DIR: str = "backups"
    MAX_AUTO_BACKUPS: int = 5
    MAX_MANUAL_BACKUPS: int = 20

    def __init__(
        self,
        config_file: str,
        db_file: str,
        app_version: str = "unknown",
        pending_restore_file: Optional[str] = None,
    ):
        self.config_file = config_file
        self.db_file = db_file
        self.app_version = app_version
        self.backup_dir = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), self.BACKUP_DIR
        )
        self.pending_restore_file = pending_restore_file or os.path.join(
            os.path.dirname(os.path.abspath(config_file)), PENDING_RESTORE_FILENAME
        )
        self.last_create_error = ""
        self._ensure_backup_dir()

    def _ensure_backup_dir(self):
        if not os.path.exists(self.backup_dir):
            try:
                os.makedirs(self.backup_dir)
                logger.info(f"백업 디렉토리 생성: {self.backup_dir}")
            except Exception as e:
                logger.error(f"백업 디렉토리 생성 실패: {e}")

    def _backup_info_path(self, backup_path: str) -> str:
        return os.path.join(str(backup_path), "backup_info.json")

    def _write_backup_info(self, backup_path: str, info: Dict[str, Any]) -> None:
        _write_json_atomic(self._backup_info_path(backup_path), info)

    def validate_create_backup_prerequisites(
        self,
        include_db: bool = True,
    ) -> tuple[bool, str]:
        if not os.path.exists(self.config_file):
            return False, "설정 파일이 없어 복원 가능한 백업을 만들 수 없습니다."
        if include_db and not os.path.exists(self.db_file):
            return False, "데이터베이스 파일이 없어 '데이터베이스 포함' 백업을 만들 수 없습니다."
        return True, ""

    def create_backup(self, include_db: bool = True, trigger: str = "manual") -> Optional[str]:
        try:
            self.last_create_error = ""
            normalized_trigger = str(trigger or "manual").strip().lower()
            if normalized_trigger not in {"auto", "manual"}:
                normalized_trigger = "manual"
            ok, reason = self.validate_create_backup_prerequisites(include_db=include_db)
            if not ok:
                logger.warning(
                    "백업 생성 건너뜀: trigger=%s, include_db=%s, reason=%s",
                    normalized_trigger,
                    int(bool(include_db)),
                    reason,
                )
                self.last_create_error = reason
                return None

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            base_backup_name = f"backup_{timestamp}"
            backup_name = ""
            backup_path = ""
            for attempt in range(10):
                suffix = "" if attempt == 0 else f"_{attempt:02d}"
                candidate_name = f"{base_backup_name}{suffix}"
                candidate_path = os.path.join(self.backup_dir, candidate_name)
                try:
                    os.makedirs(candidate_path, exist_ok=False)
                    backup_name = candidate_name
                    backup_path = candidate_path
                    break
                except FileExistsError:
                    continue
            if not backup_path:
                logger.error("백업 폴더 생성 실패: 이름 충돌 재시도 한도 초과")
                return None

            actual_include_db = False
            shutil.copy2(self.config_file, os.path.join(backup_path, os.path.basename(self.config_file)))

            if include_db:
                backup_db = os.path.join(backup_path, os.path.basename(self.db_file))
                if not self._snapshot_db(backup_db):
                    self._copy_db_with_sidecars(backup_db)
                actual_include_db = True

            info = {
                "timestamp": timestamp,
                "app_version": self.app_version,
                "include_db": actual_include_db,
                "trigger": normalized_trigger,
                "created_at": datetime.datetime.now().isoformat(),
            }
            with open(os.path.join(backup_path, "backup_info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2, ensure_ascii=False)

            logger.info(f"백업 생성 완료: {backup_path}")
            verification = verify_backup_payload(
                backup_path=backup_path,
                config_file=self.config_file,
                db_file=self.db_file,
                require_db=actual_include_db,
            )
            info.update(
                {
                    "verification_state": str(verification.get("verification_state", "failed") or "failed"),
                    "verification_error": str(
                        verification.get("verification_error", "")
                        or verification.get("restore_error", "")
                        or verification.get("error", "")
                        or ""
                    ),
                    "is_restorable": bool(verification.get("is_restorable", False)),
                    "restore_error": str(verification.get("restore_error", "") or ""),
                    "is_corrupt": bool(verification.get("is_corrupt", False)),
                    "error": str(verification.get("error", "") or ""),
                }
            )
            self._write_backup_info(backup_path, info)
            if not bool(verification.get("is_restorable", False)):
                self.last_create_error = str(
                    verification.get("verification_error", "")
                    or verification.get("restore_error", "")
                    or verification.get("error", "")
                    or "backup self-verification failed"
                )
                logger.error("Backup self-verification failed: %s", self.last_create_error)
                self._cleanup_old_backups()
                return None

            self._cleanup_old_backups()
            return backup_path
        except Exception as e:
            logger.error(f"백업 생성 실패: {e}")
            self.last_create_error = str(e)
            traceback.print_exc()
            if "backup_path" in locals() and backup_path:
                try:
                    shutil.rmtree(backup_path)
                except Exception as cleanup_error:
                    logger.warning("실패한 백업 폴더 정리 실패: %s", cleanup_error)
            return None

    def _copy_db_with_sidecars(self, dst_db_path: str):
        shutil.copy2(self.db_file, dst_db_path)
        for suffix in ("-wal", "-shm"):
            src_sidecar = f"{self.db_file}{suffix}"
            dst_sidecar = f"{dst_db_path}{suffix}"
            if os.path.exists(src_sidecar):
                shutil.copy2(src_sidecar, dst_sidecar)

    def _snapshot_db(self, dst_db_path: str) -> bool:
        src_conn = None
        dst_conn = None
        try:
            src_conn = sqlite3.connect(self.db_file)
            dst_conn = sqlite3.connect(dst_db_path)
            src_conn.backup(dst_conn)
            dst_conn.commit()
            return True
        except Exception as e:
            logger.warning(
                f"스냅샷 백업 실패, 복사 fallback 사용 (snapshot backup failed, fallback copy path will be used): {e}"
            )
            return False
        finally:
            if dst_conn:
                dst_conn.close()
            if src_conn:
                src_conn.close()

    def schedule_restore(
        self,
        backup_name: str,
        restore_db: bool = True,
        pending_file: Optional[str] = None,
    ) -> bool:
        try:
            target_pending_file = pending_file or self.pending_restore_file
            payload = {
                "backup_name": backup_name,
                "restore_db": bool(restore_db),
                "backup_dir": self.backup_dir,
                "created_at": datetime.datetime.now().isoformat(),
            }
            _write_json_atomic(target_pending_file, payload)
            return True
        except Exception as e:
            logger.error(f"복원 예약 실패 (restore schedule failed): {e}")
            return False

    def _cleanup_old_backups(self):
        try:
            backups = self.get_backup_list()
            manual_backups = [
                backup for backup in backups if str(backup.get("trigger", "manual")).lower() == "manual"
            ]
            auto_backups = [
                backup for backup in backups if str(backup.get("trigger", "manual")).lower() == "auto"
            ]

            if len(manual_backups) > self.MAX_MANUAL_BACKUPS:
                for backup in manual_backups[self.MAX_MANUAL_BACKUPS :]:
                    deleted, error = self.delete_backup(str(backup["name"]))
                    if deleted:
                        logger.info(f"오래된 수동 백업 삭제: {backup['name']}")
                    else:
                        logger.warning(f"오래된 수동 백업 삭제 실패: {backup['name']} ({error})")

            if len(auto_backups) > self.MAX_AUTO_BACKUPS:
                for backup in auto_backups[self.MAX_AUTO_BACKUPS :]:
                    deleted, error = self.delete_backup(str(backup["name"]))
                    if deleted:
                        logger.info(f"오래된 자동 백업 삭제: {backup['name']}")
                    else:
                        logger.warning(f"오래된 자동 백업 삭제 실패: {backup['name']} ({error})")
        except Exception as e:
            logger.error(f"백업 정리 오류: {e}")

    def get_backup_list(self) -> List[Dict]:
        backups: List[Dict[str, Any]] = []
        if not os.path.exists(self.backup_dir):
            return backups

        try:
            backup_names = sorted(os.listdir(self.backup_dir), reverse=True)
        except Exception as e:
            logger.error(f"failed to list backup directory: {e}")
            return backups

        for name in backup_names:
            backup_path = os.path.join(self.backup_dir, name)
            if not os.path.isdir(backup_path):
                continue

            item: Dict[str, Any] = {
                "name": name,
                "path": backup_path,
                "timestamp": "",
                "app_version": self.app_version,
                "include_db": False,
                "trigger": "manual",
                "created_at": "",
                "is_corrupt": False,
                "error": "",
                "is_restorable": False,
                "restore_error": "",
                "verification_state": "pending",
                "verification_error": "",
            }
            info_file = os.path.join(backup_path, "backup_info.json")
            try:
                if not os.path.exists(info_file):
                    raise FileNotFoundError("backup_info.json is missing")

                with open(info_file, "r", encoding="utf-8") as f:
                    raw_info = json.load(f)
                if not isinstance(raw_info, dict):
                    raise ValueError("backup_info.json root is not a JSON object")

                item["timestamp"] = str(raw_info.get("timestamp", "") or "")
                item["app_version"] = str(raw_info.get("app_version", self.app_version) or self.app_version)
                item["include_db"] = bool(raw_info.get("include_db", False))
                trigger = str(raw_info.get("trigger", "manual") or "manual").strip().lower()
                item["trigger"] = trigger if trigger in {"auto", "manual"} else "manual"
                item["created_at"] = str(raw_info.get("created_at", "") or "")
                item["verification_state"] = str(
                    raw_info.get("verification_state", item["verification_state"]) or item["verification_state"]
                ).lower()
                item["verification_error"] = str(
                    raw_info.get("verification_error", item["verification_error"]) or item["verification_error"]
                )
                item["is_restorable"] = bool(
                    raw_info.get(
                        "is_restorable",
                        item["verification_state"] != "failed",
                    )
                )
                item["restore_error"] = str(
                    raw_info.get("restore_error", item["restore_error"]) or item["restore_error"]
                )
                item["is_corrupt"] = bool(raw_info.get("is_corrupt", False))
                item["error"] = str(raw_info.get("error", item["error"]) or item["error"])
            except Exception as item_error:
                item["is_corrupt"] = True
                item["error"] = str(item_error)
                item["is_restorable"] = False
                item["restore_error"] = "백업 메타데이터가 손상되었습니다."
                item["verification_state"] = "failed"
                item["verification_error"] = item["restore_error"]
                logger.warning("corrupt backup metadata detected: %s (%s)", name, item_error)
            else:
                cfg_backup = os.path.join(backup_path, os.path.basename(self.config_file))
                db_backup = os.path.join(backup_path, os.path.basename(self.db_file))
                if item["is_corrupt"]:
                    item["is_restorable"] = False
                    item["verification_state"] = "failed"
                    if not item["restore_error"]:
                        item["restore_error"] = item["error"] or item["verification_error"] or "backup is corrupt"
                    if not item["verification_error"]:
                        item["verification_error"] = item["restore_error"]
                    backups.append(item)
                    continue
                if item["verification_state"] == "failed":
                    item["is_restorable"] = False
                    if not item["restore_error"]:
                        item["restore_error"] = (
                            item["verification_error"]
                            or item["error"]
                            or "backup self-verification failed"
                        )
                    if not item["verification_error"]:
                        item["verification_error"] = item["restore_error"]
                    backups.append(item)
                    continue
                if not os.path.exists(cfg_backup):
                    item["is_restorable"] = False
                    item["restore_error"] = "설정 백업 파일이 없습니다."
                    item["verification_state"] = "failed"
                    item["verification_error"] = item["restore_error"]
                elif item["include_db"] and not os.path.exists(db_backup):
                    item["is_restorable"] = False
                    item["restore_error"] = "데이터베이스 백업 파일이 없습니다."
                    item["verification_state"] = "failed"
                    item["verification_error"] = item["restore_error"]
                else:
                    item["is_restorable"] = True
                    if item["verification_state"] != "ok":
                        item["verification_state"] = "pending"
                        item["verification_error"] = ""
                        item["restore_error"] = ""

            backups.append(item)

        backups.sort(
            key=lambda x: str(x.get("timestamp", "")) or str(x.get("name", "")),
            reverse=True,
        )
        return backups

    def verify_backup_entry(
        self,
        backup_entry: Dict[str, Any],
        *,
        require_db: Optional[bool] = None,
    ) -> Dict[str, Any]:
        verified = dict(backup_entry)
        backup_name = str(verified.get("name") or verified.get("backup_name") or "").strip()
        backup_path = str(verified.get("path") or os.path.join(self.backup_dir, backup_name))
        include_db = bool(verified.get("include_db", False))
        verification = verify_backup_payload(
            backup_path=backup_path,
            config_file=self.config_file,
            db_file=self.db_file,
            require_db=include_db if require_db is None else bool(require_db),
        )
        verified.update(verification)
        verified["name"] = backup_name
        verified["path"] = backup_path
        return verified

    def verify_backup_by_name(
        self,
        backup_name: str,
        *,
        require_db: Optional[bool] = None,
    ) -> Dict[str, Any]:
        backup_name = str(backup_name or "").strip()
        for entry in self.get_backup_list():
            if str(entry.get("name", "")).strip() == backup_name:
                return self.verify_backup_entry(entry, require_db=require_db)

        return self.verify_backup_entry(
            {
                "name": backup_name,
                "backup_name": backup_name,
                "path": os.path.join(self.backup_dir, backup_name),
                "include_db": bool(require_db),
            },
            require_db=require_db,
        )

    def delete_backup(self, backup_name: str) -> tuple[bool, str]:
        backup_name = str(backup_name or "").strip()
        if not backup_name:
            return False, "백업 이름이 비어 있습니다."

        backup_path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(backup_path):
            return False, "삭제할 백업 경로가 존재하지 않습니다."

        try:
            shutil.rmtree(backup_path)
        except Exception as e:
            return False, str(e)

        if os.path.exists(backup_path):
            return False, "백업 디렉터리가 삭제되지 않았습니다."
        return True, ""

    def restore_backup(self, backup_name: str, restore_db: bool = True) -> bool:
        """오프라인 복원용 즉시 복원 API (UI에서는 schedule_restore 사용 권장)."""
        try:
            backup_path = os.path.join(self.backup_dir, backup_name)
            if not os.path.exists(backup_path):
                logger.error(f"백업을 찾을 수 없음: {backup_name}")
                return False
            restored = _apply_restore_from_backup(
                backup_path=backup_path,
                config_file=self.config_file,
                db_file=self.db_file,
                restore_db=bool(restore_db),
                context_label=f"restore_backup({backup_name})",
            )
            if restored:
                logger.info("백업 복원 완료: %s", backup_name)
            return restored
        except Exception as e:
            logger.error(f"백업 복원 실패: {e}")
            traceback.print_exc()
            return False

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
    backup_dir = payload.get("backup_dir") or os.path.join(
        os.path.dirname(os.path.abspath(config_file)), AutoBackup.BACKUP_DIR
    )
    backup_path = os.path.join(str(backup_dir), backup_name)

    if not backup_name or not os.path.isdir(backup_path):
        logger.error("pending restore validation failed: backup path is invalid (file is kept)")
        return False

    restored = _apply_restore_from_backup(
        backup_path=backup_path,
        config_file=config_file,
        db_file=db_file,
        restore_db=restore_db,
        context_label="pending restore",
    )
    if not restored:
        return False

    try:
        os.remove(pending_file)
    except OSError as remove_err:
        logger.warning("restore applied but pending file delete failed: %s", remove_err)

    return True
