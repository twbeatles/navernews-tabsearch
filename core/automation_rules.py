from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from core.content_filters import normalize_tags
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases


EXCLUDE_TAG = "제외"
MAX_RULES = 100
MAX_TERMS = 20


def _clean_text(value: Any, *, limit: int = 120) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "y"}:
            return True
        if lowered in {"0", "false", "no", "off", "n"}:
            return False
    return default


def _to_text_list(value: Any, *, limit: int = MAX_TERMS) -> List[str]:
    raw_items: Iterable[Any]
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_items = value
    else:
        raw_items = []

    result: List[str] = []
    seen = set()
    for item in raw_items:
        text = _clean_text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                break
    return result


def normalize_automation_rules(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for index, raw_rule in enumerate(value):
        if not isinstance(raw_rule, Mapping):
            continue
        name = _clean_text(raw_rule.get("name") or f"Rule {index + 1}", limit=60)
        keywords = _to_text_list(raw_rule.get("keywords"))
        exclude_words = _to_text_list(raw_rule.get("exclude_words"))
        publishers = _to_text_list(raw_rule.get("publishers"))
        query_terms = _to_text_list(raw_rule.get("queries"))
        add_tags = normalize_tags(raw_rule.get("add_tags", []))
        mark_read = _to_bool(raw_rule.get("mark_read"), False)
        mark_bookmark = _to_bool(raw_rule.get("mark_bookmark"), False)
        exclude = _to_bool(raw_rule.get("exclude"), False)
        suppress_notification = _to_bool(raw_rule.get("suppress_notification"), False)

        if not any([keywords, exclude_words, publishers, query_terms]):
            continue
        if not any([add_tags, mark_read, mark_bookmark, exclude, suppress_notification]):
            continue

        normalized.append(
            {
                "name": name,
                "enabled": _to_bool(raw_rule.get("enabled"), True),
                "keywords": keywords,
                "exclude_words": exclude_words,
                "publishers": publishers,
                "queries": query_terms,
                "add_tags": add_tags,
                "mark_read": mark_read,
                "mark_bookmark": mark_bookmark,
                "exclude": exclude,
                "suppress_notification": suppress_notification,
            }
        )
        if len(normalized) >= MAX_RULES:
            break
    return normalized


def _automation_rule_identity(rule: Mapping[str, Any]) -> tuple[Any, ...]:
    normalized = normalize_automation_rules([rule])
    if not normalized:
        return ()
    item = normalized[0]
    return (
        item.get("name", ""),
        bool(item.get("enabled", True)),
        tuple(item.get("keywords", [])),
        tuple(item.get("exclude_words", [])),
        tuple(item.get("publishers", [])),
        tuple(item.get("queries", [])),
        tuple(item.get("add_tags", [])),
        bool(item.get("mark_read", False)),
        bool(item.get("mark_bookmark", False)),
        bool(item.get("exclude", False)),
        bool(item.get("suppress_notification", False)),
    )


def dedupe_automation_rules(value: Any) -> List[Dict[str, Any]]:
    normalized = normalize_automation_rules(value)
    deduped: List[Dict[str, Any]] = []
    seen: Set[tuple[Any, ...]] = set()
    for rule in normalized:
        identity = _automation_rule_identity(rule)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduped.append(rule)
    return deduped


@dataclass(frozen=True)
class AutomationActions:
    matched_rules: List[str]
    add_tags: List[str]
    mark_read: bool = False
    mark_bookmark: bool = False
    suppress_notification: bool = False

    @property
    def has_actions(self) -> bool:
        return bool(self.add_tags or self.mark_read or self.mark_bookmark or self.suppress_notification)


def _contains_all(text: str, terms: Sequence[str]) -> bool:
    lowered = text.casefold()
    return all(term.casefold() in lowered for term in terms)


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def evaluate_automation_rules(
    item: Mapping[str, Any],
    rules: Sequence[Mapping[str, Any]],
    *,
    publisher_aliases: Mapping[str, str] | None = None,
) -> AutomationActions:
    normalized_rules = normalize_automation_rules(list(rules))
    aliases = normalize_publisher_aliases(publisher_aliases or {})
    title = _clean_text(item.get("title"), limit=500)
    description = _clean_text(item.get("description"), limit=1000)
    keyword = _clean_text(item.get("keyword") or item.get("db_keyword") or item.get("query"), limit=200)
    text = f"{title}\n{description}"
    publisher = _clean_text(item.get("publisher"))
    canonical = canonical_publisher(publisher, aliases)

    matched_rules: List[str] = []
    tag_set: List[str] = []
    tag_seen: Set[str] = set()
    mark_read = False
    mark_bookmark = False
    suppress_notification = False

    for rule in normalized_rules:
        if not bool(rule.get("enabled", True)):
            continue
        keywords = list(rule.get("keywords", []))
        exclude_words = list(rule.get("exclude_words", []))
        publishers = list(rule.get("publishers", []))
        query_terms = list(rule.get("queries", []))

        if keywords and not _contains_all(text, keywords):
            continue
        if exclude_words and _contains_any(text, exclude_words):
            continue
        if publishers:
            pub_keys = {publisher.casefold(), canonical.casefold()}
            wanted = {str(item).casefold() for item in publishers}
            if not (pub_keys & wanted):
                continue
        if query_terms and not _contains_any(keyword, query_terms):
            continue

        matched_rules.append(str(rule.get("name") or "rule"))
        for tag in list(rule.get("add_tags", [])):
            tag_key = str(tag).casefold()
            if tag and tag_key not in tag_seen:
                tag_seen.add(tag_key)
                tag_set.append(str(tag))
        if bool(rule.get("exclude", False)):
            if EXCLUDE_TAG.casefold() not in tag_seen:
                tag_seen.add(EXCLUDE_TAG.casefold())
                tag_set.append(EXCLUDE_TAG)
            mark_read = True
            suppress_notification = True
        mark_read = mark_read or bool(rule.get("mark_read", False))
        mark_bookmark = mark_bookmark or bool(rule.get("mark_bookmark", False))
        suppress_notification = suppress_notification or bool(rule.get("suppress_notification", False))

    return AutomationActions(
        matched_rules=matched_rules,
        add_tags=tag_set,
        mark_read=mark_read,
        mark_bookmark=mark_bookmark,
        suppress_notification=suppress_notification,
    )
