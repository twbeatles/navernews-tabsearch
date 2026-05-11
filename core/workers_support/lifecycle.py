import logging
from typing import Any, Callable, Dict

from PyQt6.QtCore import QThread

logger = logging.getLogger(__name__)
_DETACHED_WORKERS: Dict[int, Any] = {}

def _safe_delete_later(obj: Any) -> None:
    try:
        obj.deleteLater()
    except Exception:
        pass
def connect_qthread_finished(worker: Any, slot: Callable[..., Any]) -> bool:
    """Connect to QThread.finished even when subclasses define result signals named finished."""
    if not isinstance(worker, QThread):
        return False
    try:
        finished_signal = QThread.finished.__get__(worker, type(worker))
        finished_signal.connect(slot)
        return True
    except Exception:
        return False
def delete_qthread_when_finished(worker: Any) -> bool:
    """Delete a QThread subclass only after Qt reports the native thread has finished."""
    return connect_qthread_finished(worker, lambda *_args: _safe_delete_later(worker))
def retain_worker_until_finished(worker: Any) -> None:
    """Keep a detached QThread subclass alive until its run method settles."""
    if worker is None:
        return
    key = id(worker)
    _DETACHED_WORKERS[key] = worker

    def release(*_args: Any) -> None:
        retained = _DETACHED_WORKERS.pop(key, None)
        if retained is not None:
            _safe_delete_later(retained)

    connected = connect_qthread_finished(worker, release)
    settled = getattr(worker, "settled", None)
    if not connected and settled is not None:
        try:
            settled.connect(release)
            connected = True
        except Exception:
            connected = False

    if not connected:
        for signal_name in ("finished", "error", "cancelled"):
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(release)
                connected = True
            except Exception:
                pass

    try:
        if not worker.isRunning():
            release()
    except Exception:
        if not connected:
            release()
def retain_qthread_until_finished(thread: Any, *objects: Any) -> None:
    """Keep a QThread and moved worker alive after a cancellation timeout."""
    if thread is None:
        return
    retained_objects = tuple(obj for obj in (thread, *objects) if obj is not None)
    key = id(thread)
    _DETACHED_WORKERS[key] = retained_objects

    def release(*_args: Any) -> None:
        retained = _DETACHED_WORKERS.pop(key, ())
        for obj in retained:
            _safe_delete_later(obj)

    try:
        thread.finished.connect(release)
    except Exception:
        pass
    try:
        if not thread.isRunning():
            release()
    except Exception:
        pass
