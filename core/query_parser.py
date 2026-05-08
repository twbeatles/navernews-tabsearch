from typing import List, Tuple


def _split_query_tokens(raw: str) -> Tuple[List[str], List[str]]:
    parts = str(raw or "").split()
    if not parts:
        return [], []

    positive_words: List[str] = []
    exclude_words: List[str] = []
    for token in parts:
        if token.startswith("-"):
            if len(token) > 1:
                exclude_words.append(token[1:])
            continue
        positive_words.append(token)
    return positive_words, exclude_words


def parse_tab_query(raw: str) -> Tuple[str, List[str]]:
    """Return legacy db_keyword metadata and excludes for a tab query.

    The first positive token remains the compatibility `db_keyword` value for
    old storage/grouping paths. The actual tab/fetch identity must be derived
    from `parse_search_query(...)` plus excludes through `build_fetch_key(...)`.
    """
    positive_words, exclude_words = _split_query_tokens(raw)
    db_keyword = positive_words[0] if positive_words else ""
    return db_keyword, exclude_words


def parse_search_query(raw: str) -> Tuple[str, List[str]]:
    """API 검색어(모든 양키워드 결합) + 제외어를 반환."""
    positive_words, exclude_words = _split_query_tokens(raw)
    search_query = " ".join(positive_words)
    return search_query, exclude_words


def has_positive_keyword(raw: str) -> bool:
    search_query, _ = parse_search_query(raw)
    return bool(search_query)


def build_fetch_key(search_keyword: str, exclude_words: List[str]) -> str:
    normalized_keyword = (search_keyword or "").strip().lower()
    normalized_excludes = sorted(
        {
            word.strip().lower()
            for word in (exclude_words or [])
            if isinstance(word, str) and word.strip()
        }
    )
    return f"{normalized_keyword}|{'|'.join(normalized_excludes)}"
