from __future__ import annotations

import getpass
import hashlib
import os
import platform


def get_machine_identity() -> str:
    """Return a stable non-secret machine/user identity for portable settings import policy."""
    parts = [
        platform.node(),
        getpass.getuser(),
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERDOMAIN", ""),
    ]
    raw = "|".join(part.strip().lower() for part in parts if str(part or "").strip())
    if not raw:
        raw = "unknown"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
