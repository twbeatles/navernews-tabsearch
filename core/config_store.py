from __future__ import annotations

"""Compatibility facade for config storage APIs.

The implementation lives in ``core.config_store_impl`` so settings defaults,
normalization, secret handling, and file I/O can be split further without
changing existing imports.
"""

import os
from typing import Any, Dict, Mapping, Tuple

from core import config_store_impl as _impl
from core.config_store_impl import (
    AppConfig,
    AppSettings,
    DEFAULT_CONFIG,
    WindowGeometry,
    default_config,
    normalize_import_settings,
    normalize_loaded_config,
    save_config_file_atomic,
    save_primary_config_file,
)

_is_windows_platform = _impl._is_windows_platform
_dpapi_encrypt_text = _impl._dpapi_encrypt_text
_dpapi_decrypt_text = _impl._dpapi_decrypt_text


def _call_with_facade_secret_hooks(func, *args, **kwargs):
    old_is_windows = _impl._is_windows_platform
    old_encrypt = _impl._dpapi_encrypt_text
    old_decrypt = _impl._dpapi_decrypt_text
    _impl._is_windows_platform = _is_windows_platform
    _impl._dpapi_encrypt_text = _dpapi_encrypt_text
    _impl._dpapi_decrypt_text = _dpapi_decrypt_text
    try:
        return func(*args, **kwargs)
    finally:
        _impl._is_windows_platform = old_is_windows
        _impl._dpapi_encrypt_text = old_encrypt
        _impl._dpapi_decrypt_text = old_decrypt


def encode_client_secret_for_storage(client_secret: str) -> Dict[str, str]:
    return _call_with_facade_secret_hooks(_impl.encode_client_secret_for_storage, client_secret)


def resolve_client_secret_for_runtime(settings: Mapping[str, Any]) -> Tuple[str, bool]:
    return _call_with_facade_secret_hooks(_impl.resolve_client_secret_for_runtime, settings)


def load_config_file(path: str) -> AppConfig:
    return _call_with_facade_secret_hooks(_impl.load_config_file, path)

__all__ = [
    "AppConfig",
    "AppSettings",
    "DEFAULT_CONFIG",
    "WindowGeometry",
    "default_config",
    "encode_client_secret_for_storage",
    "load_config_file",
    "normalize_import_settings",
    "normalize_loaded_config",
    "resolve_client_secret_for_runtime",
    "save_config_file_atomic",
    "save_primary_config_file",
    "_is_windows_platform",
    "_dpapi_encrypt_text",
    "_dpapi_decrypt_text",
    "os",
]
