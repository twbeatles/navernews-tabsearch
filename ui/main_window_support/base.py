
"""Compatibility facade for MainApp base mixins."""

from ui.main_window_support.base_support import (
    TabFetchState,
    _MainWindowBaseAccessorsMixin,
    _MainWindowFtsBackfillMixin,
    _MainWindowMaintenanceMixin,
    _MainWindowTabHydrationMixin,
)


class _MainWindowBaseMixin(
    _MainWindowBaseAccessorsMixin,
    _MainWindowFtsBackfillMixin,
    _MainWindowTabHydrationMixin,
    _MainWindowMaintenanceMixin,
):
    """Composes MainApp common accessors, hydration, backfill, and maintenance."""


__all__ = ["TabFetchState", "_MainWindowBaseMixin"]
