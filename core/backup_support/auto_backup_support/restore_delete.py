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


class _AutoBackupRestoreDeleteMixin:
    def schedule_restore(
        self,
        backup_name: str,
        restore_db: bool = True,
        pending_file: Optional[str] = None,
    ) -> bool:
        try:
            target_pending_file = pending_file or self.pending_restore_file
            backup_path = os.path.join(self.backup_dir, str(backup_name or ""))
            if not backup_name or not os.path.isdir(backup_path):
                logger.error("복원 예약 실패: 백업 디렉터리를 찾을 수 없습니다 (%s)", backup_path)
                return False
            try:
                os.listdir(backup_path)
            except OSError as access_error:
                logger.error("복원 예약 실패: 백업 디렉터리에 접근할 수 없습니다 (%s)", access_error)
                return False
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

    def delete_corrupt_backups(self) -> tuple[int, List[str]]:
        deleted_count = 0
        errors: List[str] = []
        for backup in self.get_backup_list():
            if not bool(backup.get("is_corrupt", False)):
                continue
            backup_name = str(backup.get("name") or backup.get("backup_name") or "")
            if not backup_name:
                continue
            deleted, error = self.delete_backup(backup_name)
            if deleted:
                deleted_count += 1
            elif error:
                errors.append(f"{backup_name}: {error}")
        return deleted_count, errors

    def delete_backup(self, backup_name: str) -> tuple[bool, str]:
        backup_name = str(backup_name or "").strip()
        if not backup_name:
            return False, "백업 이름이 비어 있습니다."

        backup_path = os.path.join(self.backup_dir, backup_name)
        if not os.path.exists(backup_path):
            return False, "삭제할 백업 경로가 존재하지 않습니다."

        try:
            _rmtree_force(backup_path)
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
