"""Signed GitHub release manifest validation for the self-updater."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, cast
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.constants import UPDATE_MANIFEST_MAX_BYTES, UPDATE_REQUEST_TIMEOUT_SECONDS

_VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class NoUpdateAvailableError(ValueError):
    """Raised when a verified manifest is not newer than this build."""


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    version: str
    artifact_url: str
    artifact_sha256: str
    artifact_size: int
    expires_at: datetime
    signature: str


def canonical_manifest_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def is_newer_version(candidate: str, current: str) -> bool:
    def parse(value: str) -> tuple[int, ...]:
        if not _VERSION_PATTERN.fullmatch(str(value or "").strip()):
            raise ValueError(f"Invalid version: {value}")
        return tuple(int(part) for part in str(value).strip().split("."))

    left, right = parse(candidate), parse(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def verify_release_manifest(
    document: bytes | str | Mapping[str, Any],
    *,
    public_key: str,
    current_version: str,
    max_artifact_bytes: int,
    now: datetime | None = None,
) -> ReleaseManifest:
    raw = (
        document
        if isinstance(document, bytes)
        else (
            document.encode("utf-8")
            if isinstance(document, str)
            else canonical_manifest_payload(document)
        )
    )
    if len(raw) > UPDATE_MANIFEST_MAX_BYTES:
        raise ValueError("업데이트 정보가 허용 크기를 초과했습니다.")
    try:
        parsed_value: Any = (
            json.loads(raw.decode("utf-8"))
            if isinstance(raw, bytes)
            else dict(document)  # type: ignore[arg-type]
        )
        if not isinstance(parsed_value, Mapping):
            raise ValueError("manifest root is invalid")
        parsed = cast(Mapping[str, Any], parsed_value)
        if not isinstance(parsed.get("payload"), Mapping):
            raise ValueError("payload is missing")
        payload = dict(parsed["payload"])
        signature = base64.b64decode(str(parsed["signature"]), validate=True)
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key, validate=True)
        )
        key.verify(signature, canonical_manifest_payload(payload))
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        InvalidSignature,
    ) as exc:
        raise ValueError("업데이트 서명 검증에 실패했습니다.") from exc
    version = str(payload.get("version", "")).strip()
    if not is_newer_version(version, current_version):
        raise NoUpdateAvailableError("현재 버전이 최신입니다.")
    artifact_url = str(payload.get("artifact_url", "")).strip()
    url = urlsplit(artifact_url)
    if url.scheme != "https" or not url.hostname:
        raise ValueError("업데이트 파일 주소는 HTTPS여야 합니다.")
    sha256 = str(payload.get("sha256", "")).lower()
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("업데이트 파일 해시가 올바르지 않습니다.")
    try:
        size = int(payload.get("size", 0))
        expires_at = datetime.fromisoformat(
            str(payload.get("expires_at", "")).replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("업데이트 정보 형식이 올바르지 않습니다.") from exc
    if size <= 0 or size > max_artifact_bytes:
        raise ValueError("업데이트 파일 크기가 허용 범위를 벗어났습니다.")
    expires_at = (
        expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    )
    if expires_at <= (now or datetime.now(timezone.utc)):
        raise ValueError("업데이트 정보가 만료되었습니다.")
    return ReleaseManifest(
        version, artifact_url, sha256, size, expires_at, str(parsed["signature"])
    )


def download_release_manifest(url: str) -> bytes:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("업데이트 정보 주소는 HTTPS여야 합니다.")
    with urlopen(
        Request(url, headers={"User-Agent": "NaverNewsScraperPro-Updater"}),
        timeout=UPDATE_REQUEST_TIMEOUT_SECONDS,
    ) as response:
        if urlsplit(response.geturl()).scheme != "https":
            raise ValueError("업데이트 정보 리디렉션이 HTTPS가 아닙니다.")
        data = response.read(UPDATE_MANIFEST_MAX_BYTES + 1)
    if len(data) > UPDATE_MANIFEST_MAX_BYTES:
        raise ValueError("업데이트 정보가 허용 크기를 초과했습니다.")
    return data
