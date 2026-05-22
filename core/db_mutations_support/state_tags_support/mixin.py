
from core.db_mutations_support.state_tags_support.article_state import _NewsArticleStateMixin
from core.db_mutations_support.state_tags_support.automation import _NewsAutomationActionsMixin
from core.db_mutations_support.state_tags_support.tags import _NewsTagsMixin


class _NewsStateTagsMixin(
    _NewsArticleStateMixin,
    _NewsTagsMixin,
    _NewsAutomationActionsMixin,
):
    # news.is_duplicate is a legacy schema column; duplicate truth lives in news_keywords.
    ALLOWED_UPDATE_FIELDS = {"is_read", "is_bookmarked", "notes"}


__all__ = ["_NewsStateTagsMixin"]
