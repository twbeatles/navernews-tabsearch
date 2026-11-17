from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TabFetchState:
    last_api_start_index: int = 0


__all__ = ["TabFetchState"]
