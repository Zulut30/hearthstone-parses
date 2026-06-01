from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .cards_index import resolve_card_name
from .hsreplay_extract import extract_for_source
from .sources import Source
from .structured import build_structured


DECK_CODE_RE = re.compile(r"\bAAE[A-Za-z0-9+/=]{24,}\b")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for index, table in enumerate(soup.find_all("table")):
        rows = []
        for tr in table.find_all("tr"):
            cells = [_clean_text(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        headers = rows[0] if table.find("th") else []
        data_rows = rows[1:] if headers else rows
        objects = []
        if headers:
            for row in data_rows:
                item = {}
                for pos, header in enumerate(headers):
                    item[header or f"column_{pos + 1}"] = row[pos] if pos < len(row) else None
                objects.append(item)
        tables.append(
            {
                "index": index,
                "headers": headers,
                "rows": data_rows,
                "objects": objects,
            }
        )
    return tables


def _extract_json_scripts(soup: BeautifulSoup) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        script_id = script.get("id") or ""
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        if "json" not in script_type and script_id != "__NEXT_DATA__":
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        payloads.append({"id": script_id, "type": script_type, "value": value})
    return payloads


def _extract_links(soup: BeautifulSoup, limit: int = 5000) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        label = _clean_text(anchor.get_text(" "))
        href = anchor["href"]
        if label or href:
            links.append({"text": label, "href": href})
        if len(links) >= limit:
            break
    return links


def _extract_hsreplay_bootstrap(json_scripts: list[dict[str, Any]]) -> dict[str, Any] | None:
    for script in json_scripts:
        if script.get("id") != "userdata":
            continue
        value = script.get("value")
        if isinstance(value, dict):
            return value
    return None


def _tables_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in snapshot.get("tables") or []:
        rows = item.get("rows") or []
        if not rows:
            continue
        headers = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []
        objects = []
        if headers:
            for row in data_rows:
                obj = {}
                for pos, header in enumerate(headers):
                    obj[header or f"column_{pos + 1}"] = row[pos] if pos < len(row) else None
                objects.append(obj)
        out.append({"index": item.get("index", 0), "headers": headers, "rows": data_rows, "objects": objects})
    return out


def parse_html(source: Source, html: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title = _clean_text(title_tag.get_text(" ")) if title_tag else ""
    text_lines = [
        _clean_text(line)
        for line in soup.get_text("\n").splitlines()
        if _clean_text(line)
    ]
    if snapshot and snapshot.get("lines"):
        snap_lines = [_clean_text(line) for line in snapshot["lines"] if _clean_text(line)]
        if len(snap_lines) > len(text_lines):
            text_lines = snap_lines
    deck_codes = sorted(set(DECK_CODE_RE.findall(html)))
    json_scripts = _extract_json_scripts(soup)
    tables = _extract_tables(soup)
    if snapshot and snapshot.get("tables"):
        snap_tables = _tables_from_snapshot(snapshot)
        if sum(len(t.get("rows") or []) for t in snap_tables) > sum(
            len(t.get("rows") or []) for t in tables
        ):
            tables = snap_tables
    if snapshot and snapshot.get("card_rows"):
        objects = []
        stat_headers = [
            "Card",
            "Deck Winrate",
            "Avg Copies",
            "Times Played",
            "Mulligan Winrate",
            "Keep Percentage",
        ]
        for row in snapshot["card_rows"]:
            if len(row) < 2:
                continue
            name = None
            name_idx = 0
            for i, cell in enumerate(row):
                if len(cell) > 2 and not _clean_text(cell).isdigit() and "%" not in cell:
                    if resolve_card_name(cell).get("id") or len(cell) > 4:
                        name = cell
                        name_idx = i
                        break
            if not name:
                continue
            obj = {"Card": name}
            stats = [c for j, c in enumerate(row) if j != name_idx and c]
            for j, val in enumerate(stats[:5]):
                obj[stat_headers[j + 1] if j + 1 < len(stat_headers) else f"stat_{j}"] = val
            objects.append(obj)
        if objects:
            tables.append(
                {
                    "index": 99,
                    "headers": stat_headers,
                    "rows": [list(o.values()) for o in objects],
                    "objects": objects,
                }
            )
    links = _extract_links(soup)
    hsreplay_bootstrap = _extract_hsreplay_bootstrap(json_scripts) if source.site == "hsreplay" else None
    hsreplay_extracted = (
        extract_for_source(source.id, soup, html, snapshot)
        if source.site == "hsreplay"
        else {}
    )
    structured = build_structured(
        source,
        {
            "text_preview": text_lines,
            "tables": tables,
            "links": links,
            "hsreplay_extracted": hsreplay_extracted,
        },
    )
    return {
        "source_id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "title": title,
        "tables": tables,
        "json_scripts": json_scripts,
        "hsreplay_bootstrap": hsreplay_bootstrap,
        "structured": structured,
        "hsreplay_extracted": hsreplay_extracted,
        "deck_codes": deck_codes,
        "links": links,
        "text_preview": text_lines[:300],
        "counts": {
            "tables": len(soup.find_all("table")),
            "json_scripts": len(_extract_json_scripts(soup)),
            "deck_codes": len(deck_codes),
            "links": len(soup.find_all("a")),
            "text_lines": len(text_lines),
        },
    }
