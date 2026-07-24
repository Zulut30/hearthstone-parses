from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

from bs4 import BeautifulSoup, Tag


SOURCE_ID = "hsguru_archetype_analysis"
SCHEMA_VERSION = 1
ANALYSIS_RANK = "legend"
ANALYSIS_PERIOD = "past_week"
FORMAT_IDS = {"standard": 2, "wild": 1}

CLASS_KEYS = {
    "death knight": "deathknight",
    "demon hunter": "demonhunter",
    "druid": "druid",
    "hunter": "hunter",
    "mage": "mage",
    "paladin": "paladin",
    "priest": "priest",
    "rogue": "rogue",
    "shaman": "shaman",
    "warlock": "warlock",
    "warrior": "warrior",
}


def _header(value: str) -> str:
    return re.sub(r"[^a-z]+", " ", value.casefold()).strip()


def _number(value: Any) -> float | None:
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _count(value: Any) -> int | None:
    text = str(value or "").split("(", 1)[0]
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _table_with_headers(
    html: str,
    required: set[str],
) -> tuple[Tag | None, dict[str, int]]:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        header_row = table.find("thead") or table.find("tr")
        if header_row is None:
            continue
        cells = header_row.find_all(["th", "td"])
        headers = [_header(cell.get_text(" ", strip=True)) for cell in cells]
        indexes = {name: headers.index(name) for name in required if name in headers}
        if len(indexes) == len(required):
            return table, indexes
    return None, {}


def parse_class_matchups_html(html: str) -> list[dict[str, Any]]:
    required = {"class", "winrate", "total games"}
    table, indexes = _table_with_headers(html, required)
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    table_rows = table.select("tbody tr") or table.find_all("tr")[1:]
    for tr in table_rows:
        cells = tr.find_all(["th", "td"])
        if len(cells) <= max(indexes.values()):
            continue
        class_label = cells[indexes["class"]].get_text(" ", strip=True)
        class_key = CLASS_KEYS.get(_header(class_label))
        if not class_key:
            continue
        games_text = cells[indexes["total games"]].get_text(" ", strip=True)
        winrate = _number(cells[indexes["winrate"]].get_text(" ", strip=True))
        games = _count(games_text)
        share_match = re.search(r"\(([-+]?\d+(?:[.,]\d+)?)\s*%\)", games_text)
        share = _number(share_match.group(1)) if share_match else None
        if winrate is None or not 0 <= winrate <= 100 or games is None:
            continue
        rows.append(
            {
                "class_key": class_key,
                "class_label": class_label,
                "winrate": winrate,
                "games": games,
                "share_pct": share,
            }
        )
    return rows


def _attribute_in_tree(cell: Tag, *names: str) -> str | None:
    for node in (cell, *cell.find_all(True)):
        for name in names:
            value = node.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _card_identity(cell: Tag) -> tuple[str | None, int | None, str]:
    name = (
        _attribute_in_tree(cell, "data-card-name", "aria-label", "alt")
        or cell.get_text(" ", strip=True)
    )
    card_id = _attribute_in_tree(cell, "data-card-id", "data-cardid")
    dbf_raw = _attribute_in_tree(cell, "data-dbf-id", "data-dbfid")
    dbf_id = int(dbf_raw) if dbf_raw and dbf_raw.isdigit() else None

    link = cell.find("a", href=True)
    if link is not None:
        parsed = urlparse(str(link.get("href") or ""))
        query = parse_qs(parsed.query)
        card_id = card_id or next(iter(query.get("card_id", [])), None)
        dbf_query = next(iter(query.get("dbf_id", [])), None)
        if dbf_id is None and dbf_query and dbf_query.isdigit():
            dbf_id = int(dbf_query)
        path_match = re.search(r"/card/(?:\d+/)?([A-Za-z0-9_]+)", parsed.path)
        if card_id is None and path_match:
            card_id = path_match.group(1)

    image = cell.find("img", src=True)
    if card_id is None and image is not None:
        image_match = re.search(
            r"/(?:tiles|render/[^/]+/[^/]+)/([^/.?]+)",
            str(image.get("src") or ""),
        )
        if image_match:
            card_id = image_match.group(1)
    return card_id, dbf_id, re.sub(r"\s+", " ", name).strip()


def parse_card_stats_html(html: str) -> list[dict[str, Any]]:
    required = {
        "card",
        "mulligan impact",
        "mulligan count",
        "drawn impact",
        "drawn count",
        "kept impact",
        "kept count",
    }
    table, indexes = _table_with_headers(html, required)
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    table_rows = table.select("tbody tr") or table.find_all("tr")[1:]
    for tr in table_rows:
        cells = tr.find_all(["th", "td"])
        if len(cells) <= max(indexes.values()):
            continue
        card_id, dbf_id, card_name = _card_identity(cells[indexes["card"]])
        mulligan_count = _count(cells[indexes["mulligan count"]].get_text(" ", strip=True))
        if not card_name or mulligan_count is None:
            continue
        rows.append(
            {
                "card_id": card_id,
                "dbf_id": dbf_id,
                "card_name": card_name,
                "mulligan_impact": _number(
                    cells[indexes["mulligan impact"]].get_text(" ", strip=True)
                ),
                "mulligan_count": mulligan_count,
                "drawn_impact": _number(
                    cells[indexes["drawn impact"]].get_text(" ", strip=True)
                ),
                "drawn_count": _count(
                    cells[indexes["drawn count"]].get_text(" ", strip=True)
                ),
                "kept_impact": _number(
                    cells[indexes["kept impact"]].get_text(" ", strip=True)
                ),
                "kept_count": _count(
                    cells[indexes["kept count"]].get_text(" ", strip=True)
                ),
            }
        )
    return rows


def analysis_urls(archetype: str, format_name: str) -> dict[str, str]:
    format_id = FORMAT_IDS[format_name]
    filters = {
        "format": format_id,
        "rank": ANALYSIS_RANK,
        "period": ANALYSIS_PERIOD,
    }
    return {
        "matchups": (
            f"https://www.hsguru.com/archetype/{quote(archetype)}?"
            f"{urlencode(filters)}"
        ),
        "cards": (
            "https://www.hsguru.com/card-stats?"
            + urlencode(
                {
                    "archetype": archetype,
                    **filters,
                    "show_counts": "yes",
                }
            )
        ),
    }
