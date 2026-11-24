"""NAVER API HUB Search API 일일 호출량 추적.

공식 문서 기준 Search API 일일 호출 한도는 25,000건이다.
한도 초과는 429/오류로 사후 대응만 가능하므로, 실제 HTTP 요청 건수를
날짜별로 집계해 사전에 잔여량을 보여주고 한도 도달 시 차단을 돕는다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# 공식 문서: Search API 하루 호출 한도 25,000회
DAILY_API_CALL_LIMIT = 25000
# 사용량이 이 비율에 도달하면 1회 경고를 보낸다.
QUOTA_WARN_RATIO = 0.8


def _today_key(now: datetime | None = None) -> str:
    return (now or datetime.now()).date().isoformat()


class DailyApiQuotaTracker:
    """날짜별 API 호출 건수를 세고 JSON 파일에 영속화한다."""

    def __init__(self, path: str | None = None) -> None:
        self._path = str(path or "").strip() or None
        self._date = _today_key()
        self._count = 0
        self._warned = False
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("API quota state ignored (unreadable): %s", exc)
            return
        if not isinstance(payload, dict):
            return
        if str(payload.get("date") or "") == self._date:
            try:
                self._count = max(0, int(payload.get("count", 0) or 0))
            except (TypeError, ValueError):
                self._count = 0
            self._warned = bool(payload.get("warned", False))

    def _save(self) -> None:
        if not self._path:
            return
        payload: Dict[str, Any] = {
            "date": self._date,
            "count": int(self._count),
            "warned": bool(self._warned),
        }
        directory = os.path.dirname(os.path.abspath(self._path)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=".api_quota_", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self._path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("API quota state not saved: %s", exc)

    def _rollover_if_needed(self) -> None:
        today = _today_key()
        if today != self._date:
            self._date = today
            self._count = 0
            self._warned = False
            self._save()

    def record_call(self, count: int = 1) -> Tuple[int, int]:
        """실제 HTTP 요청 건수를 기록하고 (호출수, 잔여)를 반환한다."""
        self._rollover_if_needed()
        self._count = max(0, int(self._count) + max(0, int(count or 0)))
        self._save()
        return self._count, self.remaining

    @property
    def count(self) -> int:
        self._rollover_if_needed()
        return int(self._count)

    @property
    def remaining(self) -> int:
        return max(0, DAILY_API_CALL_LIMIT - self.count)

    @property
    def is_exhausted(self) -> bool:
        return self.count >= DAILY_API_CALL_LIMIT

    def should_warn(self) -> bool:
        """경고 임계 최초 도달 시 True를 1회 반환한다."""
        self._rollover_if_needed()
        if self._warned:
            return False
        if self._count < int(DAILY_API_CALL_LIMIT * QUOTA_WARN_RATIO):
            return False
        self._warned = True
        self._save()
        return True

    def usage(self) -> Tuple[str, int, int]:
        """(날짜, 호출수, 잔여) 스냅샷을 반환한다."""
        self._rollover_if_needed()
        return self._date, int(self._count), self.remaining

    def summary_text(self) -> str:
        """설정 화면에 보여줄 한 줄 요약."""
        _date, count, remaining = self.usage()
        return (
            f"오늘 API 호출: {count:,} / {DAILY_API_CALL_LIMIT:,}건"
            f" (잔여 {remaining:,}건)"
        )


__all__ = [
    "DAILY_API_CALL_LIMIT",
    "QUOTA_WARN_RATIO",
    "DailyApiQuotaTracker",
]
