import logging
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.workers_support.jobs import perf_timer
from core.workers_support.query_scope import DBQueryScope

logger = logging.getLogger(__name__)

class DBWorker(QThread):
    """DB 조회 전용 워커 스레드(UI 블로킹 방지)"""

    finished = pyqtSignal(list, int)
    error = pyqtSignal(str)
    settled = pyqtSignal()

    def __init__(
        self,
        db_manager,
        scope: DBQueryScope,
        limit: Optional[int] = None,
        offset: int = 0,
        include_total: bool = True,
        known_total_count: Optional[int] = None,
    ):
        super().__init__()
        self.db = db_manager
        self.scope = scope
        self.limit = limit
        self.offset = offset
        self.include_total = include_total
        self.known_total_count = known_total_count
        self._is_cancelled = False
        self.last_unread_count = 0
        self._conn = None

    def stop(self):
        self._is_cancelled = True
        if self._conn is not None:
            try:
                interrupt_connection = getattr(self.db, "interrupt_connection", None)
                if callable(interrupt_connection):
                    interrupt_connection(self._conn)
            except Exception:
                pass
        self.quit()
        self.wait(100)

    def run(self):
        try:
            with perf_timer(
                "ui.dbworker.run",
                f"kw={self.scope.keyword}|bookmark={int(self.scope.only_bookmark)}|include_total={int(self.include_total)}",
            ):
                if self._is_cancelled:
                    return

                open_read_connection = getattr(self.db, "open_read_connection", None)
                conn: Any
                if callable(open_read_connection):
                    conn = open_read_connection(timeout=1.5)
                else:
                    conn = None
                self._conn = conn
                if conn is not None:
                    conn.execute("BEGIN")

                if not self.scope.only_bookmark and not str(self.scope.keyword or "").strip():
                    self.finished.emit([], 0)
                    return

                count_kwargs = self.scope.count_kwargs()
                total_count = int(self.known_total_count or 0)
                if self.include_total:
                    total_count = self.db.count_news(conn=conn, **self.scope.count_kwargs())

                if count_kwargs.get("only_unread", False):
                    unread_count = total_count
                else:
                    unread_count_kwargs = dict(count_kwargs)
                    unread_count_kwargs["only_unread"] = True
                    unread_count = self.db.count_news(conn=conn, **unread_count_kwargs)
                self.last_unread_count = int(unread_count or 0)

                if self._is_cancelled:
                    return

                data = self.db.fetch_news(
                    conn=conn,
                    limit=self.limit,
                    offset=self.offset,
                    **self.scope.fetch_kwargs(),
                )

                if self._is_cancelled:
                    return

                self.finished.emit(data, total_count)
        except Exception as e:
            if self._is_cancelled or "interrupted" in str(e).lower():
                logger.info("DBWorker cancelled during query: %s", self.scope.keyword)
                return
            logger.exception("DBWorker failed: %s", self.scope.keyword)
            self.error.emit(str(e))
        finally:
            if self._conn is not None:
                try:
                    close_read_connection = getattr(self.db, "close_read_connection", None)
                    if callable(close_read_connection):
                        close_read_connection(self._conn)
                except Exception:
                    pass
                self._conn = None
            self.settled.emit()
