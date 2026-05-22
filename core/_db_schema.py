
# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Compatibility facade for DatabaseManager schema mixins."""

import sqlite3

from core.db_schema_support import IntegrityCheckResult, _DatabaseSchemaMixin

__all__ = ["IntegrityCheckResult", "_DatabaseSchemaMixin", "sqlite3"]
