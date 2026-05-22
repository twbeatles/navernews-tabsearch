
from core.db_queries_support.archive import _DatabaseArchiveQueriesMixin
from core.db_queries_support.counts import _DatabaseCountQueriesMixin
from core.db_queries_support.fetch import _DatabaseFetchQueriesMixin
from core.db_queries_support.filters import RE_FTS_ACCEL_TOKEN, _DatabaseQueryFilterMixin


class _DatabaseQueriesMixin(
    _DatabaseQueryFilterMixin,
    _DatabaseFetchQueriesMixin,
    _DatabaseArchiveQueriesMixin,
    _DatabaseCountQueriesMixin,
):
    """Composes DatabaseManager read/query responsibilities."""


__all__ = ["RE_FTS_ACCEL_TOKEN", "_DatabaseQueriesMixin"]
