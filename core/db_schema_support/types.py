
from __future__ import annotations

from typing import NamedTuple


class IntegrityCheckResult(NamedTuple):
    state: str
    detail: str = ""


__all__ = ["IntegrityCheckResult"]
