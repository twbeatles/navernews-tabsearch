
"""Compatibility facade for article tool dialogs."""

from ui.dialogs_support.archive_search import ArchiveSearchDialog
from ui.dialogs_support.automation_rules import AutomationRulesDialog
from ui.dialogs_support.publisher_aliases import PublisherAliasDialog
from ui.dialogs_support.tag_manager import TagManagerDialog

__all__ = [
    "ArchiveSearchDialog",
    "AutomationRulesDialog",
    "PublisherAliasDialog",
    "TagManagerDialog",
]
