
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from core.cloud_sync_support.models import CLOUD_PATH_MARKERS, CloudSyncError
from core.runtime_support.paths import RuntimePaths


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
    resolved_sync_dir = resolve_cloud_sync_dir(sync_dir, allow_empty=True)
    if not resolved_sync_dir:
        return False
    return any(
        (
            _is_relative_to(runtime_paths.data_dir, resolved_sync_dir),
            _is_relative_to(runtime_paths.db_file, resolved_sync_dir),
            _is_relative_to(resolved_sync_dir, runtime_paths.data_dir),
        )
    )


def resolve_cloud_sync_dir(sync_dir: str, *, allow_empty: bool = False) -> str:
    raw = str(sync_dir or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raise CloudSyncError("sync directory is empty")
    return os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))


def runtime_storage_is_probably_cloud(runtime_paths: RuntimePaths) -> bool:
    return is_probable_cloud_storage_path(runtime_paths.data_dir) or is_probable_cloud_storage_path(
        runtime_paths.db_file
    )

__all__ = [
    "_path_parts",
    "is_probable_cloud_storage_path",
    "_is_relative_to",
    "resolve_cloud_sync_dir",
    "cloud_sync_path_conflicts_with_runtime",
    "runtime_storage_is_probably_cloud",
]
