from __future__ import annotations

import os

from core.runtime_support import (
    APP_DATA_NAME,
    BACKUP_DIRNAME,
    CONFIG_BACKUP_FILENAME,
    CONFIG_FILENAME,
    CRASH_LOG_FILENAME,
    DB_FILENAME,
    INSTANCE_LOCK_FILENAME,
    KEYWORD_GROUPS_FILENAME,
    LOG_FILENAME,
    PENDING_RESTORE_FILENAME,
    RuntimePaths,
    get_app_dir,
    get_data_dir,
    get_runtime_paths,
    migrate_legacy_runtime_files,
)


APP_DIR = get_app_dir()
RUNTIME_PATHS = get_runtime_paths(app_dir=APP_DIR)
DATA_DIR = RUNTIME_PATHS.data_dir
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE = RUNTIME_PATHS.log_file
CONFIG_FILE = RUNTIME_PATHS.config_file
CONFIG_BACKUP_FILE = RUNTIME_PATHS.config_backup_file
DB_FILE = RUNTIME_PATHS.db_file
BACKUP_DIR = RUNTIME_PATHS.backup_dir
KEYWORD_GROUPS_FILE = RUNTIME_PATHS.keyword_groups_file
CRASH_LOG_FILE = RUNTIME_PATHS.crash_log_file
INSTANCE_LOCK_FILE = RUNTIME_PATHS.instance_lock_file
ICON_FILE = "news_icon.ico"
ICON_PNG = "news_icon.png"
APP_NAME = "뉴스 스크래퍼 Pro"
APP_USER_MODEL_ID = "Twbeatles.NaverNewsScraperPro"
VERSION = "32.10.0"
PENDING_RESTORE_FILE = RUNTIME_PATHS.pending_restore_file

# GitHub release update channel.  The private half of this Ed25519 key is kept
# outside the repository and is only used by scripts/build_update_manifest.py.
UPDATE_MANIFEST_URL = os.environ.get(
    "NEWS_SCRAPER_UPDATE_MANIFEST_URL",
    "https://raw.githubusercontent.com/twbeatles/navernews-tabsearch/main/updates/latest.json",
)
UPDATE_PUBLIC_KEY_B64 = os.environ.get(
    "NEWS_SCRAPER_UPDATE_PUBLIC_KEY_B64",
    "5wksVeeIHiXbyvv1DNVQZafIJZ/h8Nu9AZ8d3xrAdxE=",
)
# The news_fts FTS5 index is kept in the schema for future ranking work, but no
# query path consults it today: _fts_match_expression() returns "" on purpose so
# that an FTS MATCH prefilter cannot drop Korean compound-word results. Running
# the backfill worker therefore costs CPU, disk and database size for no search
# benefit, so it is off unless explicitly enabled.
FTS_BACKFILL_ENABLED = os.environ.get("NEWS_SCRAPER_ENABLE_FTS_BACKFILL", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

UPDATE_RELEASES_URL = "https://github.com/twbeatles/navernews-tabsearch/releases/latest"
UPDATE_MANIFEST_MAX_BYTES = 256 * 1024
UPDATE_ARTIFACT_MAX_BYTES = 500 * 1024 * 1024
UPDATE_REQUEST_TIMEOUT_SECONDS = 20
UPDATE_BACKUP_KEEP_COUNT = 2

__all__ = [
    "APP_DATA_NAME",
    "APP_DIR",
    "APP_NAME",
    "APP_USER_MODEL_ID",
    "BACKUP_DIR",
    "BACKUP_DIRNAME",
    "CONFIG_BACKUP_FILE",
    "CONFIG_BACKUP_FILENAME",
    "CONFIG_FILE",
    "CONFIG_FILENAME",
    "CRASH_LOG_FILE",
    "CRASH_LOG_FILENAME",
    "DATA_DIR",
    "DB_FILE",
    "DB_FILENAME",
    "ICON_FILE",
    "ICON_PNG",
    "INSTANCE_LOCK_FILE",
    "INSTANCE_LOCK_FILENAME",
    "KEYWORD_GROUPS_FILE",
    "KEYWORD_GROUPS_FILENAME",
    "LOG_FILE",
    "LOG_FILENAME",
    "PENDING_RESTORE_FILE",
    "PENDING_RESTORE_FILENAME",
    "RUNTIME_PATHS",
    "RuntimePaths",
    "VERSION",
    "UPDATE_ARTIFACT_MAX_BYTES",
    "UPDATE_BACKUP_KEEP_COUNT",
    "UPDATE_MANIFEST_MAX_BYTES",
    "UPDATE_MANIFEST_URL",
    "UPDATE_PUBLIC_KEY_B64",
    "UPDATE_RELEASES_URL",
    "FTS_BACKFILL_ENABLED",
    "UPDATE_REQUEST_TIMEOUT_SECONDS",
    "get_app_dir",
    "get_data_dir",
    "get_runtime_paths",
    "migrate_legacy_runtime_files",
]
