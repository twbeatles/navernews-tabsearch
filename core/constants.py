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
VERSION = "32.7.3"
PENDING_RESTORE_FILE = RUNTIME_PATHS.pending_restore_file

__all__ = [
    "APP_DATA_NAME",
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
    "get_app_dir",
    "get_data_dir",
    "get_runtime_paths",
    "migrate_legacy_runtime_files",
]
