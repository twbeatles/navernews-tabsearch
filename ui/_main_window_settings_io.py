"""Compatibility facade for MainApp settings/import/export orchestration."""

from core.machine_identity import get_machine_identity
from core.startup import StartupManager
from core.config_store import save_primary_config_file
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
