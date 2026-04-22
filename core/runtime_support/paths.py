from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

APP_DATA_NAME = "NaverNewsScraperPro"
BACKUP_DIRNAME = "backups"
CONFIG_FILENAME = "news_scraper_config.json"
CONFIG_BACKUP_FILENAME = "news_scraper_config.json.backup"
CRASH_LOG_FILENAME = "crash_log.txt"
DB_FILENAME = "news_database.db"
INSTANCE_LOCK_FILENAME = "news_scraper_pro.lock"
KEYWORD_GROUPS_FILENAME = "keyword_groups.json"
LOG_FILENAME = "news_scraper.log"
PENDING_RESTORE_FILENAME = "pending_restore.json"


@dataclass(frozen=True)
class RuntimePaths:
    app_dir: str
    data_dir: str
    config_file: str
    config_backup_file: str
    db_file: str
    log_file: str
    pending_restore_file: str
    backup_dir: str
    keyword_groups_file: str
    crash_log_file: str
    instance_lock_file: str


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_truthy_env(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def get_data_dir(
    env: Optional[Mapping[str, str]] = None,
    *,
    platform: Optional[str] = None,
    app_dir: Optional[str] = None,
) -> str:
    env_map = env or os.environ
    resolved_platform = platform or sys.platform
    resolved_app_dir = os.path.abspath(app_dir or get_app_dir())

    override = str(env_map.get("NEWS_SCRAPER_DATA_DIR", "") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(override)))

    if _is_truthy_env(env_map.get("NEWS_SCRAPER_PORTABLE")):
        return resolved_app_dir

    if resolved_platform == "win32":
        base_dir = str(env_map.get("LOCALAPPDATA", "") or env_map.get("APPDATA", "")).strip()
        if base_dir:
            return os.path.join(base_dir, APP_DATA_NAME)

    if resolved_platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), APP_DATA_NAME)

    xdg_data_home = str(env_map.get("XDG_DATA_HOME", "") or "").strip()
    if xdg_data_home:
        return os.path.join(xdg_data_home, APP_DATA_NAME)
    return os.path.join(os.path.expanduser("~/.local/share"), APP_DATA_NAME)


def get_runtime_paths(
    env: Optional[Mapping[str, str]] = None,
    *,
    platform: Optional[str] = None,
    app_dir: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> RuntimePaths:
    resolved_app_dir = os.path.abspath(app_dir or get_app_dir())
    resolved_data_dir = os.path.abspath(
        os.path.expanduser(
            os.path.expandvars(
                data_dir or get_data_dir(env=env, platform=platform, app_dir=resolved_app_dir)
            )
        )
    )
    return RuntimePaths(
        app_dir=resolved_app_dir,
        data_dir=resolved_data_dir,
        config_file=os.path.join(resolved_data_dir, CONFIG_FILENAME),
        config_backup_file=os.path.join(resolved_data_dir, CONFIG_BACKUP_FILENAME),
        db_file=os.path.join(resolved_data_dir, DB_FILENAME),
        log_file=os.path.join(resolved_data_dir, LOG_FILENAME),
        pending_restore_file=os.path.join(resolved_data_dir, PENDING_RESTORE_FILENAME),
        backup_dir=os.path.join(resolved_data_dir, BACKUP_DIRNAME),
        keyword_groups_file=os.path.join(resolved_data_dir, KEYWORD_GROUPS_FILENAME),
        crash_log_file=os.path.join(resolved_data_dir, CRASH_LOG_FILENAME),
        instance_lock_file=os.path.join(resolved_data_dir, INSTANCE_LOCK_FILENAME),
    )


__all__ = [
    "APP_DATA_NAME",
    "BACKUP_DIRNAME",
    "CONFIG_BACKUP_FILENAME",
    "CONFIG_FILENAME",
    "CRASH_LOG_FILENAME",
    "DB_FILENAME",
    "INSTANCE_LOCK_FILENAME",
    "KEYWORD_GROUPS_FILENAME",
    "LOG_FILENAME",
    "PENDING_RESTORE_FILENAME",
    "RuntimePaths",
    "get_app_dir",
    "get_data_dir",
    "get_runtime_paths",
]
