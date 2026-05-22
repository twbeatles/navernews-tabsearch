
"""Compatibility facade for NewsTab UI control mixins."""

from ui.news_tab_support.ui_controls_support import (
    _NewsTabDateFilterControlsMixin,
    _NewsTabFilterEventControlsMixin,
    _NewsTabSavedSearchControlsMixin,
    _NewsTabUILayoutMixin,
)


class _NewsTabUIControlsMixin(
    _NewsTabUILayoutMixin,
    _NewsTabSavedSearchControlsMixin,
    _NewsTabDateFilterControlsMixin,
    _NewsTabFilterEventControlsMixin,
):
    """Composes NewsTab layout, saved-search, date, and filter controls."""


__all__ = ["_NewsTabUIControlsMixin"]
