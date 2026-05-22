# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import sqlite3
import traceback
from typing import Any, Dict, List, Optional

from core.backup_support.constants import DEFAULT_BACKUP_DIR, PENDING_RESTORE_FILENAME
from core.backup_support.fs import _rmtree_force, _write_json_atomic
from core.backup_support.restore import _apply_restore_from_backup
from core.backup_support.validation import verify_backup_payload

logger = logging.getLogger(__name__)


class _AutoBackupCreateMixin:
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
            self._write_backup_info(backup_path, info)

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
                    "last_verified_at": datetime.datetime.now().isoformat(),
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
                    _rmtree_force(backup_path)
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
