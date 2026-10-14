from __future__ import annotations

from typing import Any, Protocol


class LockFileProtocol(Protocol):
    def removeStaleLockFile(self) -> bool | None:
        ...

    # QLockFile.tryLock 스텁은 timeout을 위치 전용으로 선언하므로 맞춘다.
    def tryLock(self, timeout: int, /) -> bool:
        ...


class RequestGetProtocol(Protocol):
    def get(self, *args: Any, **kwargs: Any) -> Any:
        ...


class ClosableProtocol(Protocol):
    def close(self) -> None:
        ...
