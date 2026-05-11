import logging
import sqlite3
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, Optional, Protocol, cast

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

class ReadConnectionProtocol(Protocol):
    def execute(self, sql: str) -> Any:
        ...

    def close(self) -> None:
        ...
@contextmanager
def perf_timer(scope: str, meta: str = ""):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(f"PERF|{scope}|{elapsed_ms:.2f}ms|{meta}")
class AsyncJobWorker(QThread):
    """단발성 비동기 작업 수행 워커"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    settled = pyqtSignal()

    def __init__(self, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            result = self.job_func(*self.args, **self.kwargs)
            if self.isInterruptionRequested():
                return
            self.finished.emit(result)
        except Exception as e:
            if self.isInterruptionRequested():
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        self.quit()
        self.wait(100)
class JobCancelledError(Exception):
    """Raised when a long-running worker is cancelled cooperatively."""
class LongTaskContext:
    """Cancellation/progress helper passed to repetitive background jobs."""

    def __init__(self, worker: "IterativeJobWorker"):
        self._worker = worker

    def is_cancelled(self) -> bool:
        return self._worker.isInterruptionRequested()

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelledError("cancelled")

    def report(
        self,
        *,
        current: int = 0,
        total: int = 0,
        message: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        progress_payload: Dict[str, Any] = {
            "current": max(0, int(current)),
            "total": max(0, int(total)),
            "message": str(message or ""),
        }
        if payload:
            progress_payload.update(payload)
        self._worker.progress.emit(progress_payload)
class IterativeJobWorker(QThread):
    """Cancel-aware worker for repetitive or chunked background tasks."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(object)
    cancelled = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        context = LongTaskContext(self)
        try:
            context.check_cancelled()
            result = self.job_func(context, *self.args, **self.kwargs)
            context.check_cancelled()
            self.finished.emit(result)
        except JobCancelledError:
            self.cancelled.emit()
        except Exception as e:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        self.quit()
        self.wait(100)
class InterruptibleReadWorker(QThread):
    """Dedicated read worker backed by an interruptible SQLite connection."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, db_manager, job_func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.db = db_manager
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
        self._conn: Optional[ReadConnectionProtocol] = None

    def run(self):
        try:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return

            open_read_connection = getattr(self.db, "open_read_connection", None)
            conn: Optional[ReadConnectionProtocol]
            if callable(open_read_connection):
                conn = cast(Optional[ReadConnectionProtocol], open_read_connection(timeout=1.5))
            else:
                conn = None
            self._conn = conn
            if conn is not None:
                conn.execute("BEGIN")

            result = self.job_func(conn, *self.args, **self.kwargs)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except JobCancelledError:
            self.cancelled.emit()
        except sqlite3.OperationalError as e:
            interrupted = "interrupted" in str(e).lower()
            if self.isInterruptionRequested() or interrupted:
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        except Exception as e:
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.error.emit(str(e))
            traceback.print_exc()
        finally:
            conn = self._conn
            self._conn = None
            if conn is not None:
                try:
                    close_read_connection = getattr(self.db, "close_read_connection", None)
                    if callable(close_read_connection):
                        close_read_connection(conn)
                    else:
                        conn.close()
                except Exception:
                    pass
            self.settled.emit()

    def stop(self):
        self.requestInterruption()
        if self._conn is not None:
            try:
                interrupt_connection = getattr(self.db, "interrupt_connection", None)
                if callable(interrupt_connection):
                    interrupt_connection(self._conn)
            except Exception:
                pass
        self.quit()
        self.wait(100)
