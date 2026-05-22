
from core.db_schema_support.backfill import _NewsBackfillSchemaMixin
from core.db_schema_support.connection import _DatabaseConnectionSchemaMixin
from core.db_schema_support.init import _DatabaseInitSchemaMixin
from core.db_schema_support.keywords import _NewsKeywordSchemaMixin
from core.db_schema_support.tables import _NewsTableSchemaMixin
from core.db_schema_support.types import IntegrityCheckResult


class _DatabaseSchemaMixin(
    _DatabaseConnectionSchemaMixin,
    _NewsKeywordSchemaMixin,
    _NewsTableSchemaMixin,
    _NewsBackfillSchemaMixin,
    _DatabaseInitSchemaMixin,
):
    """Composes DatabaseManager schema, migration, and backfill responsibilities."""

    FTS_BACKFILL_CURSOR_KEY = "news_fts.backfill_rowid"
    FTS_BACKFILL_DONE_KEY = "news_fts.backfill_done"
    TITLE_HASH_BACKFILL_CHUNK_SIZE = 1000
    PUBDATE_TS_BACKFILL_CHUNK_SIZE = 5000


__all__ = ["IntegrityCheckResult", "_DatabaseSchemaMixin"]
