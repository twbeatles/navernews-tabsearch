
"""Compatibility facade for NewsTab loading mixins."""

from ui.news_tab_support.loading_support import _NewsTabDbLoadingMixin, _NewsTabLoadingLifecycleMixin


class _NewsTabLoadingMixin(_NewsTabLoadingLifecycleMixin, _NewsTabDbLoadingMixin):
    """Composes NewsTab hydration, loading, and cleanup responsibilities."""


__all__ = ["_NewsTabLoadingMixin"]
