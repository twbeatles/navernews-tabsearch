
from __future__ import annotations

from dataclasses import dataclass

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

__all__ = [
    "SNAPSHOT_FORMAT_VERSION",
    "SNAPSHOT_PREFIX",
    "SNAPSHOT_SUFFIX",
    "MANIFEST_NAME",
    "SETTINGS_NAME",
    "DB_SNAPSHOT_NAME",
    "MAX_SNAPSHOT_ZIP_BYTES",
    "MAX_SNAPSHOT_DB_BYTES",
    "MAX_SNAPSHOT_JSON_BYTES",
    "INVALID_SNAPSHOT_DIR",
    "SANITIZED_APP_SETTING_KEYS",
    "SANITIZED_ROOT_KEYS",
    "CLOUD_PATH_MARKERS",
    "CloudSyncError",
    "CloudSnapshot",
]
