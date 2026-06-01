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
        structured = parsed.get("structured") or parsed.get("hsreplay_extracted") or {}
        if structured.get("type") == "arena_legendary_groups":
            if len(structured.get("groups") or []) < 10:
                return False, f"legendary groups too few ({len(structured.get('groups') or [])})"
            if not any(g.get("key_card") for g in structured.get("groups") or []):
                return False, "legendary groups missing key_card"
            return True, "ok"
        if structured.get("type") == "bg_comps":
            comps = structured.get("comps") or []
            if len(comps) < 3:
                return False, f"bg comps too few ({len(comps)})"
            with_cards = sum(
                1 for c in comps if (c.get("main_cards") or c.get("additional_cards"))
            )
            if with_cards < max(3, len(comps) // 2):
                return False, f"bg comps mostly empty ({with_cards}/{len(comps)} with cards)"
            return True, "ok"
        if structured.get("type") == "arena_winning_decks":
            decks = structured.get("decks") or []
            if len(decks) < 1:
                return False, "arena winning decks empty"
            if not any((d.get("final_deck") or []) for d in decks):
                return False, "arena winning decks missing final_deck"
            return True, "ok"
        if structured.get("type") == "arena_class_matrix":
            classes = structured.get("classes") or []
            matchups = structured.get("matchups") or []
            if len(classes) < 8:
                return False, f"arena class stats too few ({len(classes)})"
            if len(matchups) < 50:
                return False, f"arena dual-class matchups too few ({len(matchups)})"
            return True, "ok"
        if structured.get("type") == "arena_card_tiers":
            cards = structured.get("cards") or []
            if len(cards) < 200:
                return False, f"arena card tiers too few ({len(cards)})"
            if not any(c.get("tier") for c in cards[:50]):
                return False, "arena card tiers missing tier labels"
            return True, "ok"
        if any("could not load data" in line.lower() for line in text_lines):
            return False, "hsreplay premium data not loaded (login required)"
        if source.id.startswith("hsreplay_cards_"):
            for script in json_scripts:
                if script.get("id") != "userdata":
                    continue
                user = (script.get("value") or {})
                if isinstance(user, str):
                    continue
                if not (user.get("user") or {}).get("is_authenticated"):
                    return False, "hsreplay session not authenticated"
            if not any("%" in line for line in text_lines[100:200]):
                return False, "hsreplay cards stats not found in page"
        has_userdata = any(s.get("id") == "userdata" for s in json_scripts)
        if has_userdata or table_rows >= 3 or len(text_lines) >= 40:
            return True, "ok"
        return False, "hsreplay page missing userdata/tables/content"

    return len(text_lines) >= 10, "minimal content check"
