from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from core.cloud_sync_support.models import (
    DB_SNAPSHOT_NAME,
    INVALID_SNAPSHOT_DIR,
    MANIFEST_NAME,
    MAX_SNAPSHOT_DB_BYTES,
    MAX_SNAPSHOT_JSON_BYTES,
    MAX_SNAPSHOT_ZIP_BYTES,
    SANITIZED_APP_SETTING_KEYS,
    SANITIZED_ROOT_KEYS,
    SETTINGS_NAME,
    SNAPSHOT_FORMAT_VERSION,
    SNAPSHOT_PREFIX,
    SNAPSHOT_SUFFIX,
    CloudSnapshot,
    CloudSnapshotValidationError,
    CloudSyncError,
)
from core.cloud_sync_support.path_policy import resolve_cloud_sync_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_snapshot_token(value: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "").strip())
    return token.strip("._-") or "snapshot"


def _atomic_write_json(path: str, payload: Mapping[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".cloud_sync_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _ensure_size_limit(label: str, size_bytes: int, max_bytes: int) -> None:
    if int(size_bytes or 0) > int(max_bytes):
        raise CloudSnapshotValidationError(
            f"{label} exceeds size limit ({size_bytes} > {max_bytes} bytes)"
        )


def _snapshot_member_info(zf: zipfile.ZipFile, member: str) -> zipfile.ZipInfo:
    try:
        return zf.getinfo(member)
    except KeyError as exc:
        raise CloudSnapshotValidationError(
            f"snapshot member is missing: {member}"
        ) from exc


def _validate_snapshot_zip_size(zip_path: str) -> None:
    if not os.path.exists(zip_path):
        raise CloudSyncError(f"snapshot does not exist: {zip_path}")
    _ensure_size_limit(
        "snapshot zip", os.path.getsize(zip_path), MAX_SNAPSHOT_ZIP_BYTES
    )


def quarantine_invalid_snapshot(zip_path: str, reason: str = "") -> str:
    source = os.path.abspath(str(zip_path or ""))
    if not source or not os.path.exists(source):
        return ""
    root = os.path.dirname(source) or "."
    invalid_dir = os.path.join(root, INVALID_SNAPSHOT_DIR)
    os.makedirs(invalid_dir, exist_ok=True)
    base_name = os.path.basename(source)
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = os.path.join(invalid_dir, f"{base_name}.{token}.invalid")
    counter = 1
    while os.path.exists(target):
        target = os.path.join(invalid_dir, f"{base_name}.{token}.{counter}.invalid")
        counter += 1
    try:
        shutil.move(source, target)
        metadata = {
            "original_name": base_name,
            "reason": str(reason or ""),
            "quarantined_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
        _atomic_write_json(target + ".metadata.json", metadata)
        if reason:
            with open(
                target + ".reason.txt", "w", encoding="utf-8", newline="\n"
            ) as handle:
                handle.write(str(reason))
                handle.write("\n")
        return target
    except OSError:
        return ""


def _quarantine_entry_path(sync_dir: str, entry_name: str) -> str:
    root = resolve_cloud_sync_dir(sync_dir)
    name = str(entry_name or "")
    if not name or os.path.basename(name) != name:
        raise CloudSyncError("quarantine entry must be a single file name")
    invalid_dir = os.path.abspath(os.path.join(root, INVALID_SNAPSHOT_DIR))
    path = os.path.abspath(os.path.join(invalid_dir, name))
    if os.path.commonpath([invalid_dir, path]) != invalid_dir:
        raise CloudSyncError("quarantine entry escapes the invalid directory")
    return path


def _read_quarantine_metadata(path: str) -> Dict[str, Any]:
    metadata_path = path + ".metadata.json"
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return dict(payload)
    except (OSError, ValueError, TypeError):
        pass
    reason = ""
    try:
        with open(path + ".reason.txt", "r", encoding="utf-8") as handle:
            reason = handle.read().strip()
    except OSError:
        pass
    base_name = os.path.basename(path)
    original_name = base_name.split(".", 1)[0]
    if ".zip." in base_name:
        original_name = base_name.split(".zip.", 1)[0] + ".zip"
    return {"original_name": original_name, "reason": reason, "quarantined_at": ""}


def list_quarantined_snapshots(sync_dir: str) -> List[Dict[str, Any]]:
    root = resolve_cloud_sync_dir(sync_dir, allow_empty=True)
    invalid_dir = os.path.join(root, INVALID_SNAPSHOT_DIR) if root else ""
    if not invalid_dir or not os.path.isdir(invalid_dir):
        return []
    entries: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(invalid_dir)):
        if not name.endswith(".invalid"):
            continue
        path = _quarantine_entry_path(root, name)
        if not os.path.isfile(path):
            continue
        metadata = _read_quarantine_metadata(path)
        entries.append(
            {
                "name": name,
                "path": path,
                "original_name": str(metadata.get("original_name", "") or ""),
                "reason": str(metadata.get("reason", "") or ""),
                "quarantined_at": str(metadata.get("quarantined_at", "") or ""),
            }
        )
    return entries


def revalidate_quarantined_snapshot(sync_dir: str, entry_name: str) -> Dict[str, Any]:
    path = _quarantine_entry_path(sync_dir, entry_name)
    if not os.path.isfile(path):
        raise CloudSyncError("quarantined snapshot does not exist")
    try:
        with tempfile.TemporaryDirectory(
            prefix="news_cloud_revalidate_"
        ) as staging_dir:
            manifest = read_snapshot_manifest(path)
            extract_snapshot(path, staging_dir)
        return {"valid": True, "manifest": manifest, "reason": ""}
    except CloudSnapshotValidationError as exc:
        return {"valid": False, "manifest": {}, "reason": str(exc)}


def restore_quarantined_snapshot(sync_dir: str, entry_name: str) -> str:
    root = resolve_cloud_sync_dir(sync_dir)
    path = _quarantine_entry_path(root, entry_name)
    validation = revalidate_quarantined_snapshot(root, entry_name)
    if not bool(validation.get("valid")):
        raise CloudSnapshotValidationError(
            str(validation.get("reason") or "snapshot is still invalid")
        )
    metadata = _read_quarantine_metadata(path)
    original_name = str(metadata.get("original_name", "") or "").strip()
    if not original_name or os.path.basename(original_name) != original_name:
        raise CloudSyncError("quarantine metadata has an invalid original name")
    target = os.path.abspath(os.path.join(root, original_name))
    if os.path.commonpath([os.path.abspath(root), target]) != os.path.abspath(root):
        raise CloudSyncError("restore target escapes the cloud sync directory")
    if os.path.exists(target):
        raise CloudSyncError(f"restore target already exists: {original_name}")
    os.replace(path, target)
    for suffix in (".reason.txt", ".metadata.json"):
        sidecar = path + suffix
        if os.path.exists(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass
    return target


def delete_quarantined_snapshot(sync_dir: str, entry_name: str) -> bool:
    path = _quarantine_entry_path(sync_dir, entry_name)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    for suffix in (".reason.txt", ".metadata.json"):
        sidecar = path + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)
    return True


def sanitize_config_for_cloud(config: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(dict(config))
    for key in SANITIZED_ROOT_KEYS:
        sanitized.pop(key, None)
    app_settings = sanitized.get("app_settings")
    if isinstance(app_settings, dict):
        for key in SANITIZED_APP_SETTING_KEYS:
            app_settings.pop(key, None)
    return sanitized


def _snapshot_sqlite_db(src_db_path: str, dst_db_path: str) -> None:
    if not os.path.exists(src_db_path):
        raise CloudSyncError(f"database file does not exist: {src_db_path}")
    src_conn: Optional[sqlite3.Connection] = None
    dst_conn: Optional[sqlite3.Connection] = None
    try:
        src_conn = sqlite3.connect(src_db_path, timeout=10.0)
        dst_conn = sqlite3.connect(dst_db_path, timeout=10.0)
        src_conn.backup(dst_conn)
        dst_conn.commit()
    except Exception as exc:
        raise CloudSyncError(f"database snapshot failed: {exc}") from exc
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()


def _verify_sqlite_db(db_path: str) -> None:
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise CloudSnapshotValidationError(
                f"snapshot integrity_check failed: {row[0] if row else 'unknown'}"
            )
        news_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'news'"
        ).fetchone()
        if news_table is None:
            raise CloudSnapshotValidationError(
                "snapshot database does not contain news table"
            )
    except CloudSnapshotValidationError:
        raise
    except Exception as exc:
        raise CloudSnapshotValidationError(
            f"snapshot database is unreadable: {exc}"
        ) from exc
    finally:
        if conn is not None:
            conn.close()


def create_cloud_snapshot(
    *,
    sync_dir: str,
    config: Mapping[str, Any],
    db_file: str,
    machine_id: str,
    app_version: str,
) -> CloudSnapshot:
    target_dir = resolve_cloud_sync_dir(sync_dir)
    os.makedirs(target_dir, exist_ok=True)

    created_at = _utc_now_iso()
    snapshot_id = _safe_snapshot_token(
        f"{machine_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    )
    filename = f"{SNAPSHOT_PREFIX}{snapshot_id}{SNAPSHOT_SUFFIX}"
    target_path = os.path.join(target_dir, filename)
    temp_zip_path = os.path.join(target_dir, f".{filename}.tmp")

    manifest = {
        "format": "navernews-tabsearch-cloud-snapshot",
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "machine_id": str(machine_id or ""),
        "created_at": created_at,
        "app_version": str(app_version or ""),
        "settings_file": SETTINGS_NAME,
        "db_file": DB_SNAPSHOT_NAME,
    }
    sanitized_config = sanitize_config_for_cloud(config)

    with tempfile.TemporaryDirectory(prefix="news_cloud_sync_") as staging_dir:
        staging_db = os.path.join(staging_dir, DB_SNAPSHOT_NAME)
        _snapshot_sqlite_db(db_file, staging_db)
        _verify_sqlite_db(staging_db)
        _ensure_size_limit(
            "snapshot database", os.path.getsize(staging_db), MAX_SNAPSHOT_DB_BYTES
        )
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode(
            "utf-8"
        )
        settings_bytes = json.dumps(
            sanitized_config, ensure_ascii=False, indent=2
        ).encode("utf-8")
        _ensure_size_limit(
            "snapshot manifest", len(manifest_bytes), MAX_SNAPSHOT_JSON_BYTES
        )
        _ensure_size_limit(
            "snapshot settings", len(settings_bytes), MAX_SNAPSHOT_JSON_BYTES
        )

        try:
            with zipfile.ZipFile(
                temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                zf.writestr(MANIFEST_NAME, manifest_bytes)
                zf.writestr(SETTINGS_NAME, settings_bytes)
                zf.write(staging_db, DB_SNAPSHOT_NAME)
            _ensure_size_limit(
                "snapshot zip", os.path.getsize(temp_zip_path), MAX_SNAPSHOT_ZIP_BYTES
            )
            os.replace(temp_zip_path, target_path)
        except Exception as exc:
            raise CloudSyncError(f"snapshot zip write failed: {exc}") from exc
        finally:
            if os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except OSError:
                    pass

    return CloudSnapshot(
        path=target_path,
        snapshot_id=snapshot_id,
        machine_id=str(machine_id or ""),
        created_at=created_at,
        app_version=str(app_version or ""),
    )


def _validate_zip_member_name(name: str) -> None:
    normalized = str(name or "").replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
    ):
        raise CloudSnapshotValidationError(f"unsafe snapshot member path: {name}")


def read_snapshot_manifest(zip_path: str) -> Dict[str, Any]:
    try:
        _validate_snapshot_zip_size(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            if MANIFEST_NAME not in zf.namelist():
                raise CloudSnapshotValidationError("snapshot manifest is missing")
            info = _snapshot_member_info(zf, MANIFEST_NAME)
            _ensure_size_limit(
                "snapshot manifest", info.file_size, MAX_SNAPSHOT_JSON_BYTES
            )
            payload = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    except CloudSnapshotValidationError:
        raise
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudSnapshotValidationError(
            f"snapshot manifest could not be read: {exc}"
        ) from exc
    except Exception as exc:
        raise CloudSyncError(f"snapshot manifest could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise CloudSnapshotValidationError("snapshot manifest is not a JSON object")
    if str(payload.get("format_version", "")) != SNAPSHOT_FORMAT_VERSION:
        raise CloudSnapshotValidationError("unsupported snapshot format version")
    if not str(payload.get("snapshot_id", "")).strip():
        raise CloudSnapshotValidationError("snapshot_id is missing")
    if not str(payload.get("db_file", "")).strip():
        raise CloudSnapshotValidationError("db_file is missing")
    return payload


def extract_snapshot(zip_path: str, destination_dir: str) -> Dict[str, str]:
    manifest = read_snapshot_manifest(zip_path)
    db_member = str(manifest.get("db_file", DB_SNAPSHOT_NAME) or DB_SNAPSHOT_NAME)
    settings_member = str(manifest.get("settings_file", SETTINGS_NAME) or SETTINGS_NAME)
    for member in (MANIFEST_NAME, db_member, settings_member):
        _validate_zip_member_name(member)

    os.makedirs(destination_dir, exist_ok=True)
    extracted: Dict[str, str] = {
        "manifest": os.path.join(destination_dir, MANIFEST_NAME),
        "db": os.path.join(destination_dir, os.path.basename(db_member)),
        "settings": os.path.join(destination_dir, os.path.basename(settings_member)),
    }
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            if db_member not in names:
                raise CloudSnapshotValidationError("snapshot database is missing")
            if settings_member not in names:
                raise CloudSnapshotValidationError("snapshot settings are missing")
            _ensure_size_limit(
                "snapshot database",
                _snapshot_member_info(zf, db_member).file_size,
                MAX_SNAPSHOT_DB_BYTES,
            )
            _ensure_size_limit(
                "snapshot manifest",
                _snapshot_member_info(zf, MANIFEST_NAME).file_size,
                MAX_SNAPSHOT_JSON_BYTES,
            )
            _ensure_size_limit(
                "snapshot settings",
                _snapshot_member_info(zf, settings_member).file_size,
                MAX_SNAPSHOT_JSON_BYTES,
            )
            for member, target in (
                (MANIFEST_NAME, extracted["manifest"]),
                (db_member, extracted["db"]),
                (settings_member, extracted["settings"]),
            ):
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except CloudSnapshotValidationError:
        raise
    except Exception as exc:
        raise CloudSyncError(f"snapshot extraction failed: {exc}") from exc
    _verify_sqlite_db(extracted["db"])
    return extracted


def list_cloud_snapshots(sync_dir: str) -> List[str]:
    root = resolve_cloud_sync_dir(sync_dir, allow_empty=True)
    if not root or not os.path.isdir(root):
        return []
    paths = []
    for entry in os.listdir(root):
        if not entry.startswith(SNAPSHOT_PREFIX) or not entry.endswith(SNAPSHOT_SUFFIX):
            continue
        candidate = os.path.join(root, entry)
        if os.path.isfile(candidate):
            paths.append(candidate)
    paths.sort(key=lambda path: (os.path.getmtime(path), path))
    return paths


def cleanup_old_snapshots(sync_dir: str, *, keep: int = 100) -> int:
    snapshots = list_cloud_snapshots(sync_dir)
    excess = snapshots[: max(0, len(snapshots) - max(1, int(keep)))]
    deleted = 0
    for path in excess:
        try:
            os.remove(path)
            deleted += 1
        except OSError:
            pass
    return deleted


__all__ = [
    "_utc_now_iso",
    "_safe_snapshot_token",
    "_atomic_write_json",
    "_ensure_size_limit",
    "_snapshot_member_info",
    "_validate_snapshot_zip_size",
    "quarantine_invalid_snapshot",
    "sanitize_config_for_cloud",
    "_snapshot_sqlite_db",
    "_verify_sqlite_db",
    "create_cloud_snapshot",
    "_validate_zip_member_name",
    "read_snapshot_manifest",
    "extract_snapshot",
    "list_cloud_snapshots",
    "cleanup_old_snapshots",
]
