from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .scrapers.proxy import httpx_client_kwargs
from .sources import Source

logger = logging.getLogger(__name__)

# Pattern to parse title of the deck post on hearthstone-decks.net
# Format: "No Hand Hunter #2 Legend – Unknown (Score: 15-4)"
# Or: "Companion Hunter #138 Legend – unikoru11_uni"
DECK_TITLE_PATTERN = re.compile(
    r"^(?P<archetype>.+?)\s+(?P<rank>#\d+\s+\w+)\s*[–-]\s*(?P<player>.+?)(?:\s*\(\s*Score:\s*(?P<score>\d+-\d+)\s*\))?$",
    re.UNICODE
)


async def fetch_inner_deck_code(client: httpx.AsyncClient, url: str) -> str:
    """
    Fetch the individual post page of a deck and extract the deck code from the input field.
    """
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Look for an input containing a deck code
            for inp in soup.find_all("input"):
                val = inp.get("value") or ""
                # Simple regex check for typical deck code structure
                if val.startswith("AAE") or re.match(r"^AA[EBCG][a-zA-Z0-9+/=]+$", val):
                    return val
    except Exception as e:
        logger.error(f"Error fetching deck code from {url}: {e}")
    return ""


async def parse_decks_list_page(client: httpx.AsyncClient, url: str, format_name: str, limit: int = 20) -> list[dict[str, Any]]:
    """
    Parse standard/wild decks list page, find article elements, parse title stats and concurrently fetch their codes.
    """
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, "lxml")
    articles = soup.find_all("article")
    
    decks_info = []
    
    for art in articles[:limit]:
        h3 = art.find(class_="elementor-post__title")
        a_tag = h3.find("a") if h3 else None
        if not a_tag:
            continue
            
        raw_title = a_tag.get_text(strip=True)
        href = a_tag["href"]
        
        date_span = art.find(class_="elementor-post-date")
        date_str = date_span.get_text(strip=True) if date_span else ""
        
        # Parse title details with regex
        archetype = raw_title
        rank = ""
        player = ""
        score = None
        
        match = DECK_TITLE_PATTERN.search(raw_title)
        if match:
            gd = match.groupdict()
            archetype = gd.get("archetype") or raw_title
            rank = gd.get("rank") or ""
            player = gd.get("player") or ""
            score = gd.get("score")
            
        decks_info.append({
            "title": raw_title,
            "url": href,
            "date": date_str,
            "format": format_name,
            "archetype": archetype,
            "rank": rank,
            "player": player,
            "score": score,
        })
        
    # Fetch deck codes in parallel for these decks
    tasks = [fetch_inner_deck_code(client, d["url"]) for d in decks_info]
    codes = await asyncio.gather(*tasks)
    
    for d, code in zip(decks_info, codes):
        d["deck_code"] = code
        
    return decks_info


async def fetch_hearthstone_decks(source: Source) -> dict[str, Any]:
    """
    Fetch both Standard and Wild decks from hearthstone-decks.net and group them in a single response,
    merging and deduplicating with previous cached decks.
    """
    from .storage import load_dataset

    async with httpx.AsyncClient(**httpx_client_kwargs(source.id)) as client:
        standard_task = parse_decks_list_page(client, "https://hearthstone-decks.net/standard-decks/", "Standard", limit=20)
        wild_task = parse_decks_list_page(client, "https://hearthstone-decks.net/wild-decks/", "Wild", limit=20)
        
        standard_decks, wild_decks = await asyncio.gather(standard_task, wild_task)
        
    new_decks = standard_decks + wild_decks

    # Load previous decks if any exist
    previous_decks = []
    try:
        prev_data = load_dataset(source.id)
        if prev_data and isinstance(prev_data.get("data"), dict):
            previous_decks = prev_data["data"].get("decks") or []
    except Exception as e:
        logger.warning(f"Could not load previous decks for {source.id}: {e}")

    # Merge and deduplicate by post URL
    seen_urls = set()
    merged_decks = []
    
    # Process new decks first to keep them at the top or update them
    for d in new_decks:
        url = d.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged_decks.append(d)
            
    # Append previous decks
    for d in previous_decks:
        url = d.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged_decks.append(d)

    # Limit to latest 100 decks per format to avoid growing infinitely
    standard_merged = [d for d in merged_decks if d.get("format") == "Standard"][:100]
    wild_merged = [d for d in merged_decks if d.get("format") == "Wild"][:100]
    
    final_decks = standard_merged + wild_merged
    
    return {
        "type": "hearthstone_decks",
        "decks": final_decks,
        "standard_count": len(standard_merged),
        "wild_count": len(wild_merged),
        "total_decks": len(final_decks),
    }
