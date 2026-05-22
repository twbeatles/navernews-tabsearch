
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
"""Compatibility facade for news state/tag mutation mixins."""

from core.db_mutations_support.state_tags_support import _NewsStateTagsMixin

__all__ = ["_NewsStateTagsMixin"]
