"""Create the signed `updates/latest.json` used by released Windows builds."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.update_manifest import canonical_manifest_payload, is_newer_version  # noqa: E402


def _private_key(env_name: str) -> Ed25519PrivateKey:
    encoded = os.environ.get(env_name, "").strip()
    if not encoded:
        raise ValueError(f"환경 변수 {env_name}이 설정되지 않았습니다.")
    return Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(encoded, validate=True)
    )


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a signed News Scraper Pro update manifest"
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--private-key-env", default="NEWS_SCRAPER_UPDATE_PRIVATE_KEY_B64"
    )
    parser.add_argument("--expires-in-days", type=int, default=365)
    args = parser.parse_args(argv)
    # Reuse the updater's strict numeric version parser.
    is_newer_version(args.version, "0")
    artifact = args.artifact.resolve()
    if (
        artifact.suffix.lower() != ".exe"
        or not artifact.is_file()
        or not args.artifact_url.startswith("https://")
    ):
        raise ValueError(
            "artifact must be an existing .exe and artifact-url must use HTTPS"
        )
    if args.expires_in_days <= 0:
        raise ValueError("expires-in-days must be positive")
    sha256, size = _hash_file(artifact)
    payload = {
        "version": args.version,
        "artifact_url": args.artifact_url,
        "sha256": sha256,
        "size": size,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(days=args.expires_in_days)
        )
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    signature = base64.b64encode(
        _private_key(args.private_key_env).sign(canonical_manifest_payload(payload))
    ).decode("ascii")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"payload": payload, "signature": signature},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
