
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict

from core.config_store_support.normalization import default_config, normalize_loaded_config
from core.config_store_support.secrets import (
    _is_windows_platform,
    encode_client_secret_for_storage,
    resolve_client_secret_for_runtime,
)
from core.config_store_support.types import AppConfig

logger = logging.getLogger(__name__)


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

__all__ = [
    "load_config_file",
    "save_config_file_atomic",
    "_write_text_atomic",
    "save_primary_config_file",
]
