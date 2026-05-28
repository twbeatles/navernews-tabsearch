
from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Mapping, Sequence

from core.cloud_sync_support.models import CloudSyncError
from core.cloud_sync_support.snapshot_io import (
    cleanup_old_snapshots,
    create_cloud_snapshot,
    extract_snapshot,
    list_cloud_snapshots,
    quarantine_invalid_snapshot,
    read_snapshot_manifest,
)


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
    imported: List[Dict[str, Any]] = []
    errors: List[str] = []
    selection = select_cloud_snapshots_for_import(
        db_manager=db_manager,
        sync_dir=sync_dir,
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

    snapshot = create_cloud_snapshot(
        sync_dir=sync_dir,
        config=config,
        db_file=db_file,
        machine_id=machine_id,
        app_version=app_version,
    )
    db_manager.mark_cloud_sync_snapshot_seen(snapshot.snapshot_id)

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

__all__ = [
    "_snapshot_import_error",
    "select_cloud_snapshots_for_import",
    "import_cloud_snapshot",
    "preview_cloud_snapshot_import",
    "aggregate_cloud_import_preview",
    "preview_cloud_snapshots_for_import",
    "run_cloud_sync_cycle",
]
