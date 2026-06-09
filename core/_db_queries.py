
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Compatibility facade for DatabaseManager query mixins."""

from core.db_queries_support import NewsCountSummary, RE_FTS_ACCEL_TOKEN, _DatabaseQueriesMixin

__all__ = ["NewsCountSummary", "RE_FTS_ACCEL_TOKEN", "_DatabaseQueriesMixin"]
