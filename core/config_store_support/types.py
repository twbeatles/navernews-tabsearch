
from __future__ import annotations

from typing import Any, Dict, List, TypedDict

class WindowGeometry(TypedDict):
    x: int
    y: int
    width: int
    height: int


class AppSettings(TypedDict):
    client_id: str
    client_secret: str
    client_secret_enc: str
    client_secret_storage: str
    theme_index: int
    refresh_interval_index: int
    auto_backup_minutes: int
    notification_enabled: bool
    alert_keywords: List[str]
    sound_enabled: bool
    minimize_to_tray: bool
    close_to_tray: bool
    start_minimized: bool
    auto_start_enabled: bool
    notify_on_refresh: bool
    api_timeout: int
    blocked_publishers: List[str]
    preferred_publishers: List[str]
    cloud_sync_enabled: bool
    cloud_sync_dir: str
    cloud_sync_interval_minutes: int
    window_geometry: WindowGeometry


class AppConfig(TypedDict):
    app_settings: AppSettings
    tabs: List[str]
    search_history: List[str]
    keyword_groups: Dict[str, List[str]]
    pagination_state: Dict[str, int]
    pagination_totals: Dict[str, int]
    saved_searches: Dict[str, Dict[str, Any]]
    tab_refresh_policies: Dict[str, str]
    automation_rules: List[Dict[str, Any]]
    publisher_aliases: Dict[str, str]


DEFAULT_CONFIG: AppConfig = {
    "app_settings": {
        "client_id": "",
        "client_secret": "",
        "client_secret_enc": "",
        "client_secret_storage": "plain",
        "theme_index": 0,
        "refresh_interval_index": 2,
        "auto_backup_minutes": 60,
        "notification_enabled": True,
        "alert_keywords": [],
        "sound_enabled": True,
        "minimize_to_tray": True,
        "close_to_tray": True,
        "start_minimized": False,
        "auto_start_enabled": False,
        "notify_on_refresh": False,
        "api_timeout": 15,
        "blocked_publishers": [],
        "preferred_publishers": [],
        "cloud_sync_enabled": True,
        "cloud_sync_dir": "",
        "cloud_sync_interval_minutes": 30,
        "window_geometry": {
            "x": 100,
            "y": 100,
            "width": 1100,
            "height": 850,
        },
    },
    "tabs": [],
    "search_history": [],
    "keyword_groups": {},
    "pagination_state": {},
    "pagination_totals": {},
    "saved_searches": {},
    "tab_refresh_policies": {},
    "automation_rules": [],
    "publisher_aliases": {},
}

ALLOWED_AUTO_BACKUP_MINUTES = {0, 30, 60, 180, 360}
DEFAULT_AUTO_BACKUP_MINUTES = 60
ALLOWED_CLOUD_SYNC_INTERVAL_MINUTES = {10, 30, 60, 120, 360}
DEFAULT_CLOUD_SYNC_INTERVAL_MINUTES = 30

__all__ = [
    "WindowGeometry",
    "AppSettings",
    "AppConfig",
    "DEFAULT_CONFIG",
    "ALLOWED_AUTO_BACKUP_MINUTES",
    "DEFAULT_AUTO_BACKUP_MINUTES",
    "ALLOWED_CLOUD_SYNC_INTERVAL_MINUTES",
    "DEFAULT_CLOUD_SYNC_INTERVAL_MINUTES",
]
