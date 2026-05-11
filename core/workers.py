"""Compatibility facade for worker APIs.

Actual implementations live under ``core.workers_support`` so worker lifecycle,
HTTP policy, fetch workers, and DB query workers can evolve independently while
keeping legacy imports stable.
"""

import html
import ipaddress
import json
import logging
import re
import sqlite3
import threading
import time
import traceback
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, TypedDict, cast

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.database import DatabaseQueryError, DatabaseWriteError
from core.protocols import ClosableProtocol, RequestGetProtocol
from core.query_parser import build_fetch_key
from core.workers_support import (
    ApiErrorMeta,
    ApiWorker,
    AsyncJobWorker,
    DBQueryScope,
    DBWorker,
    InterruptibleReadWorker,
    IterativeJobWorker,
    JobCancelledError,
    LongTaskContext,
    MAX_FETCH_COOLDOWN_SECONDS,
    MAX_INLINE_RETRY_AFTER_SECONDS,
    RE_BOLD_TAGS,
    ReadConnectionProtocol,
    _safe_delete_later,
    _host_from_url,
    _is_disallowed_http_host,
    _is_naver_news_host,
    _is_naver_news_url,
    _normalized_http_url,
    _parse_retry_after_seconds,
    _publisher_from_naver_news_url,
    _publisher_from_url,
    _publisher_source_url,
    _retry_after_seconds_from_response,
    connect_qthread_finished,
    delete_qthread_when_finished,
    perf_timer,
    retain_qthread_until_finished,
    retain_worker_until_finished,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ApiErrorMeta",
    "ApiWorker",
    "AsyncJobWorker",
    "DBQueryScope",
    "DBWorker",
    "InterruptibleReadWorker",
    "IterativeJobWorker",
    "JobCancelledError",
    "LongTaskContext",
    "MAX_FETCH_COOLDOWN_SECONDS",
    "MAX_INLINE_RETRY_AFTER_SECONDS",
    "RE_BOLD_TAGS",
    "ReadConnectionProtocol",
    "_safe_delete_later",
    "connect_qthread_finished",
    "delete_qthread_when_finished",
    "perf_timer",
    "retain_qthread_until_finished",
    "retain_worker_until_finished",
    "_host_from_url",
    "_is_disallowed_http_host",
    "_is_naver_news_host",
    "_is_naver_news_url",
    "_normalized_http_url",
    "_parse_retry_after_seconds",
    "_publisher_from_naver_news_url",
    "_publisher_from_url",
    "_publisher_source_url",
    "_retry_after_seconds_from_response",
]
