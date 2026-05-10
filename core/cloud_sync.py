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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.runtime_support.paths import RuntimePaths


SNAPSHOT_FORMAT_VERSION = "1.0"
SNAPSHOT_PREFIX = "news_scraper_sync_"
SNAPSHOT_SUFFIX = ".zip"
MANIFEST_NAME = "manifest.json"
SETTINGS_NAME = "settings.json"
DB_SNAPSHOT_NAME = "news_database.db"
SANITIZED_APP_SETTING_KEYS = {
    "client_id",
    "client_secret",
    "client_secret_enc",
    "client_secret_storage",
    "cloud_sync_dir",
}
CLOUD_PATH_MARKERS = {
    "onedrive",
    "google drive",
    "googledrive",
    "google 드라이브",
    "dropbox",
    "icloud",
    "box",
}


class CloudSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudSnapshot:
    path: str
    snapshot_id: str
    machine_id: str
    created_at: str
    app_version: str


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


def sanitize_config_for_cloud(config: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(dict(config))
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
            raise CloudSyncError(f"snapshot integrity_check failed: {row[0] if row else 'unknown'}")
    except CloudSyncError:
        raise
    except Exception as exc:
        raise CloudSyncError(f"snapshot database is unreadable: {exc}") from exc
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
    target_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(str(sync_dir or ""))))
    if not target_dir:
        raise CloudSyncError("sync directory is empty")
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

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                zf.writestr(SETTINGS_NAME, json.dumps(sanitized_config, ensure_ascii=False, indent=2))
                zf.write(staging_db, DB_SNAPSHOT_NAME)
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
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise CloudSyncError(f"unsafe snapshot member path: {name}")


def read_snapshot_manifest(zip_path: str) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if MANIFEST_NAME not in zf.namelist():
                raise CloudSyncError("snapshot manifest is missing")
            payload = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    except CloudSyncError:
        raise
    except Exception as exc:
        raise CloudSyncError(f"snapshot manifest could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise CloudSyncError("snapshot manifest is not a JSON object")
    if str(payload.get("format_version", "")) != SNAPSHOT_FORMAT_VERSION:
        raise CloudSyncError("unsupported snapshot format version")
    if not str(payload.get("snapshot_id", "")).strip():
        raise CloudSyncError("snapshot_id is missing")
    if not str(payload.get("db_file", "")).strip():
        raise CloudSyncError("db_file is missing")
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
                raise CloudSyncError("snapshot database is missing")
            if settings_member not in names:
                raise CloudSyncError("snapshot settings are missing")
            for member, target in (
                (MANIFEST_NAME, extracted["manifest"]),
                (db_member, extracted["db"]),
                (settings_member, extracted["settings"]),
            ):
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except CloudSyncError:
        raise
    except Exception as exc:
        raise CloudSyncError(f"snapshot extraction failed: {exc}") from exc
    _verify_sqlite_db(extracted["db"])
    return extracted


def list_cloud_snapshots(sync_dir: str) -> List[str]:
    root = os.path.abspath(os.path.expanduser(os.path.expandvars(str(sync_dir or ""))))
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


def import_cloud_snapshot(
    *,
    db_manager: Any,
    zip_path: str,
    local_machine_id: str,
) -> Dict[str, Any]:
    manifest = read_snapshot_manifest(zip_path)
    snapshot_id = str(manifest.get("snapshot_id", "") or "").strip()
    source_machine_id = str(manifest.get("machine_id", "") or "").strip()
    if snapshot_id in db_manager.get_cloud_sync_seen_snapshot_ids():
        return {
            "snapshot_id": snapshot_id,
            "merged": False,
            "skipped": True,
            "reason": "already_seen",
        }
    with tempfile.TemporaryDirectory(prefix="news_cloud_import_") as staging_dir:
        extracted = extract_snapshot(zip_path, staging_dir)
        result = db_manager.merge_cloud_snapshot_db(
            extracted["db"],
            snapshot_id=snapshot_id,
            source_machine_id=source_machine_id,
            local_machine_id=local_machine_id,
        )
    result["snapshot_path"] = zip_path
    result["source_machine_id"] = source_machine_id
    return result


def run_cloud_sync_cycle(
    *,
    db_manager: Any,
    sync_dir: str,
    config: Mapping[str, Any],
    db_file: str,
    machine_id: str,
    app_version: str,
    max_imports: int = 20,
) -> Dict[str, Any]:
    snapshot = create_cloud_snapshot(
        sync_dir=sync_dir,
        config=config,
        db_file=db_file,
        machine_id=machine_id,
        app_version=app_version,
    )
    db_manager.mark_cloud_sync_snapshot_seen(snapshot.snapshot_id)

    imported: List[Dict[str, Any]] = []
    errors: List[str] = []
    for zip_path in list_cloud_snapshots(sync_dir)[-max(1, int(max_imports)) :]:
        try:
            manifest = read_snapshot_manifest(zip_path)
            if str(manifest.get("snapshot_id", "") or "") == snapshot.snapshot_id:
                continue
            result = import_cloud_snapshot(
                db_manager=db_manager,
                zip_path=zip_path,
                local_machine_id=machine_id,
            )
            imported.append(result)
        except CloudSyncError as exc:
            errors.append(f"{os.path.basename(zip_path)}: {exc}")

    cleanup_old_snapshots(sync_dir, keep=100)
    return {
        "exported": snapshot,
        "imported": imported,
        "errors": errors,
        "merged_count": sum(1 for item in imported if bool(item.get("merged", False))),
        "skipped_count": sum(1 for item in imported if bool(item.get("skipped", False))),
    }


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


def _path_parts(path: str) -> Iterable[str]:
    try:
        return Path(os.path.abspath(path)).parts
    except Exception:
        return ()


def is_probable_cloud_storage_path(path: str) -> bool:
    normalized_parts = [" ".join(part.lower().split()) for part in _path_parts(path)]
    for part in normalized_parts:
        compact = part.replace(" ", "")
        if part in CLOUD_PATH_MARKERS or compact in CLOUD_PATH_MARKERS:
            return True
        if part.startswith("onedrive") or compact.startswith("googledrive"):
            return True
    return False


def _is_relative_to(child: str, parent: str) -> bool:
    try:
        child_path = Path(os.path.abspath(child))
        parent_path = Path(os.path.abspath(parent))
        child_path.relative_to(parent_path)
        return True
    except Exception:
        return False


def cloud_sync_path_conflicts_with_runtime(sync_dir: str, runtime_paths: RuntimePaths) -> bool:
    resolved_sync_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(str(sync_dir or ""))))
    if not resolved_sync_dir:
        return False
    return any(
        (
            _is_relative_to(runtime_paths.data_dir, resolved_sync_dir),
            _is_relative_to(runtime_paths.db_file, resolved_sync_dir),
            _is_relative_to(resolved_sync_dir, runtime_paths.data_dir),
        )
    )


def runtime_storage_is_probably_cloud(runtime_paths: RuntimePaths) -> bool:
    return is_probable_cloud_storage_path(runtime_paths.data_dir) or is_probable_cloud_storage_path(
        runtime_paths.db_file
    )


__all__ = [
    "CloudSnapshot",
    "CloudSyncError",
    "DB_SNAPSHOT_NAME",
    "MANIFEST_NAME",
    "SETTINGS_NAME",
    "SNAPSHOT_FORMAT_VERSION",
    "cleanup_old_snapshots",
    "cloud_sync_path_conflicts_with_runtime",
    "create_cloud_snapshot",
    "extract_snapshot",
    "import_cloud_snapshot",
    "is_probable_cloud_storage_path",
    "list_cloud_snapshots",
    "read_snapshot_manifest",
    "run_cloud_sync_cycle",
    "runtime_storage_is_probably_cloud",
    "sanitize_config_for_cloud",
]
