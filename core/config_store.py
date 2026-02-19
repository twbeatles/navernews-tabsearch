import copy
import json
import os
import tempfile
from typing import Any, Dict, List, TypedDict


class WindowGeometry(TypedDict):
    x: int
    y: int
    width: int
    height: int


class AppSettings(TypedDict):
    client_id: str
    client_secret: str
    theme_index: int
    refresh_interval_index: int
    notification_enabled: bool
    alert_keywords: List[str]
    sound_enabled: bool
    minimize_to_tray: bool
    close_to_tray: bool
    start_minimized: bool
    auto_start_enabled: bool
    notify_on_refresh: bool
    api_timeout: int
    window_geometry: WindowGeometry


class AppConfig(TypedDict):
    app_settings: AppSettings
    tabs: List[str]
    search_history: List[str]


DEFAULT_CONFIG: AppConfig = {
    "app_settings": {
        "client_id": "",
        "client_secret": "",
        "theme_index": 0,
        "refresh_interval_index": 2,
        "notification_enabled": True,
        "alert_keywords": [],
        "sound_enabled": True,
        "minimize_to_tray": True,
        "close_to_tray": True,
        "start_minimized": False,
        "auto_start_enabled": False,
        "notify_on_refresh": False,
        "api_timeout": 15,
        "window_geometry": {
            "x": 100,
            "y": 100,
            "width": 1100,
            "height": 850,
        },
    },
    "tabs": [],
    "search_history": [],
}


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _to_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def default_config() -> AppConfig:
    return copy.deepcopy(DEFAULT_CONFIG)


def normalize_loaded_config(raw: Dict[str, Any]) -> AppConfig:
    cfg = default_config()

    if "app_settings" in raw and isinstance(raw.get("app_settings"), dict):
        app_raw = raw["app_settings"]
        app_cfg = cfg["app_settings"]
        app_cfg["client_id"] = str(app_raw.get("client_id", app_cfg["client_id"]))
        app_cfg["client_secret"] = str(app_raw.get("client_secret", app_cfg["client_secret"]))
        app_cfg["theme_index"] = _to_int(app_raw.get("theme_index"), app_cfg["theme_index"])
        app_cfg["refresh_interval_index"] = _to_int(
            app_raw.get("refresh_interval_index"), app_cfg["refresh_interval_index"]
        )
        app_cfg["notification_enabled"] = _to_bool(
            app_raw.get("notification_enabled"), app_cfg["notification_enabled"]
        )
        app_cfg["alert_keywords"] = _to_str_list(app_raw.get("alert_keywords"))
        app_cfg["sound_enabled"] = _to_bool(app_raw.get("sound_enabled"), app_cfg["sound_enabled"])
        app_cfg["minimize_to_tray"] = _to_bool(app_raw.get("minimize_to_tray"), app_cfg["minimize_to_tray"])
        app_cfg["close_to_tray"] = _to_bool(app_raw.get("close_to_tray"), app_cfg["close_to_tray"])
        app_cfg["start_minimized"] = _to_bool(app_raw.get("start_minimized"), app_cfg["start_minimized"])
        app_cfg["auto_start_enabled"] = _to_bool(
            app_raw.get("auto_start_enabled"), app_cfg["auto_start_enabled"]
        )
        app_cfg["notify_on_refresh"] = _to_bool(app_raw.get("notify_on_refresh"), app_cfg["notify_on_refresh"])
        app_cfg["api_timeout"] = _to_int(app_raw.get("api_timeout"), app_cfg["api_timeout"])

        geom_raw = app_raw.get("window_geometry")
        if isinstance(geom_raw, dict):
            app_cfg["window_geometry"] = {
                "x": _to_int(geom_raw.get("x"), cfg["app_settings"]["window_geometry"]["x"]),
                "y": _to_int(geom_raw.get("y"), cfg["app_settings"]["window_geometry"]["y"]),
                "width": _to_int(geom_raw.get("width"), cfg["app_settings"]["window_geometry"]["width"]),
                "height": _to_int(geom_raw.get("height"), cfg["app_settings"]["window_geometry"]["height"]),
            }

        cfg["tabs"] = _to_str_list(raw.get("tabs"))
        cfg["search_history"] = _to_str_list(raw.get("search_history"))
        return cfg

    # Legacy flat schema
    app_cfg = cfg["app_settings"]
    app_cfg["client_id"] = str(raw.get("id", app_cfg["client_id"]))
    app_cfg["client_secret"] = str(raw.get("secret", app_cfg["client_secret"]))
    app_cfg["theme_index"] = _to_int(raw.get("theme"), app_cfg["theme_index"])
    app_cfg["refresh_interval_index"] = _to_int(raw.get("interval"), app_cfg["refresh_interval_index"])
    app_cfg["api_timeout"] = _to_int(raw.get("api_timeout"), app_cfg["api_timeout"])
    cfg["tabs"] = _to_str_list(raw.get("tabs"))
    cfg["search_history"] = _to_str_list(raw.get("search_history"))
    return cfg


def load_config_file(path: str) -> AppConfig:
    if not os.path.exists(path):
        return default_config()

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return default_config()
    return normalize_loaded_config(raw)


def save_config_file_atomic(path: str, config: AppConfig) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
