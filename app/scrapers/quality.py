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

    if source.site == "metastats":
        structured = parsed.get("structured") or {}
        if source.id == "metastats_decks":
            decks = structured.get("decks") or []
            if len(decks) < 5:
                return False, f"metastats too few decks ({len(decks)})"
            return True, "ok"
        if source.id == "metastats_matchups":
            matchups = structured.get("matchups") or []
            if len(matchups) < 10:
                return False, f"metastats matchups too few ({len(matchups)})"
            return True, "ok"

    if source.site == "hearthstone-decks":
        structured = parsed.get("structured") or {}
        decks = structured.get("decks") or []
        if len(decks) < 5:
            return False, f"hearthstone-decks too few decks ({len(decks)})"
        return True, "ok"

    if source.site == "vicious-syndicate":
        structured = parsed.get("structured") or {}
        radars = structured.get("radars") or []
        if len(radars) < 5:
            return False, f"vicious-syndicate too few radars ({len(radars)})"
        return True, "ok"

    if source.site in ("hsreplay", "firestone", "heartharena"):
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
        if structured.get("type") == "bg_card_stats":
            tiers = structured.get("tiers") or {}
            total_cards = sum(len(cards) for cards in tiers.values())
            if total_cards < 50:
                return False, f"bg_card_stats too few total cards ({total_cards})"
            with_stats = sum(
                1
                for cards in tiers.values()
                for c in cards
                if c.get("average_placement") is not None or c.get("total_played")
            )
            if with_stats < 40:
                return False, f"bg_card_stats missing placement stats ({with_stats}/{total_cards})"
            return True, "ok"
        if structured.get("type") == "bg_trinkets":
            trinkets = structured.get("trinkets") or []
            if len(trinkets) < 8:
                return False, f"bg trinkets too few ({len(trinkets)})"
            valid = [
                t
                for t in trinkets
                if t.get("pick_rate")
                and t.get("name")
                and len(str(t["name"])) >= 4
                and str(t["name"])[0].isalnum()
            ]
            if len(valid) < max(6, len(trinkets) // 2):
                return False, f"bg trinkets invalid names/stats ({len(valid)}/{len(trinkets)})"
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
        if structured.get("type") == "bg_heroes":
            heroes = structured.get("heroes") or []
            if structured.get("blocked"):
                return False, "bg heroes blocked"
            if len(heroes) < 30:
                return False, f"bg heroes too few ({len(heroes)})"
            with_stats = sum(
                1
                for h in heroes
                if h.get("avg_placement") is not None
                and (h.get("games") or h.get("data_points"))
                and h.get("pick_rate")
            )
            if with_stats < 20:
                return False, f"bg heroes missing stats ({with_stats}/{len(heroes)})"
            return True, "ok"
        if structured.get("type") == "arena_card_tiers":
            cards = structured.get("cards") or []
            min_cards = 20 if "legendary" in source.id else 100
            if len(cards) < min_cards:
                return False, f"arena card tiers too few ({len(cards)})"
            if "firestone" not in source.id and not any(c.get("tier") for c in cards[:50]):
                return False, "arena card tiers missing tier labels"
            return True, "ok"
        if structured.get("type") == "heartharena_tierlist":
            classes = structured.get("classes") or []
            if len(classes) < 5:
                return False, f"heartharena classes too few ({len(classes)})"
            total_cards = structured.get("total_cards", 0)
            if total_cards < 300:
                return False, f"heartharena cards too few ({total_cards})"
            with_tier = sum(
                1 for cl in classes for c in (cl.get("cards") or []) if c.get("tier_id")
            )
            if with_tier < 200:
                return False, f"heartharena cards missing tier_id ({with_tier})"
            return True, "ok"
        if structured.get("type") == "card_stats":
            cards = structured.get("cards") or []
            if structured.get("blocked") and len(cards) < 10:
                return False, "card stats blocked or empty"
            if len(cards) < 30:
                return False, f"card stats too few ({len(cards)})"
            with_metrics = sum(
                1 for c in cards if c.get("deck_winrate") or c.get("deck_popularity")
            )
            if with_metrics < 20:
                return False, f"card stats missing metrics ({with_metrics}/{len(cards)})"
            return True, "ok"
        if any("could not load data" in line.lower() for line in text_lines):
            return False, "hsreplay premium data not loaded (login required)"
        if source.id.startswith("hsreplay_cards_"):
            if "rankrange=gold" not in (source.fragment or "").lower():
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
