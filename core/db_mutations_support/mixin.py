from core.db_mutations_support.maintenance import _NewsMaintenanceMixin
from core.db_mutations_support.news_upsert import _NewsUpsertMixin
from core.db_mutations_support.state_tags import _NewsStateTagsMixin


class _DatabaseMutationsMixin(_NewsUpsertMixin, _NewsStateTagsMixin, _NewsMaintenanceMixin):
    """Composes DatabaseManager write, tag, mark-read, and maintenance mutations."""


__all__ = ["_DatabaseMutationsMixin"]
