from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .config import fetch_proxy_url
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


def parse_radar_js(html: str) -> dict[str, Any]:
    """
    Extract nodes (var n = ...) and edges (var e = ...) from the inline setup function of index.html.
    """
    # 1. Parse nodes dictionary: "var n = { ... };"
    # We can use regular expressions or character scanning.
    nodes = {}
    edges = []
    
    # Try to find the setup script contents
    script_match = re.search(r"function\s+setup\s*\(canvas\)\s*\{(.*?)\}\s*</script>", html, re.DOTALL | re.IGNORECASE)
    if not script_match:
        # Fallback to general search in html
        script_content = html
    else:
        script_content = script_match.group(1)

    # Find the node object: var n = { ... };
    node_match = re.search(r"var\s+n\s*=\s*(\{.*?\});", script_content, re.DOTALL)
    if node_match:
        node_str = node_match.group(1).strip()
        # Parse individual node entries: "Card Name": { ... }
        # Regex to match: "Name": { properties }
        # Since it is JS object literal, we can do some careful regex parsing or JSON conversion
        node_entries = re.findall(r'"([^"]+)":\s*(\{.*?\})', node_str, re.DOTALL)
        for name, props_str in node_entries:
            props = {}
            # parse radius, fill, stroke, strokewidth
            for k in ("radius", "strokewidth"):
                val_m = re.search(rf"{k}:\s*([\d.]+)", props_str)
                if val_m:
                    props[k] = float(val_m.group(1))
            for k in ("fill", "stroke", "text"):
                val_m = re.search(rf"{k}:\s*\"([^\"]+)\"", props_str)
                if val_m:
                    props[k] = val_m.group(1)
            nodes[name] = props

    # Find the edge list: var e = [ ... ];
    edge_match = re.search(r"var\s+e\s*=\s*(\[.*?\]);", script_content, re.DOTALL)
    if edge_match:
        edge_str = edge_match.group(1).strip()
        # Parse individual edge items: [ "CardA", "CardB", {properties} ]
        # Match: [ "NameA", "NameB", { properties } ]
        edge_entries = re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(\{.*?\})\s*\]', edge_str, re.DOTALL)
        for card_a, card_b, props_str in edge_entries:
            props = {}
            # parse weight, length
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


async def fetch_class_radar(client: httpx.AsyncClient, class_name: str) -> dict[str, Any] | None:
    url = f"https://www.vicioussyndicate.com/wp-content/datareaper/radars/{class_name}/index.html"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            title_text = soup.title.string if soup.title else f"Data Reaper's Radar - {class_name}"
            # Extract issue number if present, e.g. "Issue #349"
            issue_match = re.search(r"Issue\s*&#35;(\d+)|Issue\s*#(\d+)", title_text)
            issue = issue_match.group(1) or issue_match.group(2) if issue_match else "Unknown"
            
            radar_data = parse_radar_js(resp.text)
            return {
                "class": class_name,
                "title": title_text,
                "issue": issue,
                "url": url,
                **radar_data
            }
    except Exception as e:
        logger.error(f"Error fetching Vicious Syndicate radar for {class_name}: {e}")
    return None


async def fetch_vicious_syndicate_radars(source: Source) -> dict[str, Any]:
    proxy = fetch_proxy_url()
    client_kwargs = {"timeout": 45.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        tasks = [fetch_class_radar(client, cls_name) for cls_name in CLASSES]
        results = await asyncio.gather(*tasks)
        
    radars = [r for r in results if r is not None]
    
    issue = "Unknown"
    for r in radars:
        if r.get("issue") != "Unknown":
            issue = r["issue"]
            break
            
    return {
        "type": "vicious_syndicate_radars",
        "issue": issue,
        "radars": radars,
        "total_radars": len(radars),
    }
