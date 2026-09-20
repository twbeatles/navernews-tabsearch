from core.db_mutations_support.maintenance import _NewsMaintenanceMixin
from core.db_mutations_support.news_upsert import _NewsUpsertMixin
from core.db_mutations_support.state_tags import _NewsStateTagsMixin


class _DatabaseMutationsMixin(_NewsUpsertMixin, _NewsStateTagsMixin, _NewsMaintenanceMixin):
    """Composes DatabaseManager write, tag, mark-read, and maintenance mutations."""

    # How long a soft-deleted article is kept so cloud sync can propagate the
    # delete to other machines. Cleanup jobs reclaim tombstones older than this;
    # anything newer stays so a machine that has not synced yet cannot resurrect
    # the article. Callers may override per operation.
    TOMBSTONE_RETENTION_DAYS = 90


__all__ = ["_DatabaseMutationsMixin"]
