
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from core.publisher_aliases import expand_publisher_filters
from core.text_utils import perf_timer

if TYPE_CHECKING:
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)
RE_FTS_ACCEL_TOKEN = re.compile(r"[0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3]{2,}")


class _DatabaseQueryFilterMixin:
    def _active_news_clause(self: DatabaseManager, alias: str = "n") -> str:
        return f"COALESCE({alias}.is_deleted, 0) = 0"

    def _escape_like(self: DatabaseManager, value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _like_contains(self: DatabaseManager, value: str) -> str:
        return f"%{self._escape_like(value)}%"

    def _filter_tokens(self: DatabaseManager, filter_txt: str) -> List[str]:
        raw = str(filter_txt or "").strip()
        if not raw:
            return []
        return [token.strip() for token in RE_FTS_ACCEL_TOKEN.findall(raw) if token.strip()]

    def _fts_match_expression(self: DatabaseManager, filter_txt: str) -> str:
        # Keep the FTS schema/backfill path available for future ranking or
        # acceleration work, but do not use it as a hard rowid prefilter.
        # The user-facing search contract is token-AND substring matching via
        # LIKE; an FTS MATCH prefilter can drop Korean compound-word results
        # and make results differ before/after backfill.
        return ""

    def _append_text_filter_clause(
        self: DatabaseManager,
        params: List[Any],
        filter_txt: str,
    ) -> str:
        raw = str(filter_txt or "").strip()
        if not raw:
            return ""
        tokens = [] if any(char in raw for char in ("%","_","\\")) else self._filter_tokens(raw)
        if len(tokens) >= 2:
            clauses: List[str] = []
            for token in tokens:
                clauses.append("(n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')")
                wildcard = self._like_contains(token)
                params.extend([wildcard, wildcard])
            return " AND " + " AND ".join(clauses)
        wildcard = self._like_contains(raw)
        params.extend([wildcard, wildcard])
        return " AND (n.title LIKE ? ESCAPE '\\' OR n.description LIKE ? ESCAPE '\\')"

    def _append_news_scope_clause(
        self: DatabaseManager,
        params: List[Any],
        keyword: str,
        query_key: Optional[str],
        alias: str = "nk",
    ) -> str:
        normalized_query_key = str(query_key or "").strip()
        if normalized_query_key:
            params.append(normalized_query_key)
            return f"{alias}.query_key = ?"

        clause = f"{alias}.keyword = ?"
        params.append(keyword)
        return clause

    def _normalize_publisher_match_values(self: DatabaseManager, values: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for item in values or []:
            text = " ".join(str(item or "").strip().split()).casefold()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _append_publisher_match_clause(
        self: DatabaseManager,
        params: List[Any],
        publisher_expr: str,
        values: List[str],
    ) -> str:
        match_clauses: List[str] = []
        for value in values:
            if "." in value:
                match_clauses.append(f"({publisher_expr} = ? OR {publisher_expr} LIKE ? ESCAPE '\\')")
                params.extend([value, f"%.{self._escape_like(value)}"])
            else:
                match_clauses.append(f"{publisher_expr} = ?")
                params.append(value)
        if not match_clauses:
            return ""
        return "(" + " OR ".join(match_clauses) + ")"

    def _append_visibility_filter_clause(
        self: DatabaseManager,
        params: List[Any],
        *,
        blocked_publishers: Optional[List[str]] = None,
        preferred_publishers: Optional[List[str]] = None,
        only_preferred_publishers: bool = False,
        tag_filter: str = "",
    ) -> str:
        clauses: List[str] = []
        publisher_expr = "LOWER(COALESCE(n.publisher, ''))"
        blocked = self._normalize_publisher_match_values(blocked_publishers)
        preferred = self._normalize_publisher_match_values(preferred_publishers)
        if blocked:
            match_clause = self._append_publisher_match_clause(params, publisher_expr, blocked)
            if match_clause:
                clauses.append(f"NOT {match_clause}")
        if only_preferred_publishers:
            if preferred:
                match_clause = self._append_publisher_match_clause(params, publisher_expr, preferred)
                clauses.append(match_clause if match_clause else "1 = 0")
            else:
                clauses.append("1 = 0")
        normalized_tag = str(tag_filter or "").strip()
        if normalized_tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM news_tags nt WHERE nt.link = n.link AND LOWER(nt.tag) = LOWER(?))"
            )
            params.append(normalized_tag)
        if not clauses:
            return ""
        return " AND " + " AND ".join(clauses)
