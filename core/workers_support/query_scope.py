from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

@dataclass(frozen=True)
class DBQueryScope:
    keyword: str
    filter_txt: str = ""
    sort_mode: str = ""
    only_bookmark: bool = False
    only_unread: bool = False
    hide_duplicates: bool = False
    exclude_words: Tuple[str, ...] = field(default_factory=tuple)
    blocked_publishers: Tuple[str, ...] = field(default_factory=tuple)
    preferred_publishers: Tuple[str, ...] = field(default_factory=tuple)
    only_preferred_publishers: bool = False
    tag_filter: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    query_key: Optional[str] = None

    def count_kwargs(self) -> Dict[str, Any]:
        return {
            "keyword": self.keyword,
            "only_bookmark": self.only_bookmark,
            "only_unread": self.only_unread,
            "hide_duplicates": self.hide_duplicates,
            "filter_txt": self.filter_txt,
            "exclude_words": list(self.exclude_words),
            "blocked_publishers": list(self.blocked_publishers),
            "preferred_publishers": list(self.preferred_publishers),
            "only_preferred_publishers": self.only_preferred_publishers,
            "tag_filter": self.tag_filter,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "query_key": self.query_key,
        }

    def fetch_kwargs(self) -> Dict[str, Any]:
        kwargs = self.count_kwargs()
        kwargs["sort_mode"] = self.sort_mode
        return kwargs
