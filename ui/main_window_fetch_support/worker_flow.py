
"""Compatibility facade for MainApp fetch worker flow mixins."""

import time

from PyQt6.QtWidgets import QMessageBox

from core.workers import ApiWorker
from ui.main_window_fetch_support.worker_flow_support import (
    _FetchWorkerCompletionMixin,
    _FetchWorkerStartMixin,
    _FetchWorkerStateMixin,
)


class _MainWindowFetchWorkerMixin(
    _FetchWorkerStateMixin,
    _FetchWorkerStartMixin,
    _FetchWorkerCompletionMixin,
):
    """Composes fetch request state, startup, and completion handling."""


__all__ = ["ApiWorker", "QMessageBox", "_MainWindowFetchWorkerMixin", "time"]
