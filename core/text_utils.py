import html
import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Dict

from core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

RE_HTML_TAGS = re.compile(r'<[^>]+>')
RE_WHITESPACE = re.compile(r'\s+')
RE_BOLD_TAGS = re.compile(r'</?b>')

DATE_FORMATS = (
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d',
)
DATE_OUTPUT_FORMAT = '%Y.%m.%d %H:%M'

@contextmanager
def perf_timer(scope: str, meta: str = ""):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(f"PERF|{scope}|{elapsed_ms:.2f}ms|{meta}")


def parse_date_string(date_str: str) -> str:
    """날짜 문자열 파싱 헬퍼 함수 (RFC 2822 및 여러 포맷 지원)"""
    if not date_str:
        return ""
    try:
        # RFC 2822 형식 먼저 시도 (네이버 API 기본 형식)
        dt = parsedate_to_datetime(date_str)
        return dt.strftime(DATE_OUTPUT_FORMAT)
    except (ValueError, TypeError):
        # 대체 포맷들 시도
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.strftime(DATE_OUTPUT_FORMAT)
            except (ValueError, TypeError):
                continue
    
    # 추가: 한국어 날짜 형식 등 기타 포맷 시도 (필요시 확장)
    
    return date_str  # 파싱 실패 시 원본 반환


def parse_date_to_ts(date_str: str) -> float:
    """날짜 문자열을 타임스탬프로 변환 (정렬용)"""
    if not date_str:
        return 0.0
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.timestamp()
            except (ValueError, TypeError):
                continue
    return 0.0


@lru_cache(maxsize=64)
def get_highlight_pattern(keyword: str) -> re.Pattern:
    """하이라이트 패턴 캐시 반환 (LRU 캐시 사용)"""
    return re.compile(f'({re.escape(keyword)})', re.IGNORECASE)


class TextUtils:
    """텍스트 처리 유틸리티"""
    
    @staticmethod
    def highlight_text(text: str, keyword: str) -> str:
        """텍스트에서 키워드 하이라이팅 (캐시된 패턴 사용)"""
        if not keyword:
            return html.escape(text)
        
        escaped_text = html.escape(text)
        escaped_keyword = html.escape(keyword)
        
        # 캐시된 패턴 사용 (성능 최적화)
        pattern = get_highlight_pattern(escaped_keyword)
        highlighted = pattern.sub(r"<span class='highlight'>\1</span>", escaped_text)
        
        return highlighted

