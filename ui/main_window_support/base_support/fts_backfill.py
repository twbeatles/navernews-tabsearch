# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterator, List, Optional

from PyQt6.QtCore import QMutexLocker, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QStatusBar, QStyle, QTabBar, QWidget

from core.database import DatabaseManager
from core.http_client import HttpClientConfig
from core.workers import IterativeJobWorker
from ui.news_tab import NewsTab
from ui.toast import ToastQueue
from ui.main_window_support.base_support.accessors import _MainWindowBaseAccessorsMixin

logger = logging.getLogger(__name__)

from ui.main_window_support.base_support.state import TabFetchState


class _MainWindowFtsBackfillMixin:
    def _start_fts_backfill(self) -> None:
        if self._shutdown_in_progress:
            return
        worker = getattr(self, "_fts_backfill_worker", None)
        if worker is not None and worker.isRunning():
            return
        if self._require_db().is_news_fts_backfill_complete():
            self._fts_backfill_retry_attempt = 0
            self._fts_backfill_pause_requested = False
            if self._fts_backfill_retry_timer.isActive():
                self._fts_backfill_retry_timer.stop()
            return
        if self._is_fts_backfill_paused():
            self._schedule_fts_backfill_retry(max(1000, int(self._fts_backfill_pause_delay_ms or 1000)))
            return
        if self._fts_backfill_retry_timer.isActive():
            self._fts_backfill_retry_timer.stop()

        def _job(context):
            total_processed = 0
            while True:
                context.check_cancelled()
                result = self._require_db().backfill_news_fts_chunk(limit=250)
                processed = int(result.get("processed", 0) or 0)
                total_processed += processed
                context.report(current=total_processed, total=0, message="FTS backfill running")
                if bool(result.get("done", False)) or processed <= 0:
                    return {"processed": total_processed, "done": True}

        worker_cls = _MainWindowBaseAccessorsMixin._iterative_job_worker_cls(self)
        self._fts_backfill_worker = worker_cls(_job, parent=self)
        self._fts_backfill_worker.finished.connect(self._on_fts_backfill_finished)
        self._fts_backfill_worker.error.connect(self._on_fts_backfill_error)
        self._fts_backfill_worker.cancelled.connect(self._on_fts_backfill_cancelled)
        self._fts_backfill_worker.start()

    def _on_fts_backfill_finished(self, _result) -> None:
        self._fts_backfill_worker = None
        self._fts_backfill_retry_attempt = 0
        self._fts_backfill_pause_requested = False
        if self._fts_backfill_retry_timer.isActive():
            self._fts_backfill_retry_timer.stop()

    def _on_fts_backfill_error(self, error_msg: str) -> None:
        logger.warning("FTS backfill failed: %s", error_msg)
        self._fts_backfill_worker = None
        self._fts_backfill_pause_requested = False
        self._fts_backfill_retry_attempt += 1
        self._schedule_fts_backfill_retry(self._next_fts_backfill_retry_delay_ms(), force=True)

    def _on_fts_backfill_cancelled(self) -> None:
        self._fts_backfill_worker = None
        if self._shutdown_in_progress:
            self._fts_backfill_pause_requested = False
            return
        if self._fts_backfill_pause_requested:
            delay_ms = max(0, int(self._fts_backfill_pause_delay_ms or 0))
            self._fts_backfill_pause_requested = False
            self._request_fts_backfill_resume(delay_ms=max(250, delay_ms))

    def _is_fts_backfill_paused(self) -> bool:
        if self._shutdown_in_progress:
            return True
        if self.is_maintenance_mode_active():
            return True
        if self._refresh_in_progress or self._sequential_refresh_active:
            return True
        return False

    def _next_fts_backfill_retry_delay_ms(self) -> int:
        attempt = max(1, int(getattr(self, "_fts_backfill_retry_attempt", 0) or 0))
        if attempt <= 1:
            return 5000
        if attempt == 2:
            return 15000
        return 30000

    def _schedule_fts_backfill_retry(self, delay_ms: int, *, force: bool = False) -> None:
        if self._shutdown_in_progress:
            return
        if self._require_db().is_news_fts_backfill_complete():
            return
        timer = getattr(self, "_fts_backfill_retry_timer", None)
        if timer is None:
            return
        safe_delay = max(0, int(delay_ms))
        if timer.isActive():
            remaining = timer.remainingTime()
            if not force and 0 <= remaining <= safe_delay:
                return
            timer.stop()
        timer.start(safe_delay)

    def _request_fts_backfill_resume(self, *, delay_ms: int = 250) -> None:
        if self._shutdown_in_progress:
            return
        if self._require_db().is_news_fts_backfill_complete():
            return
        if self._is_fts_backfill_paused():
            self._schedule_fts_backfill_retry(max(1000, int(delay_ms)))
            return
        self._schedule_fts_backfill_retry(delay_ms)

    def _pause_fts_backfill(self, *, retry_delay_ms: int = 1000) -> None:
        if self._shutdown_in_progress:
            return
        self._fts_backfill_pause_delay_ms = max(250, int(retry_delay_ms))
        worker = getattr(self, "_fts_backfill_worker", None)
        if worker is None or not worker.isRunning():
            self._request_fts_backfill_resume(delay_ms=self._fts_backfill_pause_delay_ms)
            return
        self._fts_backfill_pause_requested = True
        try:
            worker.requestInterruption()
        except Exception:
            pass
