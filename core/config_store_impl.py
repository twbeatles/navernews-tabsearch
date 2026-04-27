import base64
import copy
import ctypes
import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Tuple, TypedDict

from core.content_filters import normalize_name_list

logger = logging.getLogger(__name__)


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


DEFAULT_CONFIG: AppConfig = {
    "app_settings": {
        "client_id": "",
        "client_secret": "",
        "client_secret_enc": "",
        "client_secret_storage": "plain",
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
        "blocked_publishers": [],
        "preferred_publishers": [],
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
}


def _is_windows_platform() -> bool:
    return sys.platform == "win32"


def _normalize_secret_storage(value: Any) -> str:
    storage = str(value or "").strip().lower()
    if storage == "dpapi":
        return "dpapi"
    return "plain"


def _dpapi_encrypt_text(text: str) -> str:
    if not _is_windows_platform():
        return ""

    plain = str(text or "")
    if not plain:
        return ""

    try:
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        source = plain.encode("utf-8")
        source_buffer = (ctypes.c_byte * len(source)).from_buffer_copy(source)
        in_blob = DATA_BLOB(
            len(source),
            ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = DATA_BLOB()

        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            return ""

        try:
            encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return base64.b64encode(encrypted).decode("ascii")
        finally:
            if out_blob.pbData:
                kernel32.LocalFree(out_blob.pbData)
    except Exception as e:
        logger.warning("DPAPI 암호화 실패: %s", e)
        return ""


def _dpapi_decrypt_text(payload: str) -> str:
    if not _is_windows_platform():
        return ""

    encoded = str(payload or "").strip()
    if not encoded:
        return ""

    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return ""

    if not raw:
        return ""

    try:
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        source_buffer = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)
        in_blob = DATA_BLOB(
            len(raw),
            ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = DATA_BLOB()

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            return ""

        try:
            decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return decrypted.decode("utf-8")
        finally:
            if out_blob.pbData:
                kernel32.LocalFree(out_blob.pbData)
    except Exception as e:
        logger.warning("DPAPI 복호화 실패: %s", e)
        return ""


def encode_client_secret_for_storage(client_secret: str) -> Dict[str, str]:
    plain = str(client_secret or "").strip()
    if not plain:
        return {
            "client_secret": "",
            "client_secret_enc": "",
            "client_secret_storage": "plain",
        }

    if _is_windows_platform():
        encrypted = _dpapi_encrypt_text(plain)
        if encrypted:
            return {
                "client_secret": "",
                "client_secret_enc": encrypted,
                "client_secret_storage": "dpapi",
            }

    return {
        "client_secret": plain,
        "client_secret_enc": "",
        "client_secret_storage": "plain",
    }


def resolve_client_secret_for_runtime(settings: Mapping[str, Any]) -> Tuple[str, bool]:
    plain = str(settings.get("client_secret", "") or "")
    encrypted = str(settings.get("client_secret_enc", "") or "")
    storage = _normalize_secret_storage(settings.get("client_secret_storage", "plain"))

    if _is_windows_platform() and encrypted:
        if storage == "dpapi":
            decrypted = _dpapi_decrypt_text(encrypted)
            if decrypted:
                # Encrypted secret exists; clear legacy plaintext on next save.
                return decrypted, bool(plain)
            # Decryption failed: fallback to legacy plaintext when available.
            if plain:
                return plain, True
            return "", False

        # Unknown storage metadata with encrypted payload: try decrypting defensively.
        decrypted = _dpapi_decrypt_text(encrypted)
        if decrypted:
            return decrypted, True

    if _is_windows_platform() and plain:
        # Legacy plaintext on Windows should migrate to DPAPI.
        return plain, True

    return plain, False


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "f", "no", "n", "off"}:
            return False
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


def _to_pagination_state(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, int] = {}
    for key, raw_start in value.items():
        if not isinstance(key, str):
            continue
        fetch_key = key.strip()
        if not fetch_key:
            continue
        start_idx = _to_int(raw_start, 0)
        if start_idx < 1:
            continue
        normalized[fetch_key] = max(1, min(1000, start_idx))
    return normalized


def _to_pagination_totals(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, int] = {}
    for key, raw_total in value.items():
        if not isinstance(key, str):
            continue
        fetch_key = key.strip()
        if not fetch_key:
            continue
        total = _to_int(raw_total, 0)
        if total < 0:
            continue
        normalized[fetch_key] = total
    return normalized


def _to_saved_searches(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_payload in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_payload, dict):
            continue
        name = raw_name.strip()[:60]
        if not name:
            continue
        payload = dict(raw_payload)
        normalized[name] = {
            "keyword": str(payload.get("keyword", "") or "").strip()[:100],
            "filter_txt": str(payload.get("filter_txt", "") or "").strip()[:200],
            "sort_mode": str(payload.get("sort_mode", "최신순") or "최신순"),
            "only_unread": _to_bool(payload.get("only_unread"), False),
            "hide_duplicates": _to_bool(payload.get("hide_duplicates"), False),
            "date_active": _to_bool(payload.get("date_active"), False),
            "start_date": str(payload.get("start_date", "") or "").strip(),
            "end_date": str(payload.get("end_date", "") or "").strip(),
            "tag_filter": str(payload.get("tag_filter", "") or "").strip()[:30],
            "only_preferred_publishers": _to_bool(
                payload.get("only_preferred_publishers"),
                False,
            ),
        }
        if len(normalized) >= 100:
            break
    return normalized


def _to_tab_refresh_policies(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}

    allowed = {"inherit", "off", "10", "30", "60", "120", "360"}
    normalized: Dict[str, str] = {}
    for raw_keyword, raw_policy in value.items():
        if not isinstance(raw_keyword, str):
            continue
        keyword = raw_keyword.strip()
        if not keyword:
            continue
        policy = str(raw_policy or "inherit").strip().lower()
        if policy not in allowed:
            policy = "inherit"
        normalized[keyword] = policy
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
        baseline["auto_start_enabled"] = _to_bool(
            fallback_settings.get("auto_start_enabled"), baseline["auto_start_enabled"]
        )
        baseline["notify_on_refresh"] = _to_bool(
            fallback_settings.get("notify_on_refresh"), baseline["notify_on_refresh"]
        )
        baseline["api_timeout"] = _to_int(
            fallback_settings.get("api_timeout"), baseline["api_timeout"]
        )
        baseline["blocked_publishers"] = normalize_name_list(
            fallback_settings.get("blocked_publishers", baseline["blocked_publishers"])
        )
        baseline["preferred_publishers"] = normalize_name_list(
            fallback_settings.get("preferred_publishers", baseline["preferred_publishers"])
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
        "auto_start_enabled": bool(baseline["auto_start_enabled"]),
        "notify_on_refresh": bool(baseline["notify_on_refresh"]),
        "api_timeout": max(5, min(60, int(baseline["api_timeout"]))),
        "blocked_publishers": list(baseline["blocked_publishers"]),
        "preferred_publishers": list(baseline["preferred_publishers"]),
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
        "auto_start_enabled",
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

    for field in ("blocked_publishers", "preferred_publishers"):
        normalized_publishers = normalize_name_list(raw_settings.get(field, normalized[field]))
        normalized[field] = normalized_publishers
        if field in raw_settings and normalized_publishers != raw_settings.get(field):
            warnings.append(f"{field} 값을 정규화했습니다. (중복 제거)")

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
        app_cfg["client_secret_enc"] = str(
            app_raw.get("client_secret_enc", app_cfg["client_secret_enc"])
        )
        app_cfg["client_secret_storage"] = _normalize_secret_storage(
            app_raw.get("client_secret_storage", app_cfg["client_secret_storage"])
        )
        app_cfg["theme_index"] = max(0, min(1, _to_int(app_raw.get("theme_index"), app_cfg["theme_index"])))
        app_cfg["refresh_interval_index"] = max(
            0,
            min(
                5,
                _to_int(
                    app_raw.get("refresh_interval_index"), app_cfg["refresh_interval_index"]
                ),
            ),
        )
        app_cfg["notification_enabled"] = _to_bool(
            app_raw.get("notification_enabled"), app_cfg["notification_enabled"]
        )
        app_cfg["alert_keywords"], _ = _normalize_alert_keywords(app_raw.get("alert_keywords"))
        app_cfg["sound_enabled"] = _to_bool(app_raw.get("sound_enabled"), app_cfg["sound_enabled"])
        app_cfg["minimize_to_tray"] = _to_bool(app_raw.get("minimize_to_tray"), app_cfg["minimize_to_tray"])
        app_cfg["close_to_tray"] = _to_bool(app_raw.get("close_to_tray"), app_cfg["close_to_tray"])
        app_cfg["start_minimized"] = _to_bool(app_raw.get("start_minimized"), app_cfg["start_minimized"])
        app_cfg["auto_start_enabled"] = _to_bool(
            app_raw.get("auto_start_enabled"), app_cfg["auto_start_enabled"]
        )
        app_cfg["notify_on_refresh"] = _to_bool(app_raw.get("notify_on_refresh"), app_cfg["notify_on_refresh"])
        app_cfg["api_timeout"] = max(5, min(60, _to_int(app_raw.get("api_timeout"), app_cfg["api_timeout"])))
        app_cfg["blocked_publishers"] = normalize_name_list(
            app_raw.get("blocked_publishers", app_cfg["blocked_publishers"])
        )
        app_cfg["preferred_publishers"] = normalize_name_list(
            app_raw.get("preferred_publishers", app_cfg["preferred_publishers"])
        )

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
        cfg["pagination_state"] = _to_pagination_state(raw.get("pagination_state"))
        cfg["pagination_totals"] = _to_pagination_totals(raw.get("pagination_totals"))
        cfg["saved_searches"] = _to_saved_searches(raw.get("saved_searches"))
        cfg["tab_refresh_policies"] = _to_tab_refresh_policies(raw.get("tab_refresh_policies"))
        return cfg

    # Legacy flat schema
    app_cfg = cfg["app_settings"]
    app_cfg["client_id"] = str(raw.get("id", app_cfg["client_id"]))
    app_cfg["client_secret"] = str(raw.get("secret", app_cfg["client_secret"]))
    app_cfg["client_secret_enc"] = str(raw.get("client_secret_enc", app_cfg["client_secret_enc"]))
    app_cfg["client_secret_storage"] = _normalize_secret_storage(
        raw.get("client_secret_storage", app_cfg["client_secret_storage"])
    )
    app_cfg["theme_index"] = max(0, min(1, _to_int(raw.get("theme"), app_cfg["theme_index"])))
    app_cfg["refresh_interval_index"] = max(
        0, min(5, _to_int(raw.get("interval"), app_cfg["refresh_interval_index"]))
    )
    app_cfg["notification_enabled"] = _to_bool(
        raw.get("notification_enabled"), app_cfg["notification_enabled"]
    )
    app_cfg["alert_keywords"], _ = _normalize_alert_keywords(raw.get("alert_keywords"))
    app_cfg["sound_enabled"] = _to_bool(raw.get("sound_enabled"), app_cfg["sound_enabled"])
    app_cfg["minimize_to_tray"] = _to_bool(raw.get("minimize_to_tray"), app_cfg["minimize_to_tray"])
    app_cfg["close_to_tray"] = _to_bool(raw.get("close_to_tray"), app_cfg["close_to_tray"])
    app_cfg["start_minimized"] = _to_bool(raw.get("start_minimized"), app_cfg["start_minimized"])
    app_cfg["auto_start_enabled"] = _to_bool(raw.get("auto_start_enabled"), app_cfg["auto_start_enabled"])
    app_cfg["notify_on_refresh"] = _to_bool(raw.get("notify_on_refresh"), app_cfg["notify_on_refresh"])
    app_cfg["api_timeout"] = max(5, min(60, _to_int(raw.get("api_timeout"), app_cfg["api_timeout"])))
    app_cfg["blocked_publishers"] = normalize_name_list(raw.get("blocked_publishers", app_cfg["blocked_publishers"]))
    app_cfg["preferred_publishers"] = normalize_name_list(
        raw.get("preferred_publishers", app_cfg["preferred_publishers"])
    )
    cfg["tabs"] = _to_str_list(raw.get("tabs"))
    cfg["search_history"] = _to_str_list(raw.get("search_history"))
    cfg["keyword_groups"] = _to_keyword_groups(raw.get("keyword_groups"))
    cfg["pagination_state"] = _to_pagination_state(raw.get("pagination_state"))
    cfg["pagination_totals"] = _to_pagination_totals(raw.get("pagination_totals"))
    cfg["saved_searches"] = _to_saved_searches(raw.get("saved_searches"))
    cfg["tab_refresh_policies"] = _to_tab_refresh_policies(raw.get("tab_refresh_policies"))
    return cfg


def load_config_file(path: str) -> AppConfig:
    if not os.path.exists(path):
        return default_config()

    def _load_raw_json(file_path: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"config root is not dict: {type(loaded).__name__}")
        return loaded

    raw: Dict[str, Any]
    try:
        raw = _load_raw_json(path)
    except Exception as original_error:
        backup_path = f"{path}.backup"
        if os.path.exists(backup_path):
            try:
                backup_raw = _load_raw_json(backup_path)
                recovered = normalize_loaded_config(backup_raw)
                save_config_file_atomic(path, recovered)
                raw = backup_raw
                logger.warning(
                    "설정 파일 복구 fallback 적용: %s -> %s",
                    backup_path,
                    path,
                )
            except Exception as backup_error:
                logger.error(
                    "설정 파일 복구 fallback 실패: original=%s, backup=%s",
                    original_error,
                    backup_error,
                )
                raise original_error
        else:
            raise

    cfg = normalize_loaded_config(raw)
    app_settings = cfg.get("app_settings", {})
    secret_value, needs_migration = resolve_client_secret_for_runtime(app_settings)
    if needs_migration and secret_value and _is_windows_platform():
        encoded_secret = encode_client_secret_for_storage(secret_value)
        app_settings["client_secret"] = encoded_secret["client_secret"]
        app_settings["client_secret_enc"] = encoded_secret["client_secret_enc"]
        app_settings["client_secret_storage"] = encoded_secret["client_secret_storage"]
        try:
            save_config_file_atomic(path, cfg)
        except Exception as e:
            logger.warning("DPAPI 마이그레이션 저장 실패: %s", e)
    return cfg


def save_config_file_atomic(path: str, config: AppConfig) -> None:
    _write_text_atomic(
        path,
        json.dumps(config, indent=4, ensure_ascii=False),
    )


def _write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def save_primary_config_file(path: str, config: AppConfig) -> None:
    """Save the main config atomically while keeping the previous valid file as .backup."""
    backup_path = f"{path}.backup"

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as src:
                current_text = src.read()
            loaded = json.loads(current_text)
            if isinstance(loaded, dict):
                _write_text_atomic(backup_path, current_text)
            else:
                logger.warning("기존 설정 파일이 JSON object가 아니어서 backup 회전을 건너뜁니다.")
        except Exception as e:
            logger.warning("기존 설정 backup 회전 생략: %s", e)

    save_config_file_atomic(path, config)
