
"""Compatibility facade for NewsTab action mixins."""

from ui.news_tab_support.actions_support import (
    _NewsTabArticleActionsMixin,
    _NewsTabLinkOpeningMixin,
    _NewsTabMarkReadMixin,
)


class _NewsTabActionsMixin(
    _NewsTabArticleActionsMixin,
    _NewsTabLinkOpeningMixin,
    _NewsTabMarkReadMixin,
):
    """Composes NewsTab article, link, and mark-read actions."""


__all__ = ["_NewsTabActionsMixin"]
