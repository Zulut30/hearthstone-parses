from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
from typing import Any

import httpx

from .cards_index import card_from_id
from .sources import Source

logger = logging.getLogger(__name__)

FIRESTONE_STRATEGIES_URL = "https://static.zerotoheroes.com/hearthstone/data/battlegrounds-strategies/bgs-comps-strategies.gz.json"
FIRESTONE_STATS_URL = "https://static.zerotoheroes.com/api/bgs/comp-stats/past-three/overview-from-hourly.gz.json?v=2"

def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()

def difficulty_ru(val: str) -> str:
    v = val.strip().lower()
    if v == "easy":
        return "Легкая"
    if v == "medium":
        return "Средняя"
    if v == "hard":
        return "Сложная"
    return val

def first_tip(strategy: dict[str, Any]) -> str:
    tips = strategy.get("tips") or []
    if not tips:
        return ""
    # Try ruRU first
    for t in tips:
        if t.get("language") == "ruRU" and t.get("tip"):
            return t["tip"]
    # Try enUS
    for t in tips:
        if t.get("language") == "enUS" and t.get("tip"):
            return t["tip"]
    # Fallback to the first available tip
    return tips[0].get("tip") or ""

def _group_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for card in cards:
        key = str(card.get("id") or card.get("card_id") or card.get("dbfId") or "")
        if not key:
            continue
        if key in grouped:
            grouped[key]["count"] = int(grouped[key].get("count") or 1) + 1
        else:
            grouped[key] = dict(card)
            grouped[key]["count"] = 1
    return list(grouped.values())

def _card_from_firestone_entry(entry: dict[str, Any]) -> dict[str, Any]:
    card_id = entry.get("cardId")
    name = entry.get("name") or ""
    
    # Resolve card details using our cached and localized HearthstoneJSON index
    card_meta = card_from_id(card_id, locale="ruRU")
    
    res = {
        "count": 1,
        "card_id": card_id,
        "dbfId": card_meta.get("dbfId"),
        "id": card_id,
        "name": card_meta.get("name") or name,
        "image_url": f"https://art.hearthstonejson.com/v1/256x/{card_id}.png",
        "status": str(entry.get("status") or "").strip().upper() or "ADDON",
    }
    
    if entry.get("finalBoardWeight") is not None:
        try:
            res["final_board_weight"] = int(entry["finalBoardWeight"])
        except (ValueError, TypeError):
            res["final_board_weight"] = 0
            
    for k in ("cost", "type", "rarity"):
        if card_meta.get(k):
            res[k] = card_meta[k]
            
    return res

async def fetch_firestone_comps(source: Source) -> dict[str, Any]:
    """
    Fetch and assemble Firestone Battlegrounds compositions.
    This parses:
      1) bgs-comps-strategies.gz.json (strategies metadata)
      2) overview-from-hourly.gz.json (stats, win rates, pick rates, etc.)
    And maps them to the unified bg_comps format.
    """
    headers = {
        "accept": "application/json,text/plain,*/*",
        "user-agent": "KolodaHS BattlegroundsCrawler/1.0 (+https://kolodahs.ru)",
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        # Fetch strategies and stats in parallel
        resp_strategies, resp_stats = await asyncio.gather(
            client.get(FIRESTONE_STRATEGIES_URL, headers=headers),
            client.get(FIRESTONE_STATS_URL, headers=headers)
        )
        
        resp_strategies.raise_for_status()
        resp_stats.raise_for_status()
        
        content_strategies = resp_strategies.content
        if content_strategies.startswith(b'\x1f\x8b'):
            content_strategies = gzip.decompress(content_strategies)
            
        content_stats = resp_stats.content
        if content_stats.startswith(b'\x1f\x8b'):
            content_stats = gzip.decompress(content_stats)
            
        strategies_data = json.loads(content_strategies)
        stats_data = json.loads(content_stats)
        
    # Index stats by archetype (compId) for fast lookup
    comp_stats_list = stats_data.get("compStats") or []
    stats_by_archetype = {s.get("archetype"): s for s in comp_stats_list if s.get("archetype")}
    
    comps: list[dict[str, Any]] = []
    
    for strategy in strategies_data:
        comp_id = str(strategy.get("compId") or "").strip()
        if not comp_id:
            continue
            
        stats = stats_by_archetype.get(comp_id) or {}
        
        main_cards = []
        additional_cards = []
        
        for entry in strategy.get("cards") or []:
            if not entry or not entry.get("cardId"):
                continue
                
            status = str(entry.get("status") or "").strip().upper()
            card = _card_from_firestone_entry(entry)
            
            if status == "CORE":
                main_cards.append(card)
            else:
                additional_cards.append(card)
                
        # Format and append composition
        title_val = strategy.get("name") or slug_to_title(comp_id)
        description_val = first_tip(strategy)
        difficulty_val = str(strategy.get("difficulty") or "").strip()
        power_level_val = strategy.get("powerLevel")
        
        avg_placement_val = ""
        avg_placement_raw = stats.get("averagePlacement")
        if avg_placement_raw is not None:
            try:
                avg_placement_val = f"{float(avg_placement_raw):.2f}"
            except (ValueError, TypeError):
                pass
                
        games_val = None
        data_points_raw = stats.get("dataPoints")
        if data_points_raw is not None:
            try:
                games_val = int(data_points_raw)
            except (ValueError, TypeError):
                pass
                
        comps.append({
            "id": f"firestone-{slugify(comp_id or title_val)}",
            "comp_id": comp_id,
            "source": "firestone",
            "source_id": comp_id,
            "source_label": "Firestone",
            "title": title_val,
            "name": title_val,
            "description": description_val,
            "difficulty": difficulty_val,
            "difficulty_ru": difficulty_ru(difficulty_val),
            "tier": str(power_level_val) if power_level_val is not None else "",
            "games": games_val,
            "avg_placement": avg_placement_val,
            "main_cards": _group_cards(main_cards),
            "additional_cards": _group_cards(additional_cards),
            "minions": [c.get("name") for c in _group_cards(additional_cards) if c.get("name")],
            "url": "https://www.firestoneapp.com/battlegrounds/comps",
        })
        
    return {
        "type": "bg_comps",
        "comps": comps,
    }
