from ui.main_window_io_support.cloud import _MainWindowCloudSyncMixin
from ui.main_window_io_support.data_io import _MainWindowDataIOMixin
from ui.main_window_io_support.exports import (
    export_items_to_csv,
    export_items_to_markdown,
    export_scope_to_csv,
    export_scope_to_markdown,
    import_bookmarks_notes_from_csv,
)
from ui.main_window_io_support.import_stage import _MainWindowImportStageMixin
from ui.main_window_io_support.settings_dialogs import _MainWindowSettingsDialogsMixin


class _MainWindowSettingsIOMixin(
    _MainWindowCloudSyncMixin,
    _MainWindowDataIOMixin,
    _MainWindowImportStageMixin,
    _MainWindowSettingsDialogsMixin,
):
    """Composes MainApp cloud, export/import, and settings-dialog I/O mixins."""


__all__ = [
    "_MainWindowSettingsIOMixin",
    "export_items_to_csv",
    "export_items_to_markdown",
    "export_scope_to_csv",
    "export_scope_to_markdown",
    "import_bookmarks_notes_from_csv",
]
