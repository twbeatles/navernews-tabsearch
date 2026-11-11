"""Compatibility facade for auxiliary dialogs."""

import logging

from core.logging_setup import configure_logging
from ui.dialogs_support import (
    ArchiveSearchDialog,
    AutomationRulesDialog,
    BackupDialog,
    KeywordGroupDialog,
    LogViewerDialog,
    NoteDialog,
    PublisherAliasDialog,
    TagManagerDialog,
    _verify_backups_job,
)

configure_logging()
logger = logging.getLogger(__name__)

__all__ = [
    "ArchiveSearchDialog",
    "AutomationRulesDialog",
    "BackupDialog",
    "KeywordGroupDialog",
    "LogViewerDialog",
    "NoteDialog",
    "PublisherAliasDialog",
    "TagManagerDialog",
    "_verify_backups_job",
]
