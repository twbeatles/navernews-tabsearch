from __future__ import annotations

from typing import Any, Protocol


class LockFileProtocol(Protocol):
    def removeStaleLockFile(self) -> bool | None:
        ...

    def tryLock(self, timeout: int) -> bool:
        ...


class RequestGetProtocol(Protocol):
    def get(self, *args: Any, **kwargs: Any) -> Any:
        ...


class ClosableProtocol(Protocol):
    def close(self) -> None:
        ...
