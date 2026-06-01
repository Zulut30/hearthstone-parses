from __future__ import annotations

import re
from typing import Any

from .cards_index import card_from_id, card_label, cards_by_dbfid, cards_by_id
from .hsreplay_client import fetch_hsreplay_markdown, jina_url

HSREPLAY_COMPS_URL = "https://hsreplay.net/battlegrounds/comps/"

COMP_MD_HEADER_RE = re.compile(
    r"^\[(.*)\]\(https://hsreplay\.net/battlegrounds/comps/(\d+)/([^)]+)\)\s*$",
    re.MULTILINE,
)
COMP_URL_RE = re.compile(
    r"https://hsreplay\.net/battlegrounds/comps/(\d+)/([a-zA-Z0-9_-]+)/?",
)
HSJSON_IMG_RE = re.compile(
    r"!\[([^\]]*)\]\(https://art\.hearthstonejson\.com/v1/(?:bgs/latest/[A-Za-z_]+/)?256x/([A-Za-z0-9_]+)\.(?:webp|png)\)",
    re.IGNORECASE,
)
MINION_CARD_RE = re.compile(
    r"!\[([^\]]*)\]\([^)]*hearthstonejson\.com[^)]*/(?:bgs/latest/[A-Za-z_]+/)?256x/([A-Za-z0-9_]+)\.(?:webp|png)\)\]"
    r"\(https://hsreplay\.net/battlegrounds/minions/(\d+)/([^)]+)\)",
    re.IGNORECASE,
)
MINION_URL_RE = re.compile(
    r"https://hsreplay\.net/battlegrounds/minions/(\d+)/([a-zA-Z0-9_-]+)/?",
    re.IGNORECASE,
)
HSJSON_ID_RE = re.compile(
    r"hearthstonejson\.com/v1/(?:bgs/latest/[A-Za-z_]+/)?256x/([A-Za-z0-9_]+)\.(?:webp|png)",
    re.IGNORECASE,
)


def _title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().title()


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


def _card_from_hsjson(name: str, card_id: str, dbf: int | None = None) -> dict[str, Any]:
    meta = cards_by_id().get(card_id) or card_label(cards_by_dbfid().get(int(dbf)) if dbf else None)
    if meta.get("name") in (None, "Unknown") and name:
        meta["name"] = name.strip()
    return {
        "count": 1,
        "card_id": card_id,
        "dbfId": meta.get("dbfId") or dbf,
        "id": meta.get("id") or card_id,
        "name": meta.get("name") or name,
        "image_url": f"https://art.hearthstonejson.com/v1/256x/{card_id}.png",
        **{k: meta[k] for k in ("cost", "type", "rarity") if meta.get(k)},
    }


def parse_hearthstonejson_images(text: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for match in HSJSON_IMG_RE.finditer(text):
        cards.append(_card_from_hsjson(match.group(1), match.group(2)))
    return cards


def parse_hsreplay_minion_cards(section: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    for match in MINION_CARD_RE.finditer(section):
        key = match.group(2)
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                **_card_from_hsjson(match.group(1), match.group(2), int(match.group(3))),
                "url": f"https://hsreplay.net/battlegrounds/minions/{match.group(3)}/{match.group(4).strip('/')}/",
            }
        )

    for dbf, slug in MINION_URL_RE.findall(section):
        key = f"dbf:{dbf}"
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                **_card_from_hsjson(_title_from_slug(slug), "", int(dbf)),
                "url": f"https://hsreplay.net/battlegrounds/minions/{dbf}/{slug}/",
            }
        )

    for card_id in HSJSON_ID_RE.findall(section):
        if card_id in seen:
            continue
        seen.add(card_id)
        cards.append(_card_from_hsjson("", card_id))
    return cards


def _find_comp_headers(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    headers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for index, line in enumerate(lines):
        md_match = COMP_MD_HEADER_RE.match(line.strip())
        if md_match:
            key = (md_match.group(2), md_match.group(3).strip("/"))
            if key not in seen:
                seen.add(key)
                headers.append(
                    {
                        "line": index,
                        "caption": md_match.group(1),
                        "remote_id": key[0],
                        "slug": key[1],
                        "url": f"https://hsreplay.net/battlegrounds/comps/{key[0]}/{key[1]}/",
                    }
                )

    for match in COMP_URL_RE.finditer(markdown):
        key = (match.group(1), match.group(2).strip("/"))
        if key in seen:
            continue
        seen.add(key)
        line_no = markdown[: match.start()].count("\n")
        caption = lines[line_no][:200] if line_no < len(lines) else ""
        headers.append(
            {
                "line": line_no,
                "caption": caption,
                "remote_id": key[0],
                "slug": key[1],
                "url": f"https://hsreplay.net/battlegrounds/comps/{key[0]}/{key[1]}/",
            }
        )

    headers.sort(key=lambda item: item["line"])
    return headers


def _split_detail_sections(markdown: str) -> tuple[str, str]:
    """Core trios (HSJSON images) usually appear before minion detail links."""
    marker = markdown.lower().find("battlegrounds/minions/")
    if marker > 100:
        return markdown[:marker], markdown[marker:]
    return markdown, ""


def _dedupe_additional(
    main_cards: list[dict[str, Any]], additional_cards: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    main_keys = {
        str(c.get("id") or c.get("card_id") or c.get("dbfId") or "")
        for c in main_cards
        if c.get("id") or c.get("card_id") or c.get("dbfId")
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in additional_cards:
        key = str(card.get("id") or card.get("card_id") or card.get("dbfId") or "")
        if not key or key in main_keys or key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


async def parse_hsreplay_comp_detail(url: str, *, source_id: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            markdown = await fetch_hsreplay_markdown(url, source_id=source_id)
            all_images = parse_hearthstonejson_images(markdown)
            all_minions = parse_hsreplay_minion_cards(markdown)
            main_cards: list[dict[str, Any]] = []
            seen_main: set[str] = set()
            for card in all_images:
                cid = str(card.get("card_id") or card.get("id") or "")
                if not cid or cid in seen_main:
                    continue
                seen_main.add(cid)
                main_cards.append(card)
                if len(main_cards) >= 6:
                    break
            additional_cards = _dedupe_additional(main_cards, all_minions)
            return {"main_cards": main_cards, "additional_cards": additional_cards}
        except Exception as exc:
            last_error = exc
    if last_error:
        import logging

        logging.getLogger(__name__).warning("Comp detail fetch failed for %s: %s", url, last_error)
    return {}


def parse_hsreplay_markdown(markdown: str, *, detail_limit: int = 12) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    headers = _find_comp_headers(markdown)
    comps: list[dict[str, Any]] = []

    for i, header in enumerate(headers):
        next_line = headers[i + 1]["line"] if i + 1 < len(headers) else len(lines)
        section = "\n".join(lines[header["line"] + 1 : next_line])

        caption = header.get("caption", "")
        main_cards = _group_cards(parse_hearthstonejson_images(caption))
        additional_cards = _group_cards(
            parse_hsreplay_minion_cards(section) + parse_hearthstonejson_images(section)
        )

        comps.append(
            {
                "id": f"hsreplay-{header['remote_id']}",
                "comp_id": int(header["remote_id"]),
                "source": "hsreplay",
                "source_id": header["remote_id"],
                "slug": header["slug"],
                "name": _title_from_slug(header["slug"]),
                "title": _title_from_slug(header["slug"]),
                "description": "",
                "main_cards": main_cards,
                "additional_cards": additional_cards,
                "minions": [c.get("name") for c in additional_cards if c.get("name")],
                "url": header["url"],
                "_fetch_detail": i < detail_limit,
                "_detail_url": header["url"],
            }
        )

    return comps


async def fetch_battlegrounds_comps(
    *,
    source_id: str = "hsreplay_battlegrounds_comps",
    detail_limit: int = 24,
) -> dict[str, Any]:
    markdown = await fetch_hsreplay_markdown(HSREPLAY_COMPS_URL, source_id=source_id)
    headers = _find_comp_headers(markdown)
    comps: list[dict[str, Any]] = []

    for i, header in enumerate(headers):
        if i >= detail_limit:
            break
        slug = header["slug"]
        comp: dict[str, Any] = {
            "id": f"hsreplay-{header['remote_id']}",
            "comp_id": int(header["remote_id"]),
            "source": "hsreplay",
            "source_id": header["remote_id"],
            "slug": slug,
            "name": _title_from_slug(slug),
            "title": _title_from_slug(slug),
            "description": "",
            "main_cards": [],
            "additional_cards": [],
            "minions": [],
            "url": header["url"],
        }
        detail = await parse_hsreplay_comp_detail(header["url"], source_id=source_id)
        main_cards = _group_cards(detail.get("main_cards") or [])
        additional_cards = _group_cards(detail.get("additional_cards") or [])
        if main_cards or additional_cards:
            comp["main_cards"] = main_cards
            comp["additional_cards"] = additional_cards
            comp["minions"] = [c.get("name") for c in additional_cards if c.get("name")]
        comps.append(comp)

    return {
        "type": "bg_comps",
        "comps": comps,
        "blocked": len(comps) < 3,
        "source": {
            "key": "hsreplay",
            "url": HSREPLAY_COMPS_URL,
            "backend": "hsreplay_jina_markdown",
        },
    }
