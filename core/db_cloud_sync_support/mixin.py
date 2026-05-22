
from core.db_cloud_sync_support.apply import _CloudSyncApplyMixin
from core.db_cloud_sync_support.merge_rows import _CloudSyncMergeRowsMixin
from core.db_cloud_sync_support.metadata import _CloudSyncMetadataMixin
from core.db_cloud_sync_support.preview import _CloudSyncPreviewMixin
from core.db_cloud_sync_support.rollback import _CloudSyncRollbackMixin


class _DatabaseCloudSyncMixin(
    _CloudSyncMetadataMixin,
    _CloudSyncRollbackMixin,
    _CloudSyncMergeRowsMixin,
    _CloudSyncPreviewMixin,
    _CloudSyncApplyMixin,
):
    """Composes DatabaseManager cloud snapshot merge responsibilities."""


__all__ = ["_DatabaseCloudSyncMixin"]
