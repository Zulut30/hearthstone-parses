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

DECK_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9+/=])AA[A-Za-z0-9+/=]{20,}(?![A-Za-z0-9+/=])")

# Pattern to parse title of the deck post on hearthstone-decks.net
# Format: "No Hand Hunter #2 Legend – Unknown (Score: 15-4)"
# Or: "Companion Hunter #138 Legend – unikoru11_uni"
DECK_TITLE_PATTERN = re.compile(
    r"^(?P<archetype>.+?)\s+(?P<rank>#\d+\s+\w+)\s*[–-]\s*(?P<player>.+?)(?:\s*\(\s*Score:\s*(?P<score>\d+-\d+)\s*\))?$",
    re.UNICODE
)


def extract_deck_code_from_html(html: str) -> str:
    """Extract a Hearthstone deck code from common WordPress post locations."""
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []

    for tag in soup.find_all(["input", "textarea", "button"]):
        for attr in ("value", "data-clipboard-text", "data-deck-code", "aria-label"):
            value = tag.get(attr)
            if value:
                candidates.append(str(value))
        text = tag.get_text(" ", strip=True)
        if text:
            candidates.append(text)

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text(" ", strip=True)
        if script_text:
            candidates.append(script_text)

    candidates.append(soup.get_text(" ", strip=True))

    for candidate in candidates:
        match = DECK_CODE_PATTERN.search(candidate)
        if match:
            return match.group(0)
    return ""


async def fetch_inner_deck_code(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """
    Fetch the individual post page and extract the deck code with a narrow retry for failed details.
    """
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    last_error = ""
    for attempt in range(1, 3):
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                await asyncio.sleep(0.5 * attempt)
                continue
            code = extract_deck_code_from_html(resp.text)
            if code:
                return {"deck_code": code, "deck_code_status": "ok", "detail_attempts": attempt}
            last_error = "deck code not found"
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning("Error fetching deck code from %s (attempt %s): %s", url, attempt, e)
        await asyncio.sleep(0.5 * attempt)
    return {"deck_code": "", "deck_code_status": "missing", "deck_code_error": last_error}


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
    code_results = await asyncio.gather(*tasks)
    
    for d, result in zip(decks_info, code_results):
        d.update(result)
        
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
        "with_deck_code": sum(1 for deck in final_decks if deck.get("deck_code")),
        "missing_deck_code_count": sum(1 for deck in final_decks if not deck.get("deck_code")),
        "deck_code_fill_rate": round(
            sum(1 for deck in final_decks if deck.get("deck_code")) / len(final_decks),
            4,
        )
        if final_decks
        else 0.0,
    }
