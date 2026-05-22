# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import html
import logging
import time
import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import QMutexLocker, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query, parse_tab_query
from core.text_utils import RE_HTML_TAGS
from core.validation import ValidationUtils
from core.worker_registry import WorkerHandle
from core.workers import ApiWorker, retain_qthread_until_finished

if TYPE_CHECKING:
    from ui.main_window import MainApp

logger = logging.getLogger(__name__)


class _FetchWorkerStateMixin:
    def _next_worker_request_id(self: MainApp) -> int:
        self._worker_request_seq += 1
        return self._worker_request_seq

    def _is_active_worker_request(
        self: MainApp,
        keyword: str,
        request_id: Optional[int],
    ) -> bool:
        if request_id is None:
            return True
        return self._worker_registry.is_active(keyword, request_id)

    def _compute_load_more_state(
        self: MainApp,
        total: Optional[int],
        last_api_start_index: int,
    ) -> bool:
        last_api_start_index = max(0, int(last_api_start_index or 0))
        next_start = last_api_start_index + 100
        if next_start > 1000:
            return False
        if total is None:
            return True
        return next_start <= min(1000, max(0, int(total or 0)))

    def _apply_load_more_button_state(
        self: MainApp,
        tab_widget,
        total: Optional[int],
        last_api_start_index: int,
    ) -> bool:
        is_maintenance_active = getattr(self, "is_maintenance_mode_active", lambda: False)
        if is_maintenance_active():
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("🔒 유지보수 중")
            return False

        has_more = self._compute_load_more_state(total, last_api_start_index)
        if has_more:
            tab_widget.btn_load.setEnabled(True)
            tab_widget.btn_load.setText("📄 더 불러오기")
        else:
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("📄 마지막 페이지")
        return has_more
