"""Compatibility facade for worker APIs.

Actual implementations live under ``core.workers_support`` so worker lifecycle,
HTTP policy, fetch workers, and DB query workers can evolve independently while
keeping legacy imports stable.
"""

import logging
import time  # noqa: F401 # patched by tests (core.workers.time)

from core.workers_support import (
    MAX_FETCH_COOLDOWN_SECONDS,
    MAX_INLINE_RETRY_AFTER_SECONDS,
    RE_BOLD_TAGS,
    ApiErrorMeta,
    ApiWorker,
    AsyncJobWorker,
    DBQueryScope,
    DBWorker,
    InterruptibleReadWorker,
    IterativeJobWorker,
    JobCancelledError,
    LongTaskContext,
    ReadConnectionProtocol,
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
    _safe_delete_later,
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
