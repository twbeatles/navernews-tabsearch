from typing import List, Tuple


def parse_tab_query(raw: str) -> Tuple[str, List[str]]:
    parts = raw.split()
    if not parts:
        return "", []

    db_keyword = ""
    exclude_words: List[str] = []
    for token in parts:
        if token.startswith("-"):
            if len(token) > 1:
                exclude_words.append(token[1:])
            continue
        if not db_keyword:
            db_keyword = token

    return db_keyword, exclude_words


def has_positive_keyword(raw: str) -> bool:
    db_keyword, _ = parse_tab_query(raw)
    return bool(db_keyword)


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
