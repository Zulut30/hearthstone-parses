from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .cards_index import card_from_id
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


def parse_decklist_div(dl, archetype_id: str, archetype_name: str, class_name: str) -> dict[str, Any] | None:
    h4 = dl.find("h4")
    if not h4:
        return None

    h4_text = h4.get_text(strip=True)
    deck_id = ""
    if "#" in h4_text:
        deck_id = h4_text.split("#")[-1].strip()
    else:
        a_tag = h4.find("a")
        if a_tag and a_tag.get("href"):
            href = a_tag["href"]
            match = re.search(r"/deck/(\d+)/", href)
            if match:
                deck_id = match.group(1)

    title = h4_text.strip()

    games = None
    win_rate = None

    text = dl.get_text()
    games_match = re.search(r"#Games:\s*([\d,]+)", text)
    if games_match:
        try:
            games = int(games_match.group(1).replace(",", ""))
        except ValueError:
            pass

    wr_match = re.search(r"#Win\s*Rate:\s*([\d.]+\s*%)", text, re.I)
    if wr_match:
        win_rate = wr_match.group(1).strip()

    deck_code = ""
    btn = dl.find(class_="copytoclipboard")
    if btn and btn.get("data-clipboard-text"):
        raw_text = btn["data-clipboard-text"]
        from .deck_decode import first_deck_code_from_text

        deck_code = first_deck_code_from_text(raw_text) or ""

    cards = []
    card_list_items = dl.find_all(class_="card-list-item")
    for item in card_list_items:
        name_div = item.find(class_="card-name")
        card_name = ""
        if name_div:
            a_link = name_div.find("a")
            if a_link:
                card_name = a_link.get_text(strip=True)
            else:
                card_name = name_div.get_text(strip=True)

        qty_div = item.find(class_="card-quantity")
        quantity = 1
        if qty_div:
            qty_text = qty_div.get_text(strip=True).lower()
            qty_match = re.search(r"(\d+)", qty_text)
            if qty_match:
                quantity = int(qty_match.group(1))

        cost_div = item.find(class_="card-gem")
        cost = None
        if cost_div:
            try:
                cost = int(cost_div.get_text(strip=True))
            except ValueError:
                pass

        card_id = None
        img_hover = item.find(id="card-image-hover")
        if img_hover and img_hover.find("img"):
            img_src = img_hover.find("img").get("src") or ""
            card_id_match = re.search(r"/([^/]+)\.png", img_src)
            if card_id_match:
                card_id = card_id_match.group(1)

        if not card_id and name_div and name_div.find("img"):
            bars_src = name_div.find("img").get("src") or ""
            card_id_match = re.search(r"/([^/]+)\.png", bars_src)
            if card_id_match:
                card_id = card_id_match.group(1)

        card_meta = {}
        if card_id:
            card_meta = card_from_id(card_id, locale="ruRU")

        cards.append({
            "id": card_id,
            "card_id": card_id,
            "dbfId": card_meta.get("dbfId"),
            "name": card_meta.get("name") or card_name,
            "metastats_name": card_name,
            "cost": card_meta.get("cost") or cost,
            "count": quantity,
        })

    return {
        "deck_id": deck_id,
        "title": title,
        "class": class_name,
        "archetype_id": archetype_id,
        "archetype_name": archetype_name,
        "games": games,
        "win_rate": win_rate,
        "deck_code": deck_code,
        "cards": cards,
    }


def parse_metastats_class_page(html_content: str, class_name: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_content, "lxml")
    decks = []

    panes = soup.find_all(class_="tab-pane")
    if not panes:
        decklists = soup.find_all(class_="decklist")
        for dl in decklists:
            deck_info = parse_decklist_div(dl, archetype_id="Unknown", archetype_name="Unknown", class_name=class_name)
            if deck_info:
                decks.append(deck_info)
    else:
        for pane in panes:
            pane_id = pane.get("id") or "Unknown"
            decklists = pane.find_all(class_="decklist")
            for dl in decklists:
                h4 = dl.find("h4")
                h4_text = h4.get_text(strip=True) if h4 else ""
                archetype_name = h4_text.split("#")[0].strip() if "#" in h4_text else h4_text.strip()
                if not archetype_name:
                    archetype_name = re.sub(r"(\x1b)?([A-Z])", r" \2", pane_id).strip()

                deck_info = parse_decklist_div(dl, archetype_id=pane_id, archetype_name=archetype_name, class_name=class_name)
                if deck_info:
                    decks.append(deck_info)
    return decks


async def fetch_metastats_decks(source: Source) -> dict[str, Any]:
    proxy = fetch_proxy_url()
    client_kwargs = {"timeout": 45.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    all_decks = []
    classes_parsed = []

    async with httpx.AsyncClient(**client_kwargs) as client:
        tasks = []
        for cls_name in CLASSES:
            url = f"https://metastats.net/hearthstone/class/decks/{cls_name}/"
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            tasks.append(client.get(url, headers=headers))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for cls_name, resp in zip(CLASSES, responses):
            if isinstance(resp, Exception):
                logger.error(f"Error fetching class {cls_name}: {resp}")
                continue
            if resp.status_code != 200:
                logger.error(f"Non-200 response for class {cls_name}: {resp.status_code}")
                continue

            try:
                decks = parse_metastats_class_page(resp.text, cls_name)
                all_decks.extend(decks)
                classes_parsed.append(cls_name)
            except Exception as e:
                logger.error(f"Error parsing class {cls_name}: {e}")

    return {
        "type": "metastats_decks",
        "decks": all_decks,
        "classes_parsed": classes_parsed,
        "total_decks": len(all_decks),
    }


def parse_metastats_matchups(html_content: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_content, "lxml")
    table = soup.find("table")
    if not table:
        return {"type": "metastats_matchups", "matchups": [], "archetypes": []}

    th_elements = table.find_all("th")
    headers = [th.get_text(strip=True) for th in th_elements]
    headers = [h for h in headers if h]

    matchups = []
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    for tr in rows:
        row_arch_el = tr.find(class_="playerarch")
        if not row_arch_el:
            continue
        row_arch = row_arch_el.get_text(strip=True)

        tds = tr.find_all("td")
        opponent_tds = tds[1:]
        for col_idx, td in enumerate(opponent_tds):
            if col_idx >= len(headers):
                break
            opp_arch = headers[col_idx]

            div = td.find("div")
            if not div:
                continue

            title_attr = div.get("title") or ""
            title_text = html.unescape(title_attr)

            games = None
            winrate = None
            vs_winrate = None

            games_match = re.search(r"Games:\s*(\d+)", title_text)
            if games_match:
                games = int(games_match.group(1))

            lines = [l.strip() for l in re.split(r"<br/?>|\n", title_text, flags=re.I) if l.strip()]
            for line in lines:
                if ":" in line:
                    parts = line.split(":", 1)
                    name = parts[0].strip()
                    val = parts[1].strip()
                    if name.lower() == row_arch.lower():
                        winrate = val
                    elif name.lower() == opp_arch.lower():
                        vs_winrate = val

            if not winrate:
                cell_text = td.get_text(strip=True)
                if cell_text and cell_text != "-":
                    winrate = cell_text

            if games is None and not winrate:
                continue

            matchups.append({
                "archetype": row_arch,
                "vs": opp_arch,
                "games": games,
                "winrate": winrate,
                "vs_winrate": vs_winrate,
            })

    return {
        "type": "metastats_matchups",
        "matchups": matchups,
        "archetypes": headers,
    }


async def fetch_metastats_matchups(source: Source) -> dict[str, Any]:
    proxy = fetch_proxy_url()
    client_kwargs = {"timeout": 45.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(source.url, headers=headers)
        resp.raise_for_status()
        html_content = resp.text

    structured = parse_metastats_matchups(html_content)
    return structured
