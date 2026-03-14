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
                _atomic_copy_replace(snapshot, target)
            elif os.path.exists(target):
                os.remove(target)
        except Exception as rollback_error:
            logger.error("rollback failed for %s: %s", target, rollback_error)


def _validate_restore_sources(
    backup_path: str,
    config_file: str,
    db_file: str,
    restore_db: bool,
    context_label: str,
) -> Optional[Dict[str, str]]:
    if not os.path.isdir(backup_path):
        logger.error("%s validation failed: backup path is invalid (%s)", context_label, backup_path)
        return None

    cfg_backup = os.path.join(backup_path, os.path.basename(config_file))
    if not os.path.exists(cfg_backup):
        logger.error("%s validation failed: config backup missing (%s)", context_label, cfg_backup)
        return None

    db_backup = os.path.join(backup_path, os.path.basename(db_file))
    if restore_db and not os.path.exists(db_backup):
        logger.error(
            "%s validation failed: restore_db=true but DB backup missing (%s)",
            context_label,
            db_backup,
        )
        return None

    return {
        "config_backup": cfg_backup,
        "db_backup": db_backup,
    }


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
        with tempfile.TemporaryDirectory(prefix=".restore_stage_", dir=staging_parent) as staging_dir:
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
        self._ensure_backup_dir()

    def _ensure_backup_dir(self):
        if not os.path.exists(self.backup_dir):
            try:
                os.makedirs(self.backup_dir)
                logger.info(f"백업 디렉토리 생성: {self.backup_dir}")
            except Exception as e:
                logger.error(f"백업 디렉토리 생성 실패: {e}")

    def create_backup(self, include_db: bool = True, trigger: str = "manual") -> Optional[str]:
        try:
            normalized_trigger = str(trigger or "manual").strip().lower()
            if normalized_trigger not in {"auto", "manual"}:
                normalized_trigger = "manual"
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

            if os.path.exists(self.config_file):
                shutil.copy2(self.config_file, os.path.join(backup_path, os.path.basename(self.config_file)))

            if include_db and os.path.exists(self.db_file):
                backup_db = os.path.join(backup_path, os.path.basename(self.db_file))
                if not self._snapshot_db(backup_db):
                    self._copy_db_with_sidecars(backup_db)

            info = {
                "timestamp": timestamp,
                "app_version": self.app_version,
                "include_db": include_db,
                "trigger": normalized_trigger,
                "created_at": datetime.datetime.now().isoformat(),
            }
            with open(os.path.join(backup_path, "backup_info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2, ensure_ascii=False)

            logger.info(f"백업 생성 완료: {backup_path}")
            self._cleanup_old_backups()
            return backup_path
        except Exception as e:
            logger.error(f"백업 생성 실패: {e}")
            traceback.print_exc()
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
                    backup_path = os.path.join(self.backup_dir, backup["name"])
                    shutil.rmtree(backup_path, ignore_errors=True)
                    logger.info(f"오래된 수동 백업 삭제: {backup['name']}")

            if len(auto_backups) > self.MAX_AUTO_BACKUPS:
                for backup in auto_backups[self.MAX_AUTO_BACKUPS :]:
                    backup_path = os.path.join(self.backup_dir, backup["name"])
                    shutil.rmtree(backup_path, ignore_errors=True)
                    logger.info(f"오래된 자동 백업 삭제: {backup['name']}")
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
            except Exception as item_error:
                item["is_corrupt"] = True
                item["error"] = str(item_error)
                logger.warning("corrupt backup metadata detected: %s (%s)", name, item_error)

            backups.append(item)

        backups.sort(
            key=lambda x: str(x.get("timestamp", "")) or str(x.get("name", "")),
            reverse=True,
        )
        return backups

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
