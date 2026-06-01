from __future__ import annotations

import re
from typing import Any

from ..sources import Source

CF_MARKERS = (
    "just a moment",
    "challenges.cloudflare.com",
    "cf-chl",
    "cloudflare challenge",
    "attention required",
)


def is_cloudflare_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CF_MARKERS)


def looks_like_real_page(html: str, source: Source) -> bool:
    if is_cloudflare_challenge(html):
        return False
    if len(html) < 2000:
        return False
    if source.site == "hsreplay":
        return bool(
            re.search(
                r"hsreplay\.net|userdata|__NEXT_DATA__|react-root|battlegrounds|arena",
                html,
                re.I,
            )
        )
    if source.site == "hsguru":
        return bool(
            re.search(r"hsguru\.com|archetype|matchup|streamer|meta", html, re.I)
        ) and "just a moment" not in html.lower()
    return True


def validate_parsed_data(source: Source, parsed: dict[str, Any]) -> tuple[bool, str]:
    title = (parsed.get("title") or "").lower()
    if "just a moment" in title or not title:
        return False, "invalid title"

    tables = parsed.get("tables") or []
    table_rows = sum(len(t.get("objects") or t.get("rows") or []) for t in tables)
    deck_codes = parsed.get("deck_codes") or []
    json_scripts = parsed.get("json_scripts") or []
    text_lines = parsed.get("text_preview") or []

    if source.site == "hsguru":
        if source.category == "meta":
            if table_rows < 5:
                return False, f"meta table too small ({table_rows} rows)"
            return True, "ok"
        if source.category == "streamer_decks":
            if len(deck_codes) < 2 and table_rows < 3:
                return False, "streamer decks missing codes/rows"
            return True, "ok"
        if source.category == "matchups":
            if table_rows < 3 and len(text_lines) < 30:
                return False, "matchups data too sparse"
            if not any("matchup" in line.lower() or "%" in line for line in text_lines[:80]):
                return False, "matchups content not detected"
            return True, "ok"

    if source.site == "hsreplay":
        has_userdata = any(s.get("id") == "userdata" for s in json_scripts)
        if has_userdata or table_rows >= 3 or len(text_lines) >= 40:
            return True, "ok"
        return False, "hsreplay page missing userdata/tables/content"

    return len(text_lines) >= 10, "minimal content check"
