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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from core.runtime_support.paths import RuntimePaths


SNAPSHOT_FORMAT_VERSION = "1.0"
SNAPSHOT_PREFIX = "news_scraper_sync_"
SNAPSHOT_SUFFIX = ".zip"
MANIFEST_NAME = "manifest.json"
SETTINGS_NAME = "settings.json"
DB_SNAPSHOT_NAME = "news_database.db"
MAX_SNAPSHOT_ZIP_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_DB_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_JSON_BYTES = 1 * 1024 * 1024
INVALID_SNAPSHOT_DIR = ".invalid"
SANITIZED_APP_SETTING_KEYS = {
    "client_id",
    "client_secret",
    "client_secret_enc",
    "client_secret_storage",
    "cloud_sync_dir",
}
SANITIZED_ROOT_KEYS = {
    "automation_rules",
    "publisher_aliases",
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


def _ensure_size_limit(label: str, size_bytes: int, max_bytes: int) -> None:
    if int(size_bytes or 0) > int(max_bytes):
        raise CloudSyncError(f"{label} exceeds size limit ({size_bytes} > {max_bytes} bytes)")


def _snapshot_member_info(zf: zipfile.ZipFile, member: str) -> zipfile.ZipInfo:
    try:
        return zf.getinfo(member)
    except KeyError as exc:
        raise CloudSyncError(f"snapshot member is missing: {member}") from exc


def _validate_snapshot_zip_size(zip_path: str) -> None:
    if not os.path.exists(zip_path):
        raise CloudSyncError(f"snapshot does not exist: {zip_path}")
    _ensure_size_limit("snapshot zip", os.path.getsize(zip_path), MAX_SNAPSHOT_ZIP_BYTES)


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
        if reason:
            with open(target + ".reason.txt", "w", encoding="utf-8", newline="\n") as handle:
                handle.write(str(reason))
                handle.write("\n")
        return target
    except OSError:
        return ""


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
        _ensure_size_limit("snapshot database", os.path.getsize(staging_db), MAX_SNAPSHOT_DB_BYTES)
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        settings_bytes = json.dumps(sanitized_config, ensure_ascii=False, indent=2).encode("utf-8")
        _ensure_size_limit("snapshot manifest", len(manifest_bytes), MAX_SNAPSHOT_JSON_BYTES)
        _ensure_size_limit("snapshot settings", len(settings_bytes), MAX_SNAPSHOT_JSON_BYTES)

        try:
            with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, manifest_bytes)
                zf.writestr(SETTINGS_NAME, settings_bytes)
                zf.write(staging_db, DB_SNAPSHOT_NAME)
            _ensure_size_limit("snapshot zip", os.path.getsize(temp_zip_path), MAX_SNAPSHOT_ZIP_BYTES)
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
        _validate_snapshot_zip_size(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            if MANIFEST_NAME not in zf.namelist():
                raise CloudSyncError("snapshot manifest is missing")
            info = _snapshot_member_info(zf, MANIFEST_NAME)
            _ensure_size_limit("snapshot manifest", info.file_size, MAX_SNAPSHOT_JSON_BYTES)
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


def _snapshot_import_error(zip_path: str, exc: BaseException) -> str:
    return f"{os.path.basename(zip_path)}: {exc}"


def select_cloud_snapshots_for_import(
    *,
    db_manager: Any,
    sync_dir: str,
    local_snapshot_id: str = "",
    max_imports: int = 20,
) -> Dict[str, Any]:
    seen_ids = set()
    try:
        seen_ids = set(db_manager.get_cloud_sync_seen_snapshot_ids())
    except Exception:
        seen_ids = set()

    candidates: List[tuple[float, str, str]] = []
    errors: List[str] = []
    skipped_seen = 0
    local_snapshot_id = str(local_snapshot_id or "")
    for zip_path in list_cloud_snapshots(sync_dir):
        try:
            manifest = read_snapshot_manifest(zip_path)
            snapshot_id = str(manifest.get("snapshot_id", "") or "").strip()
            if not snapshot_id:
                raise CloudSyncError("snapshot_id is missing")
            if snapshot_id == local_snapshot_id or snapshot_id in seen_ids:
                skipped_seen += 1
                continue
            candidates.append((os.path.getmtime(zip_path), zip_path, snapshot_id))
        except Exception as exc:
            message = _snapshot_import_error(zip_path, exc)
            quarantined = quarantine_invalid_snapshot(zip_path, str(exc))
            if quarantined:
                message += f" (quarantined: {os.path.basename(quarantined)})"
            errors.append(message)

    candidates.sort(key=lambda item: (item[0], item[1]))
    limit = max(1, int(max_imports or 20))
    selected = [path for _mtime, path, _snapshot_id in candidates[:limit]]
    return {
        "paths": selected,
        "errors": errors,
        "skipped_seen": skipped_seen,
        "pending_unseen": max(0, len(candidates) - len(selected)),
    }


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


def preview_cloud_snapshot_import(
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
            "snapshot_path": zip_path,
            "source_machine_id": source_machine_id,
            "news_added": 0,
            "memberships_added": 0,
            "read_changed": 0,
            "bookmark_changed": 0,
            "notes_changed": 0,
            "tags_changed": 0,
            "deleted": 0,
            "restored": 0,
        }
    with tempfile.TemporaryDirectory(prefix="news_cloud_preview_") as staging_dir:
        extracted = extract_snapshot(zip_path, staging_dir)
        result = db_manager.preview_cloud_snapshot_db(
            extracted["db"],
            snapshot_id=snapshot_id,
            source_machine_id=source_machine_id,
            local_machine_id=local_machine_id,
        )
    result["snapshot_path"] = zip_path
    result["source_machine_id"] = source_machine_id
    return result


def aggregate_cloud_import_preview(previews: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    keys = [
        "news_added",
        "memberships_added",
        "read_changed",
        "bookmark_changed",
        "notes_changed",
        "tags_changed",
        "deleted",
        "restored",
    ]
    totals = {key: 0 for key in keys}
    totals["merge_candidates"] = 0
    totals["skipped"] = 0
    for preview in previews:
        if bool(preview.get("skipped", False)):
            totals["skipped"] += 1
            continue
        totals["merge_candidates"] += 1
        for key in keys:
            totals[key] += int(preview.get(key, 0) or 0)
    return totals


def preview_cloud_snapshots_for_import(
    *,
    db_manager: Any,
    sync_dir: str,
    local_machine_id: str,
    max_imports: int = 20,
) -> Dict[str, Any]:
    selection = select_cloud_snapshots_for_import(
        db_manager=db_manager,
        sync_dir=sync_dir,
        max_imports=max_imports,
    )
    previews: List[Dict[str, Any]] = []
    errors = list(selection.get("errors", []) or [])
    invalid_count = len(errors)
    for zip_path in selection["paths"]:
        try:
            previews.append(
                preview_cloud_snapshot_import(
                    db_manager=db_manager,
                    zip_path=zip_path,
                    local_machine_id=local_machine_id,
                )
            )
        except Exception as exc:
            errors.append(_snapshot_import_error(zip_path, exc))
            invalid_count += 1
            quarantine_invalid_snapshot(zip_path, str(exc))
    return {
        "paths": list(selection.get("paths", []) or []),
        "previews": previews,
        "totals": aggregate_cloud_import_preview(previews),
        "errors": errors,
        "invalid_count": invalid_count,
        "pending_unseen": selection.get("pending_unseen", 0),
        "skipped_seen": selection.get("skipped_seen", 0),
    }


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
    selection = select_cloud_snapshots_for_import(
        db_manager=db_manager,
        sync_dir=sync_dir,
        local_snapshot_id=snapshot.snapshot_id,
        max_imports=max_imports,
    )
    errors.extend(selection["errors"])
    invalid_count = len(selection["errors"])
    pending_unseen = int(selection.get("pending_unseen", 0) or 0)
    skipped_seen = int(selection.get("skipped_seen", 0) or 0)
    for zip_path in selection["paths"]:
        try:
            result = import_cloud_snapshot(
                db_manager=db_manager,
                zip_path=zip_path,
                local_machine_id=machine_id,
            )
            imported.append(result)
        except Exception as exc:
            errors.append(_snapshot_import_error(zip_path, exc))
            invalid_count += 1
            quarantine_invalid_snapshot(zip_path, str(exc))

    cleanup_old_snapshots(sync_dir, keep=100)
    return {
        "exported": snapshot,
        "imported": imported,
        "import_totals": aggregate_cloud_import_preview(imported),
        "errors": errors,
        "merged_count": sum(1 for item in imported if bool(item.get("merged", False))),
        "skipped_count": sum(1 for item in imported if bool(item.get("skipped", False))),
        "invalid_count": invalid_count,
        "pending_unseen": pending_unseen,
        "skipped_seen": skipped_seen,
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
    "select_cloud_snapshots_for_import",
]
