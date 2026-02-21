import copy
import json
import os
import tempfile
from typing import Any, Dict, List, Tuple, TypedDict


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
    keyword_groups: Dict[str, List[str]]


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
    "keyword_groups": {},
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


def _to_keyword_groups(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, List[str]] = {}
    for key, raw_keywords in value.items():
        if not isinstance(key, str):
            continue
        group_name = key.strip()
        if not group_name:
            continue
        keywords = []
        for keyword in _to_str_list(raw_keywords):
            stripped = keyword.strip()
            if stripped and stripped not in keywords:
                keywords.append(stripped)
        normalized[group_name] = keywords
    return normalized


def _normalize_alert_keywords(value: Any) -> Tuple[List[str], bool]:
    changed = False
    raw_keywords: List[str] = []

    if isinstance(value, str):
        changed = True
        raw_keywords = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_keywords.append(item.strip())
            elif isinstance(item, (int, float)):
                raw_keywords.append(str(item).strip())
                changed = True
            else:
                changed = True
    elif value is None:
        raw_keywords = []
    else:
        changed = True
        raw_keywords = []

    deduped: List[str] = []
    for keyword in raw_keywords:
        if keyword and keyword not in deduped:
            deduped.append(keyword)

    if len(deduped) > 10:
        deduped = deduped[:10]
        changed = True

    if len(deduped) != len(raw_keywords):
        changed = True

    return deduped, changed


def _coerce_bool_for_import(value: Any, fallback: bool) -> Tuple[bool, bool]:
    if isinstance(value, bool):
        return value, False

    if isinstance(value, int) and value in (0, 1):
        return bool(value), True

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "t", "yes", "y", "on"}:
            return True, True
        if lowered in {"0", "false", "f", "no", "n", "off"}:
            return False, True

    return fallback, True


def _coerce_int_range_for_import(
    value: Any, fallback: int, minimum: int, maximum: int
) -> Tuple[int, bool]:
    if isinstance(value, int) and not isinstance(value, bool):
        parsed = value
        changed = False
    else:
        try:
            parsed = int(value)
            changed = True
        except (TypeError, ValueError):
            return fallback, True

    clamped = max(minimum, min(maximum, parsed))
    if clamped != parsed:
        changed = True
    return clamped, changed


def normalize_import_settings(
    raw_settings: Any, fallback_settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    """가져오기용 설정을 타입/범위 기준으로 정규화하고 보정 경고를 반환한다."""
    warnings: List[str] = []
    baseline = copy.deepcopy(DEFAULT_CONFIG["app_settings"])

    if isinstance(fallback_settings, dict):
        baseline["theme_index"] = _to_int(fallback_settings.get("theme_index"), baseline["theme_index"])
        baseline["refresh_interval_index"] = _to_int(
            fallback_settings.get("refresh_interval_index"),
            baseline["refresh_interval_index"],
        )
        baseline["notification_enabled"] = _to_bool(
            fallback_settings.get("notification_enabled"),
            baseline["notification_enabled"],
        )
        baseline["alert_keywords"], _ = _normalize_alert_keywords(
            fallback_settings.get("alert_keywords", baseline["alert_keywords"])
        )
        baseline["sound_enabled"] = _to_bool(
            fallback_settings.get("sound_enabled"), baseline["sound_enabled"]
        )
        baseline["minimize_to_tray"] = _to_bool(
            fallback_settings.get("minimize_to_tray"), baseline["minimize_to_tray"]
        )
        baseline["close_to_tray"] = _to_bool(
            fallback_settings.get("close_to_tray"), baseline["close_to_tray"]
        )
        baseline["start_minimized"] = _to_bool(
            fallback_settings.get("start_minimized"), baseline["start_minimized"]
        )
        baseline["notify_on_refresh"] = _to_bool(
            fallback_settings.get("notify_on_refresh"), baseline["notify_on_refresh"]
        )
        baseline["api_timeout"] = _to_int(
            fallback_settings.get("api_timeout"), baseline["api_timeout"]
        )

    normalized = {
        "theme_index": max(0, min(1, int(baseline["theme_index"]))),
        "refresh_interval_index": max(0, min(5, int(baseline["refresh_interval_index"]))),
        "notification_enabled": bool(baseline["notification_enabled"]),
        "alert_keywords": list(baseline["alert_keywords"]),
        "sound_enabled": bool(baseline["sound_enabled"]),
        "minimize_to_tray": bool(baseline["minimize_to_tray"]),
        "close_to_tray": bool(baseline["close_to_tray"]),
        "start_minimized": bool(baseline["start_minimized"]),
        "notify_on_refresh": bool(baseline["notify_on_refresh"]),
        "api_timeout": max(5, min(60, int(baseline["api_timeout"]))),
    }

    if not isinstance(raw_settings, dict):
        warnings.append("settings 형식이 올바르지 않아 기존 설정을 유지했습니다.")
        return normalized, warnings

    int_fields = {
        "theme_index": (0, 1),
        "refresh_interval_index": (0, 5),
        "api_timeout": (5, 60),
    }
    bool_fields = [
        "notification_enabled",
        "sound_enabled",
        "minimize_to_tray",
        "close_to_tray",
        "start_minimized",
        "notify_on_refresh",
    ]

    for field, (minimum, maximum) in int_fields.items():
        coerced, changed = _coerce_int_range_for_import(
            raw_settings.get(field), normalized[field], minimum, maximum
        )
        normalized[field] = coerced
        if changed and field in raw_settings:
            warnings.append(
                f"{field} 값을 {coerced}(으)로 보정했습니다."
            )

    for field in bool_fields:
        coerced, changed = _coerce_bool_for_import(raw_settings.get(field), normalized[field])
        normalized[field] = coerced
        if changed and field in raw_settings:
            warnings.append(
                f"{field} 값을 {coerced}(으)로 보정했습니다."
            )

    normalized_alert_keywords, changed_alert = _normalize_alert_keywords(
        raw_settings.get("alert_keywords", normalized["alert_keywords"])
    )
    normalized["alert_keywords"] = normalized_alert_keywords
    if changed_alert and "alert_keywords" in raw_settings:
        warnings.append(
            f"alert_keywords 값을 정규화했습니다. (최대 10개, 중복 제거)"
        )

    return normalized, warnings


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
        cfg["keyword_groups"] = _to_keyword_groups(raw.get("keyword_groups"))
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
    cfg["keyword_groups"] = _to_keyword_groups(raw.get("keyword_groups"))
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
