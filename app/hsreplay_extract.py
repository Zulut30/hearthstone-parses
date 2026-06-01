from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from .cards_index import card_label, cards_by_dbfid, resolve_card_name

CARD_HREF_RE = re.compile(r"/cards/(\d+)")
HERO_HREF_RE = re.compile(r"/battlegrounds/heroes/(\d+)")
COMP_HREF_RE = re.compile(r"/battlegrounds/comps/(\d+)/([^/?#]+)")
TRINKET_HREF_RE = re.compile(r"/battlegrounds/trinkets/")

ARENA_CLASS_MARKERS = {
    "Death Knight", "Demon Hunter", "Druid", "Hunter", "Mage",
    "Paladin", "Priest", "Rogue", "Shaman", "Warlock", "Warrior",
    "Рыцарь смерти", "Охотник на демонов", "Друид", "Охотник", "Маг",
    "Паладин", "Жрец", "Разбойник", "Шаман", "Чернокнижник", "Воин",
}

FINAL_DECK_MARKERS = ("Final Deck", "Финальная колода")
DISCARD_MARKERS = ("Discarded cards in Re-draft", "Сброшено при пересдаче", "Discarded")
ADDED_MARKERS = ("Added cards in Re-draft", "Добавлено при пересдаче", "Added cards")
LEGENDARY_MARKERS = ("Legendary Group", "Legendary Groups", "Легендарная группа", "Legendary")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _card_from_dbfid(dbf_id: int, count: int = 1) -> dict[str, Any]:
    meta = card_label(cards_by_dbfid().get(dbf_id))
    return {"count": count, **meta}


def _cards_from_hrefs(html_chunk: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: list[tuple[int, int]] = []
    for dbf_id in CARD_HREF_RE.findall(html_chunk):
        did = int(dbf_id)
        count = 1
        if seen and seen[-1][0] == did:
            count = seen[-1][1] + 1
            seen[-1] = (did, count)
        else:
            seen.append((did, count))
    for did, count in seen:
        entry = _card_from_dbfid(did, count)
        if entry.get("id"):
            cards.append(entry)
    return cards


def _hero_display_name(dbf_id: int, raw: str) -> str:
    meta = cards_by_dbfid().get(dbf_id) or {}
    name = meta.get("name") or ""
    raw = _clean(raw)
    if name and (len(raw) > 55 or raw.count("%") >= 2 or not raw):
        return name
    if raw and len(raw) <= 55 and not raw[0].isdigit():
        return raw
    return name or raw or f"Hero {dbf_id}"


def _apply_stats_to_card(entry: dict[str, Any], cells: list[str], row_text: str = "") -> None:
    parts = list(cells) + ([row_text] if row_text else [])
    for cell in parts:
        cell = _clean(cell)
        if not cell:
            continue
        cl = cell.lower()
        if "%" in cell:
            if any(h in cl for h in ("deck", "колод", "popularity", "включ", "included")):
                entry["deck_popularity"] = cell
            elif "mulligan" in cl or "муллиган" in cl:
                entry["mulligan_winrate"] = cell
            elif "drawn" in cl or "взяти" in cl:
                entry["winrate_when_drawn"] = cell
            elif "played" in cl or "разыгран" in cl:
                entry["played_winrate"] = cell
            elif "pick" in cl or "добор" in cl:
                entry["pick_rate"] = cell
            else:
                entry.setdefault("deck_winrate", cell)
        elif re.match(r"^[a-fA-F]$", cell):
            entry["tier"] = cell.upper()
        elif re.match(r"^\d+(?:\.\d+)?%$", cell):
            entry.setdefault("deck_winrate", cell)
        elif cell.replace(",", "").replace(".", "", 1).isdigit() and "avg_copies" not in entry:
            entry.setdefault("avg_copies", cell)


def cards_from_snapshot(snapshot: dict[str, Any] | None, *, arena: bool = False) -> list[dict[str, Any]]:
    if not snapshot:
        return []
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()

    for item in snapshot.get("card_entries") or []:
        href = str(item.get("href") or "")
        is_arena = "UNDERGROUND_ARENA" in href
        if arena != is_arena:
            continue
        dbf_id = int(item.get("dbfId") or 0)
        if not dbf_id or dbf_id in seen:
            continue
        seen.add(dbf_id)
        entry = _card_from_dbfid(dbf_id)
        cells = [str(c) for c in (item.get("cells") or [])]
        _apply_stats_to_card(entry, cells, str(item.get("rowText") or ""))
        for cell in cells:
            m = re.match(r"^(\d+)\s*(★)?\s*(.+)$", _clean(cell))
            if m and not entry.get("name"):
                entry["mana"] = int(m.group(1))
                entry["name"] = m.group(3).strip()
        cards.append(entry)

    for row in snapshot.get("card_rows") or []:
        if not isinstance(row, list) or len(row) < 2:
            continue
        name = None
        for cell in row:
            c = _clean(str(cell))
            if resolve_card_name(c).get("id") or (len(c) > 4 and "%" not in c and not c.isdigit()):
                name = c
                break
        if not name:
            continue
        entry: dict[str, Any] = {"name": name, **resolve_card_name(name)}
        if not entry.get("dbfId"):
            continue
        dbf_id = int(entry["dbfId"])
        if dbf_id in seen:
            continue
        seen.add(dbf_id)
        _apply_stats_to_card(entry, [_clean(str(c)) for c in row])
        cards.append(entry)
    return cards


def _merge_cards(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for card in primary + extra:
        dbf_id = card.get("dbfId")
        if not dbf_id:
            continue
        did = int(dbf_id)
        if did not in by_id:
            by_id[did] = dict(card)
            continue
        for key, val in card.items():
            if val and not by_id[did].get(key):
                by_id[did][key] = val
    return list(by_id.values())


def _row_stats_from_element(el: Tag | None) -> dict[str, str]:
    if el is None:
        return {}
    text = _clean(el.get_text(" "))
    stats: dict[str, str] = {}
    for part in re.findall(r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?", text):
        if "%" in part:
            if "pick_rate" not in stats:
                stats["pick_rate"] = part
            elif "winrate" not in stats:
                stats["winrate"] = part
            else:
                stats.setdefault("extra_" + part, part)
        elif "avg_placement" not in stats:
            stats["avg_placement"] = part
    return stats


def extract_bg_heroes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    by_dbf = cards_by_dbfid()
    heroes: dict[int, dict[str, Any]] = {}
    for anchor in soup.find_all("a", href=HERO_HREF_RE):
        match = HERO_HREF_RE.search(anchor.get("href", ""))
        if not match:
            continue
        dbf_id = int(match.group(1))
        row = anchor.find_parent("tr") or anchor.find_parent(
            lambda t: t.name in ("div", "li") and len(_clean(t.get_text())) < 400
        )
        raw = _clean(anchor.get_text())
        name = _hero_display_name(dbf_id, raw)
        stats = _row_stats_from_element(row)
        entry = {
            "hero": name,
            "dbfId": dbf_id,
            "id": (by_dbf.get(dbf_id) or {}).get("id"),
            **stats,
        }
        if row and not stats.get("pick_rate"):
            percents = re.findall(r"\d+(?:\.\d+)?%", _clean(row.get_text()))
            if percents:
                entry["pick_rate"] = percents[0]
        heroes[dbf_id] = entry
    return sorted(heroes.values(), key=lambda h: h.get("pick_rate", ""), reverse=True)


def _parse_comp_text(text: str, slug: str) -> tuple[str, str, list[str]]:
    text = _clean(text)
    if not text or text.lower() in ("tier7", "premium", "medium", "hard"):
        return slug, "", []
    name = text
    for sep in ("Medium Difficulty", "Hard Difficulty", "Easy Difficulty", "Tier7", "Premium"):
        if sep in name:
            name = name.split(sep)[0].strip()
    minions: list[str] = []
    if " · " in text:
        parts = [p.strip() for p in text.split(" · ") if p.strip()]
        if parts:
            name = parts[0]
            minions = parts[1:]
    elif " - " in text and len(text) < 120:
        parts = [p.strip() for p in text.split(" - ", 1)]
        name = parts[0]
        if len(parts) > 1:
            minions = [m.strip() for m in re.split(r",|\s+\+\s+", parts[1]) if m.strip()]
    return name[:120] or slug, text[:400], minions[:20]


def extract_bg_comps_from_links(links: list[dict[str, str]]) -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in links:
        href = item.get("href", "")
        match = COMP_HREF_RE.search(href)
        if not match or href in seen:
            continue
        seen.add(href)
        comp_id, slug = int(match.group(1)), match.group(2).replace("-", " ").title()
        text = _clean(item.get("text", ""))
        name, description, minions = _parse_comp_text(text, slug)
        comps.append(
            {
                "comp_id": comp_id,
                "slug": slug,
                "name": name,
                "description": description,
                "minions": minions,
                "url": href,
            }
        )
    return comps


def extract_bg_comps(soup: BeautifulSoup) -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=COMP_HREF_RE):
        href = anchor.get("href", "")
        match = COMP_HREF_RE.search(href)
        if not match or href in seen:
            continue
        seen.add(href)
        comp_id, slug = match.group(1), match.group(2).replace("-", " ").title()
        text = _clean(anchor.get_text())
        name, description, minions = _parse_comp_text(text, slug)
        comps.append(
            {
                "comp_id": int(comp_id),
                "slug": slug,
                "name": name,
                "description": description,
                "minions": minions,
                "url": href,
            }
        )
    return comps


def extract_bg_trinkets(soup: BeautifulSoup) -> list[dict[str, Any]]:
    trinkets: list[dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/battlegrounds/trinkets/" not in href or href.count("/") < 4:
            continue
        name = _clean(anchor.get_text())
        if len(name) < 3:
            continue
        row = anchor.find_parent("tr") or anchor.find_parent("li")
        stats = _row_stats_from_element(row)
        trinkets.append({"name": name[:80], "url": href, **stats})
    if trinkets:
        return trinkets
    return []


def _parse_card_row(tr: Tag) -> dict[str, Any] | None:
    link = tr.find("a", href=CARD_HREF_RE)
    if not link:
        return None
    match = CARD_HREF_RE.search(link.get("href", ""))
    if not match:
        return None
    dbf_id = int(match.group(1))
    cells = [_clean(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
    name = _clean(link.get_text()) or (cards_by_dbfid().get(dbf_id) or {}).get("name", "")
    entry: dict[str, Any] = {"name": name, **_card_from_dbfid(dbf_id)}
    header_hints = ("winrate", "win rate", "побед", "колод", "copies", "копи", "played", "pick", "mulligan", "tier", "тир")
    _apply_stats_to_card(entry, [c for c in cells if c and c != name])
    return entry if entry.get("id") else None


def extract_ranked_cards(soup: BeautifulSoup) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()
    for tr in soup.find_all("tr"):
        entry = _parse_card_row(tr)
        if entry and entry.get("dbfId") not in seen:
            seen.add(int(entry["dbfId"]))
            cards.append(entry)
    if len(cards) < 20:
        for anchor in soup.find_all("a", href=CARD_HREF_RE):
            match = CARD_HREF_RE.search(anchor.get("href", ""))
            if not match:
                continue
            dbf_id = int(match.group(1))
            if dbf_id in seen:
                continue
            seen.add(dbf_id)
            row = anchor.find_parent("tr")
            if row:
                entry = _parse_card_row(row)
                if entry:
                    cards.append(entry)
                    continue
            cards.append(_card_from_dbfid(dbf_id))
    return cards


def extract_arena_cards(soup: BeautifulSoup) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()
    for tr in soup.find_all("tr"):
        entry = _parse_card_row(tr)
        if not entry:
            continue
        dbf_id = int(entry["dbfId"])
        if dbf_id in seen:
            continue
        seen.add(dbf_id)
        cards.append(entry)
    if len(cards) < 30:
        for anchor in soup.find_all("a", href=re.compile(r"/cards/\d+")):
            match = CARD_HREF_RE.search(anchor.get("href", ""))
            if not match:
                continue
            dbf_id = int(match.group(1))
            if dbf_id in seen:
                continue
            seen.add(dbf_id)
            cards.append(_card_from_dbfid(dbf_id))
    return cards


def _split_html_sections(html: str) -> list[dict[str, str]]:
    pattern = (
        r"(Final Deck|Финальная колода|Discarded cards in Re-draft|"
        r"Сброшено при пересдаче|Added cards in Re-draft|Добавлено при пересдаче|"
        r"Legendary Group|Legendary Groups|Легендарная группа)"
    )
    parts = re.split(pattern, html, flags=re.I)
    sections: list[dict[str, str]] = []
    current = "header"
    buf: list[str] = []
    for part in parts:
        if not part:
            continue
        marker = part.strip()
        if marker.lower() in {m.lower() for m in FINAL_DECK_MARKERS + DISCARD_MARKERS + ADDED_MARKERS + LEGENDARY_MARKERS}:
            if buf:
                sections.append({"name": current, "html": "".join(buf)})
            current = marker
            buf = []
        else:
            buf.append(part)
    if buf:
        sections.append({"name": current, "html": "".join(buf)})
    return sections


def extract_arena_winning_decks(soup: BeautifulSoup, html: str) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    lines = [_clean(x) for x in soup.get_text("\n").splitlines() if _clean(x)]

    i = 0
    while i < len(lines):
        if lines[i] not in ARENA_CLASS_MARKERS:
            i += 1
            continue
        deck: dict[str, Any] = {
            "class": lines[i],
            "record": None,
            "player": None,
            "played_at": None,
            "final_deck": [],
            "discarded": [],
            "added": [],
            "legendary_group": None,
        }
        i += 1
        while i < len(lines):
            line = lines[i]
            if line in ARENA_CLASS_MARKERS:
                break
            if line == "Record" and i + 1 < len(lines):
                deck["record"] = lines[i + 1]
                i += 2
                continue
            if line in ("Player", "Игрок") and i + 1 < len(lines):
                deck["player"] = lines[i + 1]
                if i + 2 < len(lines):
                    deck["played_at"] = lines[i + 2]
                i += 3
                continue
            if any(line == m for m in FINAL_DECK_MARKERS):
                i += 1
                cards_buf: list[str] = []
                while i < len(lines):
                    if any(lines[i] == m for m in DISCARD_MARKERS + ADDED_MARKERS + LEGENDARY_MARKERS):
                        break
                    if lines[i] in ARENA_CLASS_MARKERS:
                        break
                    cards_buf.append(lines[i])
                    i += 1
                deck["final_deck"] = _parse_card_tokens(cards_buf)
                continue
            if any(line == m for m in DISCARD_MARKERS):
                i += 1
                cards_buf = []
                while i < len(lines):
                    if any(lines[i] == m for m in ADDED_MARKERS + LEGENDARY_MARKERS + FINAL_DECK_MARKERS):
                        break
                    if lines[i] in ARENA_CLASS_MARKERS:
                        break
                    cards_buf.append(lines[i])
                    i += 1
                deck["discarded"] = _parse_card_tokens(cards_buf)
                continue
            if any(line == m for m in ADDED_MARKERS):
                i += 1
                cards_buf = []
                while i < len(lines):
                    if any(lines[i] == m for m in LEGENDARY_MARKERS + FINAL_DECK_MARKERS):
                        break
                    if lines[i] in ARENA_CLASS_MARKERS:
                        break
                    cards_buf.append(lines[i])
                    i += 1
                deck["added"] = _parse_card_tokens(cards_buf)
                continue
            if any(line == m for m in LEGENDARY_MARKERS):
                deck["legendary_group"] = lines[i + 1] if i + 1 < len(lines) else line
                i += 2
                continue
            i += 1
        decks.append(deck)

    link_decks = extract_arena_winning_decks_from_links(
        [{"href": a.get("href", ""), "text": _clean(a.get_text())} for a in soup.find_all("a", href=True)],
        lines,
    )
    if link_decks and any(d.get("final_deck") for d in link_decks):
        return link_decks

    if decks and any(d.get("final_deck") for d in decks):
        return decks

    chunks = re.split(r"Final Deck|Финальная колода", html, flags=re.I)[1:]
    meta_iter = [l for l in lines if l in ARENA_CLASS_MARKERS]
    for idx, chunk in enumerate(chunks):
        deck = {
            "class": meta_iter[idx] if idx < len(meta_iter) else "Unknown",
            "record": None,
            "player": None,
            "played_at": None,
            "final_deck": _cards_from_hrefs(chunk.split("Discarded")[0].split("Сброшено")[0]),
            "discarded": [],
            "added": [],
            "legendary_group": None,
        }
        if re.search("Discarded|Сброшено", chunk, re.I):
            disc_part = re.split(r"Discarded cards in Re-draft|Сброшено", chunk, flags=re.I)[-1]
            add_part = re.split(r"Added cards in Re-draft|Добавлено", disc_part, flags=re.I)
            deck["discarded"] = _cards_from_hrefs(add_part[0])
            if len(add_part) > 1:
                deck["added"] = _cards_from_hrefs(add_part[1])
        decks.append(deck)
    return decks


def _parse_card_tokens(tokens: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "★":
            i += 1
            continue
        count = 1
        if re.match(r"^×\d+$", tok):
            count = int(tok.replace("×", ""))
            i += 1
            if i >= len(tokens):
                break
        if re.match(r"^\d+$", tok) and i + 1 < len(tokens):
            i += 1
            continue
        name = resolve_card_name(tok)
        if name.get("id"):
            cards.append({"count": count, "name": tok, **name})
        i += 1
    return cards


def _consume_card_slots(tokens: list[str], card_ids: list[int], start: int) -> tuple[list[dict[str, Any]], int]:
    cards: list[dict[str, Any]] = []
    idx = start
    for tok in tokens:
        if tok == "★":
            count = 1
        elif re.match(r"^×\d+$", tok):
            count = int(tok.replace("×", ""))
        else:
            continue
        if idx >= len(card_ids):
            break
        entry = _card_from_dbfid(card_ids[idx], count)
        idx += 1
        if entry.get("id"):
            cards.append(entry)
    return cards, idx


def _count_slot_tokens(tokens: list[str]) -> int:
    return sum(1 for tok in tokens if tok == "★" or re.match(r"^×\d+$", tok))


def _cards_from_id_slice(card_ids: list[int], start: int, end: int) -> list[dict[str, Any]]:
    return [_card_from_dbfid(did) for did in card_ids[start:end] if _card_from_dbfid(did).get("id")]


def extract_arena_winning_decks_from_links(
    links: list[dict[str, str]], lines: list[str]
) -> list[dict[str, Any]]:
    card_ids: list[int] = []
    for item in links:
        href = item.get("href", "")
        if "UNDERGROUND_ARENA" not in href:
            continue
        match = CARD_HREF_RE.search(href)
        if match:
            card_ids.append(int(match.group(1)))

    deck_metas: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i] not in ARENA_CLASS_MARKERS:
            i += 1
            continue
        meta: dict[str, Any] = {
            "class": lines[i],
            "record": None,
            "player": None,
            "played_at": None,
            "legendary_group": None,
            "final_tokens": [],
            "disc_tokens": [],
            "add_tokens": [],
        }
        i += 1
        while i < len(lines):
            line = lines[i]
            if line in ARENA_CLASS_MARKERS:
                break
            if line == "Record" and i + 1 < len(lines):
                meta["record"] = lines[i + 1]
                i += 2
                continue
            if line in ("Player", "Игрок") and i + 1 < len(lines):
                meta["player"] = lines[i + 1]
                if i + 2 < len(lines) and lines[i + 2] not in ARENA_CLASS_MARKERS:
                    meta["played_at"] = lines[i + 2]
                i += 3
                continue
            if any(line == m for m in FINAL_DECK_MARKERS):
                i += 1
                while i < len(lines) and not any(
                    lines[i] == m
                    for m in DISCARD_MARKERS + ADDED_MARKERS + LEGENDARY_MARKERS
                ) and lines[i] not in ARENA_CLASS_MARKERS:
                    if lines[i] == "★" or re.match(r"^×\d+$", lines[i]):
                        meta["final_tokens"].append(lines[i])
                    i += 1
                continue
            if any(line == m for m in DISCARD_MARKERS):
                i += 1
                while i < len(lines) and not any(
                    lines[i] == m for m in ADDED_MARKERS + LEGENDARY_MARKERS
                ) and lines[i] not in ARENA_CLASS_MARKERS:
                    if lines[i] == "★" or re.match(r"^×\d+$", lines[i]):
                        meta["disc_tokens"].append(lines[i])
                    i += 1
                continue
            if any(line == m for m in ADDED_MARKERS):
                i += 1
                while i < len(lines) and not any(
                    lines[i] == m for m in LEGENDARY_MARKERS
                ) and lines[i] not in ARENA_CLASS_MARKERS:
                    if lines[i] == "★" or re.match(r"^×\d+$", lines[i]):
                        meta["add_tokens"].append(lines[i])
                    i += 1
                continue
            if any(line == m for m in LEGENDARY_MARKERS):
                if i + 1 < len(lines) and lines[i + 1] not in ARENA_CLASS_MARKERS:
                    meta["legendary_group"] = lines[i + 1]
                i += 2
                continue
            i += 1
        deck_metas.append(meta)

    decks: list[dict[str, Any]] = []
    link_idx = 0
    per_deck = max(len(card_ids) // max(len(deck_metas), 1), 1)
    for idx, meta in enumerate(deck_metas):
        chunk_end = len(card_ids) if idx + 1 == len(deck_metas) else min(link_idx + per_deck, len(card_ids))
        chunk = card_ids[link_idx:chunk_end]
        link_idx = chunk_end
        n_final = _count_slot_tokens(meta["final_tokens"])
        n_disc = _count_slot_tokens(meta["disc_tokens"])
        n_add = _count_slot_tokens(meta["add_tokens"])
        pos = 0
        deck: dict[str, Any] = {
            "class": meta["class"],
            "record": meta["record"],
            "player": meta["player"],
            "played_at": meta["played_at"],
            "legendary_group": meta["legendary_group"],
            "final_deck": [],
            "discarded": [],
            "added": [],
        }
        if n_final:
            deck["final_deck"], pos = _consume_card_slots(meta["final_tokens"], chunk, pos)
        if n_disc:
            deck["discarded"], pos = _consume_card_slots(meta["disc_tokens"], chunk, pos)
        if n_add:
            deck["added"], pos = _consume_card_slots(meta["add_tokens"], chunk, pos)
        if pos < len(chunk):
            rest = _cards_from_id_slice(chunk, pos, len(chunk))
            if not deck["discarded"] and not deck["added"]:
                half = len(rest) // 2
                deck["discarded"] = rest[:half]
                deck["added"] = rest[half:]
            elif not deck["discarded"]:
                deck["discarded"] = rest
            elif not deck["added"]:
                deck["added"] = rest
        decks.append(deck)
    return decks


def extract_arena_cards_from_links(links: list[dict[str, str]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in links:
        href = item.get("href", "")
        if "UNDERGROUND_ARENA" not in href:
            continue
        match = CARD_HREF_RE.search(href)
        if not match:
            continue
        dbf_id = int(match.group(1))
        if dbf_id in seen:
            continue
        seen.add(dbf_id)
        text = _clean(item.get("text", ""))
        entry = _card_from_dbfid(dbf_id)
        m = re.match(r"^(\d+)\s*(★)?\s*(.+)$", text)
        if m:
            entry["mana"] = int(m.group(1))
            entry["name"] = m.group(3).strip()
        _apply_stats_to_card(entry, [text] if text else [])
        cards.append(entry)
    return cards


def extract_bg_heroes_from_links(links: list[dict[str, str]]) -> list[dict[str, Any]]:
    heroes: dict[int, dict[str, Any]] = {}
    for item in links:
        match = HERO_HREF_RE.search(item.get("href", ""))
        if not match:
            continue
        dbf_id = int(match.group(1))
        label = _clean(item.get("text", ""))
        heroes[dbf_id] = {
            "hero": _hero_display_name(dbf_id, label),
            "dbfId": dbf_id,
            "id": (cards_by_dbfid().get(dbf_id) or {}).get("id"),
        }
    return list(heroes.values())


def extract_ranked_cards_from_links(links: list[dict[str, str]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in links:
        match = CARD_HREF_RE.search(item.get("href", ""))
        if not match or "UNDERGROUND_ARENA" in item.get("href", ""):
            continue
        dbf_id = int(match.group(1))
        if dbf_id in seen:
            continue
        seen.add(dbf_id)
        text = _clean(item.get("text", ""))
        entry = _card_from_dbfid(dbf_id)
        m = re.match(r"^(\d+)\s*(★)?\s*(.+)$", text)
        if m:
            entry["mana"] = int(m.group(1))
            entry["name"] = m.group(3).strip()
        cards.append(entry)
    return cards


def extract_for_source(
    source_id: str,
    soup: BeautifulSoup,
    html: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    link_items = [
        {"text": _clean(a.get_text()), "href": a.get("href", "")}
        for a in soup.find_all("a", href=True)
    ]
    if source_id == "hsreplay_battlegrounds_heroes":
        heroes = extract_bg_heroes(soup)
        if len(heroes) < 20:
            heroes = extract_bg_heroes_from_links(link_items)
        for h in heroes:
            h["hero"] = _hero_display_name(int(h.get("dbfId") or 0), str(h.get("hero", "")))
        return {
            "type": "bg_heroes",
            "heroes": heroes,
            "blocked": len(heroes) < 20,
        }
    if source_id == "hsreplay_battlegrounds_comps":
        comps = extract_bg_comps(soup)
        if len(comps) < 3:
            comps = extract_bg_comps_from_links(link_items)
        return {"type": "bg_comps", "comps": comps, "blocked": len(comps) < 3}
    if source_id in ("hsreplay_battlegrounds_trinkets_lesser", "hsreplay_battlegrounds_trinkets_greater"):
        trinkets = extract_bg_trinkets(soup)
        if len(trinkets) < 5:
            from .structured import parse_bg_trinkets

            lines = [_clean(x) for x in soup.get_text("\n").splitlines() if _clean(x)]
            trinkets = parse_bg_trinkets(lines)
        return {"type": "bg_trinkets", "trinkets": trinkets}
    if source_id == "hsreplay_arena_winning_decks":
        lines = [_clean(x) for x in soup.get_text("\n").splitlines() if _clean(x)]
        decks = extract_arena_winning_decks(soup, html)
        if not any(d.get("final_deck") for d in decks):
            decks = extract_arena_winning_decks_from_links(link_items, lines)
        return {"type": "arena_winning_decks", "decks": decks}
    if source_id.startswith("hsreplay_cards_"):
        cards = _merge_cards(
            extract_ranked_cards(soup),
            cards_from_snapshot(snapshot, arena=False),
        )
        if len(cards) < 30:
            cards = _merge_cards(cards, extract_ranked_cards_from_links(link_items))
        blocked = "could not load data" in html.lower()
        return {"type": "card_stats", "cards": cards, "blocked": blocked and len(cards) < 10}
    if source_id == "hsreplay_arena_cards_advanced":
        cards = _merge_cards(
            extract_arena_cards(soup),
            cards_from_snapshot(snapshot, arena=True),
        )
        if len(cards) < 30:
            cards = _merge_cards(cards, extract_arena_cards_from_links(link_items))
        total = None
        m = re.search(r"Total Cards:\s*([\d,]+)", html, re.I)
        if m:
            total = m.group(1).replace(",", "")
        if snapshot and snapshot.get("lines"):
            for line in snapshot["lines"]:
                m2 = re.search(r"Total Cards:\s*([\d,]+)", str(line), re.I)
                if m2:
                    total = m2.group(1).replace(",", "")
                    break
        return {"type": "arena_card_tiers", "cards": cards, "total_cards": total}
    return {}
