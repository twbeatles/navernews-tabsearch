"""Shared SQL policy for preview and apply; inputs are internal SQL expressions.

Wall-clock timestamps choose newer observations. Equal timestamps use a stable
value ordering so two peers converge regardless of import order. This is not a
claim that clocks on different PCs represent causal order.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Collection

from core.text_utils import parse_date_to_ts

CONTENT_FIELDS = (
    "title",
    "description",
    "pubDate",
    "publisher",
    "pubDate_ts",
    "title_hash",
)


def register_content_functions(
    conn: sqlite3.Connection, title_hash: Callable[[str], str]
) -> None:
    conn.create_function(
        "news_cloud_date",
        1,
        lambda value: parse_date_to_ts(str(value or "")),
        deterministic=True,
    )
    conn.create_function(
        "news_cloud_hash",
        1,
        lambda value: title_hash(str(value or "")),
        deterministic=True,
    )


def clear_content_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("news_cloud_date", 1, None)
    conn.create_function("news_cloud_hash", 1, None)


def source_timestamp(columns: Collection[str], field: str) -> str:
    if field in columns:
        return f"COALESCE(s.{field}, 0)"
    value_field = {
        "read_updated_at": "is_read",
        "bookmark_updated_at": "is_bookmarked",
        "notes_updated_at": "notes",
    }.get(field)
    if value_field not in columns or "created_at" not in columns:
        return "0"
    empty = "''" if value_field == "notes" else "0"
    return (
        f"CASE WHEN COALESCE(s.{value_field}, {empty}) != {empty} "
        "THEN COALESCE(s.created_at, 0) ELSE 0 END"
    )


def source_wins(
    source_ts: str, local_ts: str, source_value: str, local_value: str
) -> str:
    return (
        f"(({source_ts}) > ({local_ts}) OR "
        f"(({source_ts}) = ({local_ts}) AND ({source_value}) > ({local_value})))"
    )


def content_wins(source: str = "excluded", local: str = "news") -> str:
    def key(alias: str) -> str:
        return (
            "("
            + ", ".join(
                f"COALESCE({alias}.{field}, '')" for field in CONTENT_FIELDS[:4]
            )
            + ")"
        )

    source_ts = f"COALESCE({source}.content_updated_at, 0)"
    local_ts = f"COALESCE({local}.content_updated_at, 0)"
    # Equal raw content may still have inconsistent legacy derived columns.
    # Take its normalized projection instead of ordering by a stale hash/date.
    return (
        f"({source_ts} > {local_ts} OR "
        f"({source_ts} = {local_ts} AND {key(source)} >= {key(local)}))"
    )


def source_content_projection(columns: Collection[str]) -> str:
    """Expose a compatible content row to the exact same preview/apply policy."""
    fields = []
    for field in CONTENT_FIELDS:
        default = "0" if field == "pubDate_ts" else "''"
        value = f"COALESCE(s.{field}, {default})" if field in columns else default
        if field == "pubDate_ts":
            value = "news_cloud_date(s.pubDate)" if "pubDate" in columns else "0"
        elif field == "title_hash":
            value = (
                "news_cloud_hash(s.title)"
                if "title" in columns
                else "news_cloud_hash('')"
            )
        fields.append(f"{value} AS {field}")
    timestamp = (
        "COALESCE(s.content_updated_at, 0)" if "content_updated_at" in columns else "0"
    )
    return (
        "SELECT s.link, "
        + ", ".join(fields)
        + f", {timestamp} AS content_updated_at FROM cloud_src.news s"
    )


def tag_set_key(table: str, link: str) -> str:
    # Length prefixes avoid delimiter collisions, and ordering is independent of
    # insertion order. Empty sets are represented explicitly as the empty string.
    return f"""COALESCE((SELECT GROUP_CONCAT(token, '') FROM (
        SELECT printf('%08d:%s', length(tag), tag) AS token
        FROM {table} WHERE link = {link} AND tag IS NOT NULL AND TRIM(tag) != ''
        ORDER BY tag COLLATE BINARY
    )), '')"""


def tag_candidates_sql(
    conn: sqlite3.Connection, columns: Collection[str], has_state: bool
) -> str:
    has_tags = bool(
        conn.execute(
            "SELECT 1 FROM cloud_src.sqlite_master WHERE type='table' AND name='news_tags'"
        ).fetchone()
    )
    links = []
    if has_tags:
        links.append("SELECT link FROM cloud_src.news_tags")
    if has_state:
        links.append("SELECT link FROM cloud_src.news_tag_state")
    if not links:
        return "SELECT '' AS link, 0 AS tags_updated_at, 0 AS values_changed WHERE 0"
    source_ts = (
        "COALESCE((SELECT tags_updated_at FROM cloud_src.news_tag_state WHERE link = t.link), 0)"
        if has_state
        else "COALESCE((SELECT created_at FROM cloud_src.news WHERE link = t.link), 0)"
        if "created_at" in columns
        else "0"
    )
    local_ts = (
        "COALESCE((SELECT tags_updated_at FROM news_tag_state WHERE link = t.link), 0)"
    )
    source_key = tag_set_key("cloud_src.news_tags", "t.link") if has_tags else "''"
    local_key = tag_set_key("news_tags", "t.link")
    winner = source_wins(source_ts, local_ts, source_key, local_key)
    return f"""SELECT t.link, {source_ts} AS tags_updated_at,
                      ({source_key} != {local_key}) AS values_changed
               FROM ({" UNION ".join(links)}) t
               WHERE t.link IS NOT NULL AND t.link != ''
                 AND EXISTS (SELECT 1 FROM cloud_src.news s WHERE s.link = t.link)
                 AND {winner}"""
