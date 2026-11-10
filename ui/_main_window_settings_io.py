"""Compatibility facade for MainApp settings/import/export orchestration."""

from core.startup import StartupManager  # noqa: F401 # patched by tests (ui._main_window_settings_io.StartupManager)
from ui.main_window_io_support.mixin import (
    _MainWindowSettingsIOMixin,
    export_items_to_csv,
    export_items_to_markdown,
    export_scope_to_csv,
    export_scope_to_markdown,
    import_bookmarks_notes_from_csv,
)
from ui.main_window_io_support.exports import (
    _csv_truthy,
    _dialogs_for,
    _export_item_markdown,
    _export_row,
    _markdown_escape,
)

__all__ = [
    "_MainWindowSettingsIOMixin",
    "_csv_truthy",
    "_dialogs_for",
    "_export_item_markdown",
    "_export_row",
    "_markdown_escape",
    "export_items_to_csv",
    "export_items_to_markdown",
    "export_scope_to_csv",
    "export_scope_to_markdown",
    "import_bookmarks_notes_from_csv",
]
