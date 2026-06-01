from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .scrapers.proxy import httpx_client_kwargs
from .sources import Source

logger = logging.getLogger(__name__)

CLASSES = [
    "DeathKnight",
    "DemonHunter",
    "Druid",
    "Hunter",
    "Mage",
    "Paladin",
    "Priest",
    "Rogue",
    "Shaman",
    "Warlock",
    "Warrior",
]

CLASS_SLUGS = {
    "DeathKnight": "death-knight-decks",
    "DemonHunter": "demon-hunter-decks",
    "Druid": "druid-decks",
    "Hunter": "hunter-decks",
    "Mage": "mage-decks",
    "Paladin": "paladin-decks",
    "Priest": "priest-decks",
    "Rogue": "rogue-decks",
    "Shaman": "shaman-decks",
    "Warlock": "warlock-decks",
    "Warrior": "warrior-decks",
}


def parse_radar_js(html: str) -> dict[str, Any]:
    """
    Extract nodes (var n = ...) and edges (var e = ...) from the inline setup function of index.html.
    """
    nodes = {}
    edges = []
    
    script_match = re.search(r"function\s+setup\s*\(canvas\)\s*\{(.*?)\}\s*</script>", html, re.DOTALL | re.IGNORECASE)
    script_content = script_match.group(1) if script_match else html

    node_match = re.search(r"var\s+n\s*=\s*(\{.*?\});", script_content, re.DOTALL)
    if node_match:
        node_str = node_match.group(1).strip()
        node_entries = re.findall(r'"([^"]+)":\s*(\{.*?\})', node_str, re.DOTALL)
        for name, props_str in node_entries:
            props = {}
            for k in ("radius", "strokewidth"):
                val_m = re.search(rf"{k}:\s*([\d.]+)", props_str)
                if val_m:
                    props[k] = float(val_m.group(1))
            for k in ("fill", "stroke", "text"):
                val_m = re.search(rf"{k}:\s*\"([^\"]+)\"", props_str)
                if val_m:
                    props[k] = val_m.group(1)
            nodes[name] = props

    edge_match = re.search(r"var\s+e\s*=\s*(\[.*?\]);", script_content, re.DOTALL)
    if edge_match:
        edge_str = edge_match.group(1).strip()
        edge_entries = re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(\{.*?\})\s*\]', edge_str, re.DOTALL)
        for card_a, card_b, props_str in edge_entries:
            props = {}
            for k in ("weight", "length"):
                val_m = re.search(rf"{k}:\s*([\d.]+)", props_str)
                if val_m:
                    props[k] = float(val_m.group(1))
            stroke_m = re.search(r'stroke:\s*"([^"]+)"', props_str)
            if stroke_m:
                props["stroke"] = stroke_m.group(1)
            edges.append({
                "source": card_a,
                "target": card_b,
                **props
            })

    return {
        "nodes": [{"name": k, **v} for k, v in nodes.items()],
        "edges": edges,
    }


def normalize_radar_url(path: str) -> str:
    """Ensure the path is a full, valid URL."""
    path = path.strip()
    if path.startswith("//"):
        return f"https:{path}"
    if path.startswith("/"):
        return f"https://www.vicioussyndicate.com{path}"
    if not path.startswith("http"):
        return f"https://www.vicioussyndicate.com/{path}"
    return path


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
    max_retries: int = 5,
) -> httpx.Response | None:
    """
    Robust HTTP GET with a concurrency semaphore, exponential backoff, retry jitter,
    and a tiny sleep gap to avoid disconnects.
    """
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    async with semaphore:
        for attempt in range(max_retries):
            # Small randomized sleep gap between entering the semaphore
            await asyncio.sleep(random.uniform(0.2, 0.5))
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429:
                    wait_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                    logger.warning(f"Rate limited (429) fetching {url}. Retrying in {wait_time:.2f}s... (attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                
                logger.warning(f"Received non-200 status code {resp.status_code} for {url} (attempt {attempt+1}/{max_retries})")
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                await asyncio.sleep(wait_time)
            except Exception as e:
                wait_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                logger.warning(f"Error fetching {url}: {e}. Retrying in {wait_time:.2f}s... (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)

        logger.error(f"Failed to fetch {url} after {max_retries} attempts.")
        return None


async def fetch_radar_html(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> str | None:
    resp = await fetch_with_retry(client, url, semaphore)
    return resp.text if resp else None


async def fetch_deck_code(client: httpx.AsyncClient, deck_url: str, semaphore: asyncio.Semaphore) -> str | None:
    resp = await fetch_with_retry(client, deck_url, semaphore)
    if not resp:
        return None

    # Look for button data-clipboard-text or input value containing AAE...
    soup = BeautifulSoup(resp.text, "lxml")
    
    # 1. Look for data-clipboard-text on buttons
    btn = soup.find("button", attrs={"data-clipboard-text": True})
    if btn:
        val = btn["data-clipboard-text"].strip()
        if val.startswith("AAE"):
            return val

    # 2. Look for input tag with AAE value
    inp = soup.find("input", value=True)
    if inp:
        val = inp["value"].strip()
        if val.startswith("AAE"):
            return val

    # 3. Text search
    text_match = re.search(r"(AAE[A-Za-z0-9+/=]+)", resp.text)
    if text_match:
        return text_match.group(1)
        
    return None


async def discover_class_radars(
    client: httpx.AsyncClient,
    class_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    slug = CLASS_SLUGS.get(class_name)
    if not slug:
        return []

    index_url = f"https://www.vicioussyndicate.com/deck-library/{slug}/"
    discovered = []

    try:
        resp = await fetch_with_retry(client, index_url, semaphore)
        if not resp:
            logger.error(f"Failed to fetch deck library index for {class_name}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # 1. Main Class Radar URL
        main_obj = soup.find(["object", "embed", "iframe"])
        main_radar_url = None
        if main_obj:
            path = main_obj.get("data") or main_obj.get("src")
            if path:
                main_radar_url = normalize_radar_url(path)

        if main_radar_url:
            discovered.append({
                "class": class_name,
                "archetype": None,
                "radar_url": main_radar_url,
                "source_page": index_url,
                "inner_deck_pages": [],
                "deck_code": None,
            })

        # 2. Archetype Sublinks
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "#" in href or "?" in href:
                continue
            
            pattern = rf"https?://(?:www\.)?vicioussyndicate\.com/deck-library/{slug}/([^/]+)/?$"
            match = re.match(pattern, href)
            if not match:
                pattern_rel = rf"^/deck-library/{slug}/([^/]+)/?$"
                match = re.match(pattern_rel, href)

            if match:
                arch_name = a.text.strip() or match.group(1).replace("-", " ").title()
                discovered.append({
                    "class": class_name,
                    "archetype": arch_name,
                    "radar_url": None,
                    "source_page": normalize_radar_url(href),
                    "inner_deck_pages": [],
                    "deck_code": None,
                })

    except Exception as e:
        logger.error(f"Error discovering radars for {class_name}: {e}")

    return discovered


async def resolve_archetype_details(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any] | None:
    try:
        resp = await fetch_with_retry(client, item["source_page"], semaphore)
        if resp:
            soup = BeautifulSoup(resp.text, "lxml")
            
            # Resolve radar URL if missing
            if not item["radar_url"]:
                obj = soup.find(["object", "embed", "iframe"])
                if obj:
                    path = obj.get("data") or obj.get("src")
                    if path:
                        item["radar_url"] = normalize_radar_url(path)

            # Discover nested deck page links (e.g., https://www.vicioussyndicate.com/decks/...)
            deck_pages = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/decks/" in href:
                    deck_pages.append(normalize_radar_url(href))
            
            item["inner_deck_pages"] = list(set(deck_pages))
            return item
    except Exception as e:
        logger.error(f"Error resolving details for {item.get('archetype') or item['class']}: {e}")
    return None


async def fetch_vicious_syndicate_radars(source: Source) -> dict[str, Any]:
    # Use strict Semaphore of 3 to avoid triggering Cloudflare / server rate-limiting/disconnects
    semaphore = asyncio.Semaphore(3)

    async with httpx.AsyncClient(**httpx_client_kwargs(source.id)) as client:
        # Step 1: Discover class indexes & potential archetype pages
        discovery_tasks = [discover_class_radars(client, cls_name, semaphore) for cls_name in CLASSES]
        discovery_results = await asyncio.gather(*discovery_tasks)

        all_items = []
        for res_list in discovery_results:
            all_items.extend(res_list)

        # Step 2: Resolve archetype details (including inner deck links & radar URLs)
        resolve_tasks = [resolve_archetype_details(client, item, semaphore) for item in all_items]
        resolved_results = await asyncio.gather(*resolve_tasks)
        
        # Keep items that have resolved radar URLs
        active_items = [r for r in resolved_results if r is not None and r.get("radar_url")]

        # Step 3: Fetch deck codes in parallel for items that have deck pages
        async def fetch_code_for_item(item: dict[str, Any]) -> dict[str, Any]:
            if item["inner_deck_pages"]:
                # Fetch first deck page code for this archetype
                code = await fetch_deck_code(client, item["inner_deck_pages"][0], semaphore)
                if code:
                    item["deck_code"] = code
            return item

        code_tasks = [fetch_code_for_item(item) for item in active_items]
        active_items = await asyncio.gather(*code_tasks)

        # Step 4: Fetch index.html files for all resolved radars and parse them
        async def fetch_and_parse(item: dict[str, Any]) -> dict[str, Any] | None:
            html = await fetch_radar_html(client, item["radar_url"], semaphore)
            if not html:
                return None

            soup = BeautifulSoup(html, "lxml")
            title_text = soup.title.string if soup.title else f"Data Reaper's Radar - {item['class']}"
            issue_match = re.search(r"Issue\s*&#35;(\d+)|Issue\s*#(\d+)", title_text)
            issue = issue_match.group(1) or issue_match.group(2) if issue_match else "Unknown"

            radar_data = parse_radar_js(html)
            return {
                "class": item["class"],
                "archetype": item["archetype"],
                "title": title_text,
                "issue": issue,
                "url": item["source_page"],
                "radar_url": item["radar_url"],
                "deck_code": item["deck_code"],
                **radar_data
            }

        parse_tasks = [fetch_and_parse(item) for item in active_items]
        parse_results = await asyncio.gather(*parse_tasks)

    radars = [r for r in parse_results if r is not None]

    issue = "Unknown"
    for r in radars:
        if r.get("issue") != "Unknown":
            issue = r["issue"]
            break

    classes_summary = {}
    for r in radars:
        cls = r["class"]
        arch = r["archetype"]
        if cls not in classes_summary:
            classes_summary[cls] = {
                "class": cls,
                "has_archetypes": False,
                "archetypes": [],
            }
        if arch is not None:
            classes_summary[cls]["has_archetypes"] = True
            classes_summary[cls]["archetypes"].append(arch)

    return {
        "type": "vicious_syndicate_radars",
        "issue": issue,
        "classes_summary": list(classes_summary.values()),
        "radars": radars,
        "total_radars": len(radars),
    }
