
"""Compatibility facade for MainApp settings import staging mixins."""

from ui.main_window_io_support.import_stage_support import (
    _ImportStageApplyMixin,
    _ImportStageMergeHelpersMixin,
    _ImportStageRuntimeStateMixin,
)


class _MainWindowImportStageMixin(
    _ImportStageMergeHelpersMixin,
    _ImportStageRuntimeStateMixin,
    _ImportStageApplyMixin,
):
    """Composes settings import merge, runtime snapshot, and apply/rollback staging."""


__all__ = ["_MainWindowImportStageMixin"]
