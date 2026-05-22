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


class _AutoBackupListingMixin:
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
                "include_db": None,
                "resolved_include_db": False,
                "trigger": "manual",
                "created_at": "",
                "is_corrupt": False,
                "error": "",
                "is_restorable": False,
                "restore_error": "",
                "verification_state": "pending",
                "verification_error": "",
                "last_verified_at": "",
            }
            info_file = os.path.join(backup_path, "backup_info.json")
            try:
                if not os.path.exists(info_file):
                    raise FileNotFoundError("backup_info.json is missing")

                raw_info = self._read_backup_info(backup_path)

                item["timestamp"] = str(raw_info.get("timestamp", "") or "")
                item["app_version"] = str(raw_info.get("app_version", self.app_version) or self.app_version)
                include_db_raw = raw_info.get("include_db")
                item["include_db"] = include_db_raw if isinstance(include_db_raw, bool) else None
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
                item["last_verified_at"] = str(raw_info.get("last_verified_at", "") or "")
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
                resolved_include_db = self._resolve_backup_include_db(item, fallback_to_files=True)
                item["resolved_include_db"] = resolved_include_db
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
                elif resolved_include_db and not os.path.exists(db_backup):
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
        persist: bool = False,
    ) -> Dict[str, Any]:
        verified = dict(backup_entry)
        backup_name = str(verified.get("name") or verified.get("backup_name") or "").strip()
        backup_path = str(verified.get("path") or os.path.join(self.backup_dir, backup_name))
        include_db = (
            self._resolve_backup_include_db(verified, fallback_to_files=True)
            if require_db is None
            else bool(require_db)
        )
        verification = verify_backup_payload(
            backup_path=backup_path,
            config_file=self.config_file,
            db_file=self.db_file,
            require_db=include_db,
        )
        verified.update(verification)
        verified["name"] = backup_name
        verified["path"] = backup_path
        verified["backup_name"] = backup_name
        verified["include_db"] = include_db
        verified["resolved_include_db"] = include_db
        if persist:
            return self.persist_backup_verification(backup_entry, verified, include_db=include_db)
        return verified

    def verify_backup_by_name(
        self,
        backup_name: str,
        *,
        require_db: Optional[bool] = None,
        persist: bool = False,
    ) -> Dict[str, Any]:
        backup_name = str(backup_name or "").strip()
        for entry in self.get_backup_list():
            if str(entry.get("name", "")).strip() == backup_name:
                return self.verify_backup_entry(entry, require_db=require_db, persist=persist)

        return self.verify_backup_entry(
            {
                "name": backup_name,
                "backup_name": backup_name,
                "path": os.path.join(self.backup_dir, backup_name),
                "include_db": require_db if isinstance(require_db, bool) else None,
            },
            require_db=require_db,
            persist=persist,
        )
