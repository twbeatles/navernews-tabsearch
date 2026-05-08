import warnings

warnings.warn(
    "Root worker_registry imports are deprecated; use core.worker_registry instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.worker_registry import WorkerHandle, WorkerRegistry

__all__ = ['WorkerHandle', 'WorkerRegistry']
