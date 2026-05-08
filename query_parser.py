import warnings

warnings.warn(
    "Root query_parser imports are deprecated; use core.query_parser instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.query_parser import (
    build_fetch_key,
    has_positive_keyword,
    parse_search_query,
    parse_tab_query,
)

__all__ = ['parse_tab_query', 'parse_search_query', 'has_positive_keyword', 'build_fetch_key']
