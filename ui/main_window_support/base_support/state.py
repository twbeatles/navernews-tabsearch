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

logger = logging.getLogger(__name__)

@dataclass
class TabFetchState:
    last_api_start_index: int = 0

__all__ = ["TabFetchState"]
