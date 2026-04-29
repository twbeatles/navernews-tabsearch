from __future__ import annotations

from typing import Any, Iterable, List


MAX_TAGS_PER_ARTICLE = 20
MAX_TAG_LENGTH = 30


def normalize_name_list(value: Any, *, max_items: int = 200) -> List[str]:
    """Normalize publisher-like string lists with case-insensitive dedupe."""
    if isinstance(value, str):
        raw_items: Iterable[Any] = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return []

    normalized: List[str] = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, (str, int, float)):
            continue
        text = " ".join(str(item).strip().split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized


def normalize_publisher_filter_lists(
    blocked_publishers: Any,
    preferred_publishers: Any,
    *,
    preferred_wins: bool = False,
    max_items: int = 200,
) -> tuple[List[str], List[str]]:
    """Normalize blocked/preferred publisher lists and remove cross-list duplicates."""
    blocked = normalize_name_list(blocked_publishers, max_items=max_items)
    preferred = normalize_name_list(preferred_publishers, max_items=max_items)

    if preferred_wins:
        preferred_keys = {item.casefold() for item in preferred}
        blocked = [item for item in blocked if item.casefold() not in preferred_keys]
        return blocked, preferred

    blocked_keys = {item.casefold() for item in blocked}
    preferred = [item for item in preferred if item.casefold() not in blocked_keys]
    return blocked, preferred


def normalize_tags(value: Any) -> List[str]:
    """Normalize free-form article tags."""
    if isinstance(value, str):
        raw_items: Iterable[Any] = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return []

    normalized: List[str] = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, (str, int, float)):
            continue
        text = " ".join(str(item).strip().split())
        if not text:
            continue
        text = text[:MAX_TAG_LENGTH]
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= MAX_TAGS_PER_ARTICLE:
            break
    return normalized


def tags_to_csv(tags: Any) -> str:
    return ", ".join(normalize_tags(tags))
