from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


MAX_ALIASES = 200
MAX_PUBLISHER_TEXT = 120


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:MAX_PUBLISHER_TEXT]


def _key(value: Any) -> str:
    return _clean_text(value).casefold()


def normalize_publisher_aliases(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    normalized: Dict[str, str] = {}
    seen = set()
    for raw_source, raw_alias in value.items():
        source = _clean_text(raw_source)
        alias = _clean_text(raw_alias)
        if not source or not alias:
            continue
        source_key = _key(source)
        if not source_key or source_key in seen:
            continue
        seen.add(source_key)
        normalized[source] = alias
        if len(normalized) >= MAX_ALIASES:
            break
    return normalized


def canonical_publisher(publisher: Any, aliases: Mapping[str, str] | None = None) -> str:
    text = _clean_text(publisher)
    if not text:
        return ""
    normalized_aliases = normalize_publisher_aliases(aliases or {})
    lookup = {_key(source): alias for source, alias in normalized_aliases.items()}
    return lookup.get(_key(text), text)


def expand_publisher_filters(
    values: Sequence[str] | None,
    aliases: Mapping[str, str] | None = None,
) -> List[str]:
    result: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        text = _clean_text(value)
        text_key = _key(text)
        if text and text_key not in seen:
            seen.add(text_key)
            result.append(text)

    normalized_aliases = normalize_publisher_aliases(aliases or {})
    alias_pairs = [(source, alias, _key(source), _key(alias)) for source, alias in normalized_aliases.items()]
    for value in values or []:
        add(value)
        value_key = _key(value)
        for source, alias, source_key, alias_key in alias_pairs:
            if value_key and value_key in {source_key, alias_key}:
                add(source)
                add(alias)
    return result


def combine_publisher_counts(
    rows: Iterable[Tuple[str, int]],
    aliases: Mapping[str, str] | None = None,
    *,
    limit: int = 20,
) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for publisher, count in rows:
        label = canonical_publisher(publisher, aliases) or "(unknown)"
        counts[label] = counts.get(label, 0) + int(count or 0)
    sorted_rows = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return sorted_rows[: max(1, int(limit or 20))]
