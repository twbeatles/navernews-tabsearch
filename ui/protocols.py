from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol

if TYPE_CHECKING:
    from ui.news_tab import NewsTab


class MainWindowProtocol(Protocol):
    def update_tab_badge(self, keyword: str) -> None:
        ...

    def should_block_db_action(self, action: str, *, notify: bool = True) -> bool:
        ...

    def refresh_bookmark_tab(self) -> None:
        ...

    def sync_tab_load_more_state(self, keyword: str) -> None:
        ...

    def maybe_show_query_refresh_hint(self, keyword: str) -> None:
        ...

    def show_toast(self, message: str) -> None:
        ...

    def show_warning_toast(self, message: str) -> None:
        ...

    def sync_link_state_across_tabs(
        self,
        source_tab: Optional["NewsTab"],
        link: str,
        *,
        is_read: Optional[bool] = None,
        is_bookmarked: Optional[bool] = None,
        notes: Optional[str] = None,
        deleted: bool = False,
    ) -> None:
        ...

    def on_database_maintenance_completed(self, operation: str, affected_count: int = 0) -> None:
        ...


class SettingsDialogParentProtocol(Protocol):
    def begin_database_maintenance(self, operation: str) -> tuple[bool, str]:
        ...

    def end_database_maintenance(self) -> None:
        ...

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

    def create_http_session(self) -> Any:
        ...
