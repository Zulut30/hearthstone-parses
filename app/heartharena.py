from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .cards_index import card_from_id
from .sources import Source

logger = logging.getLogger(__name__)

CLASS_MAP = {
    "death-knight": "Death Knight",
    "demon-hunter": "Demon Hunter",
    "druid": "Druid",
    "hunter": "Hunter",
    "mage": "Mage",
    "paladin": "Paladin",
    "priest": "Priest",
    "rogue": "Rogue",
    "shaman": "Shaman",
    "warlock": "Warlock",
    "warrior": "Warrior",
    "any": "Neutral",
}

async def fetch_heartharena_tierlist(source: Source) -> dict[str, Any]:
    """
    Fetch and parse HearthArena card tier list from https://www.heartharena.com/ru/tierlist.
    Returns structured HearthArena tier list.
    """
    from .scrapers.proxy import proxy_url_for_source

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-encoding": "gzip, deflate",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    proxy = proxy_url_for_source(source.id)
    last_error: Exception | None = None
    for fetch_url in (source.url, "https://www.heartharena.com/tierlist"):
        try:
            async with httpx.AsyncClient(timeout=45.0, proxy=proxy, follow_redirects=True) as client:
                resp = await client.get(fetch_url, headers=headers)
                resp.raise_for_status()
                html = resp.text
            break
        except Exception as exc:
            last_error = exc
            html = ""
    else:
        raise last_error or RuntimeError("heartharena fetch failed")

    soup = BeautifulSoup(html, "html.parser")
    sections = soup.find_all("section", class_="tierlist")
    
    classes_data = []
    
    for section in sections:
        class_id = section.get("id")
        if not class_id or class_id == "change-log":
            continue
            
        class_name = CLASS_MAP.get(class_id, class_id.replace("-", " ").title())
        cards_list = []
        
        rarity_lis = section.find_all("li", class_="rarity")
        for rarity_li in rarity_lis:
            rarity_classes = rarity_li.get("class") or []
            rarity_name = "common"
            for rc in rarity_classes:
                if rc in ("commons", "rares", "epics", "legendaries"):
                    rarity_name = rc.replace("commons", "common").replace("rares", "rare").replace("epics", "epic").replace("legendaries", "legendary")
                    break
                    
            tier_lis = rarity_li.find_all("li", class_="tier")
            for tier_li in tier_lis:
                tier_classes = tier_li.get("class") or []
                tier_id = "unknown"
                for tc in tier_classes:
                    if tc != "tier":
                        tier_id = tc
                        break
                        
                header_el = tier_li.find("header")
                tier_name = header_el.get_text(strip=True) if header_el else tier_id.title()
                
                cards_ol = tier_li.find("ol", class_="cards")
                if not cards_ol:
                    continue
                    
                card_items = cards_ol.find_all("li")
                for card_item in card_items:
                    dl_el = card_item.find("dl", class_="card")
                    if not dl_el:
                        continue
                        
                    dt_el = dl_el.find("dt")
                    dd_el = dl_el.find("dd", class_="score")
                    
                    if not dt_el:
                        continue
                        
                    parsed_name = dt_el.get_text(strip=True)
                    
                    score_val = None
                    if dd_el:
                        try:
                            score_val = int(dd_el.get_text(strip=True))
                        except (ValueError, TypeError):
                            pass
                            
                    img_url = dt_el.get("data-card-image") or ""
                    card_id = None
                    if img_url:
                        match = re.search(r"/([^/]+)\.(webp|png|jpg|gif)", img_url)
                        if match:
                            card_id = match.group(1)
                            
                    card_meta = {}
                    if card_id:
                        card_meta = card_from_id(card_id, locale="ruRU")
                        
                    card_entry = {
                        "id": card_id,
                        "card_id": card_id,
                        "dbfId": card_meta.get("dbfId"),
                        "name": card_meta.get("name") or parsed_name,
                        "heartharena_name": parsed_name,
                        "cost": card_meta.get("cost"),
                        "type": card_meta.get("type"),
                        "rarity": card_meta.get("rarity") or rarity_name.upper(),
                        "cardClass": card_meta.get("cardClass"),
                        "image_url": img_url or (f"https://art.hearthstonejson.com/v1/256x/{card_id}.png" if card_id else None),
                        "score": score_val,
                        "tier_id": tier_id,
                        "tier_name": tier_name,
                    }
                    cards_list.append(card_entry)
                    
        cards_list.sort(key=lambda c: (c.get("score") if c.get("score") is not None else -999, c.get("name") or ""), reverse=True)
        
        classes_data.append({
            "class_id": class_id,
            "class_name": class_name,
            "cards": cards_list,
            "total_cards": len(cards_list),
        })
        
    return {
        "type": "heartharena_tierlist",
        "classes": classes_data,
        "total_classes": len(classes_data),
        "total_cards": sum(c["total_cards"] for c in classes_data),
    }
