from __future__ import annotations

from typing import Protocol


class MainWindowProtocol(Protocol):
    def update_tab_badge(self, keyword: str) -> None:
        ...

    def refresh_bookmark_tab(self) -> None:
        ...

    def show_toast(self, message: str) -> None:
        ...

    def show_warning_toast(self, message: str) -> None:
        ...


class SettingsDialogParentProtocol(Protocol):
    def on_database_maintenance_completed(self, operation: str, affected_count: int = 0) -> None:
        ...

    def export_settings(self) -> None:
        ...

    def import_settings(self) -> None:
        ...

    def show_log_viewer(self) -> None:
        ...

    def show_keyword_groups(self) -> None:
        ...
