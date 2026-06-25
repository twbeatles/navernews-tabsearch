
from __future__ import annotations

import base64
import ctypes
import logging
import sys
from typing import Any, Dict, Mapping, Tuple

logger = logging.getLogger(__name__)


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


def client_secret_uses_plain_storage(settings: Mapping[str, Any]) -> bool:
    storage = _normalize_secret_storage(settings.get("client_secret_storage", "plain"))
    if storage != "plain":
        return False
    plain = str(settings.get("client_secret", "") or "").strip()
    encrypted = str(settings.get("client_secret_enc", "") or "").strip()
    return bool(plain or encrypted)


def should_warn_plain_client_secret_storage(settings: Mapping[str, Any]) -> bool:
    if _is_windows_platform():
        return False
    if not client_secret_uses_plain_storage(settings):
        return False
    plain = str(settings.get("client_secret", "") or "").strip()
    encrypted = str(settings.get("client_secret_enc", "") or "").strip()
    return bool(plain or encrypted)


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

__all__ = [
    "_is_windows_platform",
    "_normalize_secret_storage",
    "_dpapi_encrypt_text",
    "_dpapi_decrypt_text",
    "client_secret_uses_plain_storage",
    "encode_client_secret_for_storage",
    "resolve_client_secret_for_runtime",
    "should_warn_plain_client_secret_storage",
]
