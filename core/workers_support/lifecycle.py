import logging
import time
from typing import Any, Callable, Dict

from PySide6.QtCore import QThread, QTimer, Signal

logger = logging.getLogger(__name__)
_DETACHED_WORKERS: Dict[int, Any] = {}
_ACTIVE_FINISH_WATCHERS: set = set()


def request_background_shutdown(workers: Any, wait_ms: int = 1000) -> bool:
    """Cancel owned workers and confirm native thread exit within one time budget.

    A result/settled signal may be emitted before run() returns. Only wait()
    or a stopped native thread permits closing its database or QObject parent.
    The caller keeps the event loop and parent alive when this returns False.
    """
    candidates = list(workers)
    for retained in list(_DETACHED_WORKERS.values()):
        candidates.extend(retained if isinstance(retained, tuple) else (retained,))
    pending = []
    seen = set()
    for worker in candidates:
        if worker is None:
            continue
        if id(worker) in seen or not callable(getattr(worker, "isRunning", None)):
            continue
        seen.add(id(worker))
        try:
            if worker.isRunning():
                pending.append(worker)
                request = getattr(worker, "requestInterruption", None)
                if callable(request):
                    request()
                quit_thread = getattr(worker, "quit", None)
                if callable(quit_thread):
                    quit_thread()
        except RuntimeError:
            continue  # Already deleted by its native-finished cleanup.
    deadline = time.monotonic() + max(0, wait_ms) / 1000
    complete = True
    for worker in pending:
        try:
            if not worker.wait(max(0, int((deadline - time.monotonic()) * 1000))):
                complete = False
        except RuntimeError:
            continue
    return complete

def _safe_delete_later(obj: Any) -> None:
    try:
        obj.deleteLater()
    except Exception:
        pass
def _declares_shadowed_finished(worker: Any) -> bool:
    """Detect a subclass result signal named finished shadowing QThread.finished."""
    for klass in type(worker).__mro__:
        if klass is QThread:
            return False
        if isinstance(klass.__dict__.get("finished"), Signal):
            return True
    return False


def _watch_finished_by_polling(worker: Any, slot: Callable[..., Any]) -> bool:
    """Fire slot once the native thread reports finished, without signals.

    PySide6 resolves QThread.finished.__get__ by instance type and name, so a
    shadowed finished always binds the subclass result signal and the native
    no-arg finished() is unreachable from Python. Poll isFinished() instead so
    result-signal emissions never trigger premature cleanup.
    """
    try:
        timer = QTimer()
        timer.setInterval(50)
    except Exception:
        return False
    _ACTIVE_FINISH_WATCHERS.add(timer)

    def _stop() -> None:
        _ACTIVE_FINISH_WATCHERS.discard(timer)
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timer.deleteLater()
        except Exception:
            pass

    def _check() -> None:
        try:
            finished = worker.isFinished()
        except Exception:
            _stop()
            return
        if finished:
            _stop()
            try:
                slot()
            except Exception:
                logger.exception("qthread finished slot failed")

    try:
        timer.timeout.connect(_check)
        timer.start()
        return True
    except Exception:
        _stop()
        return False


def connect_qthread_finished(worker: Any, slot: Callable[..., Any]) -> bool:
    """Connect to QThread.finished even when subclasses define result signals named finished."""
    if not isinstance(worker, QThread):
        return False
    if _declares_shadowed_finished(worker):
        return _watch_finished_by_polling(worker, slot)
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
