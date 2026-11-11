import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.update_manifest import (
    NoUpdateAvailableError,
    canonical_manifest_payload,
    verify_release_manifest,
)


def _document(version: str = "32.7.8") -> tuple[dict[str, object], str]:
    key = Ed25519PrivateKey.generate()
    payload = {
        "version": version,
        "artifact_url": "https://github.com/twbeatles/navernews-tabsearch/releases/download/v32.7.8/NewsScraperPro_Safe.exe",
        "sha256": "a" * 64,
        "size": 100,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    signature = base64.b64encode(key.sign(canonical_manifest_payload(payload))).decode()
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return {"payload": payload, "signature": signature}, public


def test_verifies_a_signed_newer_manifest():
    document, public = _document()
    manifest = verify_release_manifest(json.dumps(document), public_key=public, current_version="32.7.7", max_artifact_bytes=1000)
    assert manifest.version == "32.7.8"


def test_rejects_tampered_manifest():
    document, public = _document()
    document["payload"]["size"] = 101  # type: ignore[index]
    with pytest.raises(ValueError, match="서명"):
        verify_release_manifest(document, public_key=public, current_version="32.7.7", max_artifact_bytes=1000)


def test_rejects_non_upgrade_after_signature_verification():
    document, public = _document("32.7.7")
    with pytest.raises(NoUpdateAvailableError):
        verify_release_manifest(document, public_key=public, current_version="32.7.7", max_artifact_bytes=1000)


@pytest.mark.parametrize("document", [[], {"payload": []}, {"payload": {}}])
def test_rejects_malformed_manifest_documents(document: object):
    with pytest.raises(ValueError):
        verify_release_manifest(document, public_key="not-a-key", current_version="32.7.7", max_artifact_bytes=1000)  # type: ignore[arg-type]
