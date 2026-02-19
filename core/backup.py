import datetime
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import traceback
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)

PENDING_RESTORE_FILENAME = "pending_restore.json"


def _write_json_atomic(path: str, payload: Dict) -> None:
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


class AutoBackup:
    """설정 및 데이터베이스 자동 백업"""

    BACKUP_DIR = "backups"
    MAX_BACKUPS = 5

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

    def create_backup(self, include_db: bool = True) -> Optional[str]:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            backup_path = os.path.join(self.backup_dir, backup_name)
            os.makedirs(backup_path, exist_ok=True)

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
            if len(backups) > self.MAX_BACKUPS:
                backups_to_delete = backups[self.MAX_BACKUPS :]
                for backup in backups_to_delete:
                    backup_path = os.path.join(self.backup_dir, backup["name"])
                    shutil.rmtree(backup_path, ignore_errors=True)
                    logger.info(f"오래된 백업 삭제: {backup['name']}")
        except Exception as e:
            logger.error(f"백업 정리 오류: {e}")

    def get_backup_list(self) -> List[Dict]:
        backups = []
        try:
            if not os.path.exists(self.backup_dir):
                return backups

            for name in os.listdir(self.backup_dir):
                backup_path = os.path.join(self.backup_dir, name)
                if os.path.isdir(backup_path):
                    info_file = os.path.join(backup_path, "backup_info.json")
                    if os.path.exists(info_file):
                        with open(info_file, "r", encoding="utf-8") as f:
                            info = json.load(f)
                        info["name"] = name
                        info["path"] = backup_path
                        backups.append(info)

            backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        except Exception as e:
            logger.error(f"백업 목록 조회 오류: {e}")

        return backups

    def restore_backup(self, backup_name: str, restore_db: bool = True) -> bool:
        """오프라인 복원용 즉시 복원 API (UI에서는 schedule_restore 사용 권장)."""
        try:
            backup_path = os.path.join(self.backup_dir, backup_name)
            if not os.path.exists(backup_path):
                logger.error(f"백업을 찾을 수 없음: {backup_name}")
                return False

            config_backup = os.path.join(backup_path, os.path.basename(self.config_file))
            if os.path.exists(config_backup):
                shutil.copy2(config_backup, self.config_file)

            if restore_db:
                db_backup = os.path.join(backup_path, os.path.basename(self.db_file))
                if os.path.exists(db_backup):
                    shutil.copy2(db_backup, self.db_file)

            logger.info(f"백업 복원 완료: {backup_name}")
            return True
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

        backup_name = payload.get("backup_name", "")
        restore_db = bool(payload.get("restore_db", True))
        backup_dir = payload.get("backup_dir") or os.path.join(
            os.path.dirname(os.path.abspath(config_file)), AutoBackup.BACKUP_DIR
        )
        backup_path = os.path.join(backup_dir, backup_name)
        if not backup_name or not os.path.isdir(backup_path):
            return False

        cfg_backup = os.path.join(backup_path, os.path.basename(config_file))
        if os.path.exists(cfg_backup):
            shutil.copy2(cfg_backup, config_file)

        if restore_db:
            db_backup = os.path.join(backup_path, os.path.basename(db_file))
            if os.path.exists(db_backup):
                shutil.copy2(db_backup, db_file)

            for suffix in ("-wal", "-shm"):
                src_sidecar = f"{db_backup}{suffix}"
                dst_sidecar = f"{db_file}{suffix}"
                if os.path.exists(src_sidecar):
                    shutil.copy2(src_sidecar, dst_sidecar)
                elif os.path.exists(dst_sidecar):
                    os.remove(dst_sidecar)

        os.remove(pending_file)
        return True
    except Exception as e:
        logger.error(f"예약 복원 적용 실패 (apply_pending_restore_if_any failed): {e}")
        return False
