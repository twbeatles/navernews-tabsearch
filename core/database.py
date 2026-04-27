import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from queue import Queue
from typing import Iterator, Optional, TYPE_CHECKING

from core._db_analytics import _DatabaseAnalyticsMixin
from core._db_duplicates import _DatabaseDuplicatesMixin
from core._db_mutations import _DatabaseMutationsMixin
from core._db_queries import _DatabaseQueriesMixin
from core._db_schema import _DatabaseSchemaMixin
from core.logging_setup import configure_logging


configure_logging()
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.workers import DBQueryScope


class NewsSnapshotBatchIterator:
    def __init__(
        self,
        db_manager: "DatabaseManager",
        conn,
        scope: "DBQueryScope",
        total_count: int,
        chunk_size: int,
    ):
        self._db_manager = db_manager
        self._conn = conn
        self._scope = scope
        self._total_count = max(0, int(total_count or 0))
        self._chunk_size = max(1, int(chunk_size or 1))
        self._closed = False

    def __iter__(self) -> Iterator[list[dict]]:
        offset = 0
        try:
            while offset < self._total_count:
                rows = self._db_manager.fetch_news(
                    conn=self._conn,
                    limit=self._chunk_size,
                    offset=offset,
                    **self._scope.fetch_kwargs(),
                )
                if not rows:
                    break
                offset += len(rows)
                yield rows
        finally:
            self.close()

    def __enter__(self) -> "NewsSnapshotBatchIterator":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._db_manager.close_read_connection(self._conn)


class DatabaseQueryError(RuntimeError):
    """Raised when a read/query-style DB operation fails."""

    def __init__(
        self,
        operation: str,
        message: str,
        *,
        cause: Optional[BaseException] = None,
    ):
        self.operation = str(operation or "database query")
        self.cause = cause
        super().__init__(f"{self.operation} failed: {message}")


class DatabaseWriteError(RuntimeError):
    """Raised when a write/mutation-style DB operation fails."""

    def __init__(
        self,
        operation: str,
        message: str,
        *,
        cause: Optional[BaseException] = None,
    ):
        self.operation = str(operation or "database write")
        self.cause = cause
        super().__init__(f"{self.operation} failed: {message}")


class DatabaseManager(
    _DatabaseSchemaMixin,
    _DatabaseDuplicatesMixin,
    _DatabaseQueriesMixin,
    _DatabaseMutationsMixin,
    _DatabaseAnalyticsMixin,
):
    """스레드 안전한 데이터베이스 매니저 (연결 풀 사용)"""

    def __init__(
        self,
        db_file: str,
        max_connections: int = 10,
        max_emergency_connections: int = 2,
    ):
        self.db_file = db_file
        self.max_connections = max_connections
        self.max_emergency_connections = max(0, int(max_emergency_connections))
        self.connection_pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._active_connections = 0
        self._closed = False
        self._emergency_connections = set()
        self._emergency_connection_uses = 0
        self._emergency_connection_rejections = 0

        if os.path.exists(self.db_file):
            integrity_result = self._check_integrity()
            if integrity_result.state == "corrupt":
                logger.error(
                    "데이터베이스 손상 확정. 복구를 시도합니다. detail=%s",
                    integrity_result.detail,
                )
                self._recover_database()
            elif integrity_result.state == "unreadable":
                logger.error(
                    "데이터베이스 무결성 검사를 수행하지 못했습니다. 자동 복구는 건너뜁니다. detail=%s",
                    integrity_result.detail,
                )

        self.init_db()

        for _ in range(max_connections):
            conn = self._create_connection()
            self.connection_pool.put(conn)

    def get_connection(self, timeout: float = 10.0):
        """연결 풀에서 연결 가져오기"""
        if self._closed:
            raise RuntimeError("DatabaseManager is closed")
        try:
            conn = self.connection_pool.get(timeout=timeout)
            with self._lock:
                self._active_connections += 1
            return conn
        except Exception as e:
            logger.warning(f"DB 연결 획득 실패 (timeout={timeout}s): {e}")
            logger.warning(f"활성 연결 수: {self._active_connections}/{self.max_connections}")
            with self._lock:
                active_emergency = len(self._emergency_connections)
                if active_emergency >= self.max_emergency_connections:
                    self._emergency_connection_rejections += 1
                    logger.error(
                        "DB emergency connection cap exceeded: active=%s/%s, rejects=%s",
                        active_emergency,
                        self.max_emergency_connections,
                        self._emergency_connection_rejections,
                    )
                    raise RuntimeError("Database connection pool exhausted") from e
            conn = self._create_connection()
            with self._lock:
                self._emergency_connections.add(id(conn))
                self._emergency_connection_uses += 1
                emergency_use_no = self._emergency_connection_uses
                active_emergency = len(self._emergency_connections)
            logger.warning(
                "비상 DB 연결 사용: #%s (active=%s/%s)",
                emergency_use_no,
                active_emergency,
                self.max_emergency_connections,
            )
            return conn

    @contextmanager
    def connection(self, timeout: float = 10.0):
        """Official context manager for pooled DB connection lifecycle."""
        conn = self.get_connection(timeout=timeout)
        try:
            yield conn
        finally:
            self.return_connection(conn)

    def return_connection(self, conn):
        """연결 풀에 연결 반환"""
        if conn is None:
            return

        conn_id = id(conn)
        with self._lock:
            if conn_id in self._emergency_connections:
                self._emergency_connections.discard(conn_id)
                try:
                    conn.close()
                    logger.debug("비상 연결 정리됨")
                except sqlite3.Error:
                    pass
                return

        if self._closed:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            return

        try:
            with self._lock:
                self._active_connections = max(0, self._active_connections - 1)
            if self.connection_pool.full():
                conn.close()
            else:
                self.connection_pool.put_nowait(conn)
        except Exception as e:
            logger.warning(f"DB 연결 반환 실패: {e}")
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def close(self):
        """모든 연결 종료"""
        self._closed = True
        closed_count = 0

        with self._lock:
            emergency_count = len(self._emergency_connections)
            if emergency_count > 0:
                logger.warning(f"비상 연결 {emergency_count}개가 정리되지 않고 남아있음")
            if self._emergency_connection_uses > 0 or self._emergency_connection_rejections > 0:
                logger.warning(
                    "비상 연결 통계: uses=%s, rejects=%s",
                    self._emergency_connection_uses,
                    self._emergency_connection_rejections,
                )
            self._emergency_connections.clear()

        try:
            while not self.connection_pool.empty():
                try:
                    conn = self.connection_pool.get_nowait()
                    conn.close()
                    closed_count += 1
                except (sqlite3.Error, Exception):
                    break
            logger.info(f"DB 연결 {closed_count}개 정상 종료")
        except Exception as e:
            logger.error(f"DB 종료 중 오류: {e}")

    def _new_query_error(
        self,
        operation: str,
        error: BaseException,
    ) -> DatabaseQueryError:
        return DatabaseQueryError(operation, str(error), cause=error)

    def _new_write_error(
        self,
        operation: str,
        error: BaseException,
    ) -> DatabaseWriteError:
        return DatabaseWriteError(operation, str(error), cause=error)

    def open_read_connection(self, timeout: float = 2.0):
        """Create a dedicated read connection that can be interrupted independently."""
        conn = sqlite3.connect(
            self.db_file,
            timeout=max(0.1, float(timeout)),
            check_same_thread=False,
        )
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute(f"PRAGMA busy_timeout={max(100, int(timeout * 1000))}")
        conn.row_factory = sqlite3.Row
        return conn

    def close_read_connection(self, conn) -> None:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    def interrupt_connection(self, conn) -> None:
        try:
            conn.interrupt()
        except Exception:
            pass

    def iter_news_snapshot_batches(
        self,
        scope: "DBQueryScope",
        chunk_size: int = 200,
        timeout: float = 5.0,
    ) -> tuple[int, NewsSnapshotBatchIterator]:
        """Iterate a stable snapshot for export/count style workflows."""
        conn = self.open_read_connection(timeout=timeout)
        try:
            conn.execute("BEGIN")
            total_count = int(self.count_news(conn=conn, **scope.count_kwargs()))
        except Exception:
            self.close_read_connection(conn)
            raise

        safe_chunk_size = max(1, int(chunk_size))

        return total_count, NewsSnapshotBatchIterator(self, conn, scope, total_count, safe_chunk_size)
