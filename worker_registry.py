import warnings
from core.worker_registry import WorkerHandle, WorkerRegistry

warnings.warn(
    "Root worker_registry imports are deprecated; use core.worker_registry instead.",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ['WorkerHandle', 'WorkerRegistry']
