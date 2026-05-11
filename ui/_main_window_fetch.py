"""Compatibility facade for MainApp fetch orchestration."""

import time

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from core.workers import ApiWorker, retain_qthread_until_finished
from ui.main_window_fetch_support.mixin import _MainWindowFetchMixin

__all__ = ["_MainWindowFetchMixin"]
