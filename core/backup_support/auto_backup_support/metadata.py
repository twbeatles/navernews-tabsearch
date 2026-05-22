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


class _AutoBackupMetadataMixin:
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

    def _read_backup_info(self, backup_path: str) -> Dict[str, Any]:
        info_path = self._backup_info_path(backup_path)
        with open(info_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("backup_info.json root is not a JSON object")
        return payload

    def _detect_backup_contains_db(self, backup_path: str) -> bool:
        db_backup = os.path.join(backup_path, os.path.basename(self.db_file))
        return os.path.exists(db_backup)

    def _resolve_backup_include_db(
        self,
        backup_entry: Dict[str, Any],
        *,
        fallback_to_files: bool = True,
    ) -> bool:
        include_db = backup_entry.get("include_db")
        if isinstance(include_db, bool):
            return include_db
        if not fallback_to_files:
            return False
        backup_path = str(
            backup_entry.get("path")
            or os.path.join(self.backup_dir, str(backup_entry.get("name") or backup_entry.get("backup_name") or ""))
        )
        if not backup_path:
            return False
        return self._detect_backup_contains_db(backup_path)

    def _verification_metadata_from_result(
        self,
        verification: Dict[str, Any],
        *,
        include_db: bool,
    ) -> Dict[str, Any]:
        return {
            "include_db": bool(include_db),
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

    def persist_backup_verification(
        self,
        backup_entry: Dict[str, Any],
        verification: Dict[str, Any],
        *,
        include_db: Optional[bool] = None,
    ) -> Dict[str, Any]:
        persisted = dict(verification)
        backup_name = str(
            persisted.get("name") or persisted.get("backup_name") or backup_entry.get("name") or backup_entry.get("backup_name") or ""
        ).strip()
        backup_path = str(
            persisted.get("path") or backup_entry.get("path") or os.path.join(self.backup_dir, backup_name)
        )
        resolved_include_db = (
            bool(include_db)
            if include_db is not None
            else self._resolve_backup_include_db({**backup_entry, **persisted}, fallback_to_files=True)
        )
        metadata = self._verification_metadata_from_result(persisted, include_db=resolved_include_db)
        persisted["name"] = backup_name
        persisted["backup_name"] = backup_name
        persisted["path"] = backup_path
        persisted.update(metadata)
        if not os.path.isdir(backup_path):
            return persisted
        try:
            info = self._read_backup_info(backup_path)
        except Exception:
            info = {}
        info["timestamp"] = str(
            info.get("timestamp")
            or persisted.get("timestamp")
            or ""
        )
        info["app_version"] = str(
            info.get("app_version")
            or persisted.get("app_version")
            or self.app_version
        )
        info["trigger"] = str(info.get("trigger") or persisted.get("trigger") or "manual")
        info["created_at"] = str(
            info.get("created_at")
            or persisted.get("created_at")
            or ""
        )
        info.update(metadata)
        self._write_backup_info(backup_path, info)
        persisted["timestamp"] = info["timestamp"]
        persisted["app_version"] = info["app_version"]
        persisted["trigger"] = info["trigger"]
        persisted["created_at"] = info["created_at"]
        return persisted

    def validate_create_backup_prerequisites(
        self,
        include_db: bool = True,
    ) -> tuple[bool, str]:
        if not os.path.exists(self.config_file):
            return False, "설정 파일이 없어 복원 가능한 백업을 만들 수 없습니다."
        if include_db and not os.path.exists(self.db_file):
            return False, "데이터베이스 파일이 없어 '데이터베이스 포함' 백업을 만들 수 없습니다."
        return True, ""
