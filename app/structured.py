from __future__ import annotations

import re
from typing import Any

from .cards_index import resolve_card_name
from .sources import SOURCE_BY_ID, Source

PERCENT_RE = re.compile(r"^\d+(\.\d+)?%$")
INT_RE = re.compile(r"^\d+$")
DECK_LINK_RE = re.compile(
    r"^(?P<name>.+?)\s+(?:Live now|\d[\d,]*)\s+Winrate\s+(?P<winrate>\d+(?:\.\d+)?%)"
    r"\s+Games\s+(?P<games>[\d,]+)(?:\s+Avg Duration\s+(?P<duration>[\d.]+ min))?",
    re.I,
)


def _is_percent(value: str) -> bool:
    return bool(PERCENT_RE.match(value.strip()))


def _is_int(value: str) -> bool:
    return bool(INT_RE.match(value.strip()))


def parse_legendary_groups(lines: list[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i] != "Included Cards:":
            i += 1
            continue
        cards: list[dict[str, Any]] = []
        i += 1
        while i < len(lines) and lines[i] not in ("Winrate", "Included Cards:"):
            if _is_int(lines[i]) and i + 1 < len(lines) and not _is_percent(lines[i + 1]):
                count = int(lines[i])
                name = lines[i + 1]
                resolved = resolve_card_name(name)
                cards.append({"count": count, "name": name, **resolved})
                i += 2
            else:
                i += 1
        stats: dict[str, Any] = {}
        while i < len(lines) and lines[i] != "Included Cards:":
            key = lines[i]
            if key in ("Winrate", "Pick Rate", "Offer Rate", "Score") and i + 1 < len(lines):
                stats[key.lower().replace(" ", "_")] = lines[i + 1]
                i += 2
            else:
                i += 1
        groups.append({"cards": cards, **stats})
    return groups


def parse_winning_decks(lines: list[str]) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    classes = {
        "Death Knight", "Demon Hunter", "Druid", "Hunter", "Mage",
        "Paladin", "Priest", "Rogue", "Shaman", "Warlock", "Warrior",
        "Рыцарь смерти", "Охотник на демонов", "Друид", "Охотник", "Маг",
        "Паладин", "Жрец", "Разбойник", "Шаман", "Чернокнижник", "Воин",
    }
    i = 0
    while i < len(lines):
        if lines[i] not in classes:
            i += 1
            continue
        hero_class = lines[i]
        record = None
        player = None
        played_at = None
        j = i + 1
        while j < len(lines) and j < i + 8:
            if lines[j] == "Record" and j + 1 < len(lines):
                record = lines[j + 1]
            if lines[j] == "Player" and j + 1 < len(lines):
                player = lines[j + 1]
                if j + 2 < len(lines):
                    played_at = lines[j + 2]
            if lines[j] in classes and j > i:
                break
            if lines[j] == "Final Deck":
                break
            j += 1
        decks.append(
            {
                "class": hero_class,
                "record": record,
                "player": player,
                "played_at": played_at,
            }
        )
        i = j if j > i + 1 else i + 1
    return decks


def parse_trending_decks(links: list[dict[str, str]]) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links:
        href = link.get("href") or ""
        if "/decks/" not in href or href in seen or "#tab=" in href:
            continue
        text = link.get("text") or ""
        match = DECK_LINK_RE.search(text)
        if not match:
            continue
        seen.add(href)
        deck_id = href.split("/decks/")[1].split("/")[0].split("#")[0]
        decks.append(
            {
                "name": match.group("name").strip(),
                "winrate": match.group("winrate"),
                "games": match.group("games"),
                "duration": match.group("duration"),
                "deck_url": href,
                "hsreplay_deck_id": deck_id,
            }
        )
    return decks


_HERO_SKIP = {
    "Tier", "Hero", "Pick Rate", "Best Composition", "Avg. Placement",
    "Placement Distribution", "Unlock with", "Tier7", "All Minion Types",
    "APPLY", "RESET", "SUBSCRIBE NOW", "—", ".",
}
_DESC_PREFIXES = (
    "At ", "On ", "Get ", "Discover", "Whenever", "Your ", "After ", "Choose ",
    "The ", "If ", "Each ", "All ", "When ", "Play ", "Repeat ", "Triple ",
    "Minions", "Cards", "spells", "to ", "two ", "a ", "an ",
)


def _looks_like_hero_name(line: str) -> bool:
    if line in _HERO_SKIP or len(line) < 3 or len(line) > 55:
        return False
    if _is_percent(line) or line.startswith("(") or line.startswith("×"):
        return False
    if line[0].islower() or line.startswith(_DESC_PREFIXES):
        return False
    if line.isdigit() or line in {"Record", "Player", "Final Deck", "Quests", "Trinket"}:
        return False
    return True


def parse_bg_heroes(lines: list[str]) -> list[dict[str, Any]]:
    heroes: list[dict[str, Any]] = []
    start = 0
    for i, line in enumerate(lines):
        if line == "Placement Distribution":
            start = i + 1
            break
    i = start
    current: dict[str, Any] | None = None
    while i < len(lines):
        line = lines[i]
        if _is_percent(line):
            if current is not None:
                current["pick_rate"] = line
                heroes.append(current)
                current = None
            i += 1
            continue
        if line in _HERO_SKIP or line.startswith("("):
            i += 1
            continue
        if _looks_like_hero_name(line):
            if current is not None:
                heroes.append(current)
            current = {"hero": line, "description": ""}
            i += 1
            continue
        if current is not None:
            part = line if line != "." else ""
            if part:
                current["description"] = (current["description"] + " " + part).strip()[:200]
        i += 1
    if current is not None:
        heroes.append(current)
    return [h for h in heroes if h.get("pick_rate")][:50]


def parse_hsguru_matchups(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tables:
        return []
    table = tables[0]
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    if len(headers) < 3 or not rows:
        return []
    columns = headers[2:]
    pairs: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 2:
            continue
        if "%" in str(row[0]):
            continue
        row_arch = row[1] if len(row) > 1 else ""
        if not row_arch or row_arch in ("Winrate", "Seed Weights Reset Weights Popularity: Archetype"):
            continue
        for ci, col in enumerate(columns):
            idx = ci + 2
            if idx >= len(row):
                break
            val = row[idx]
            if val is None or val == "":
                continue
            pairs.append(
                {
                    "archetype": row_arch,
                    "vs": col,
                    "winrate": val if "%" in str(val) else f"{val}%",
                }
            )
    return pairs


def _parse_percent_value(value: str) -> str | None:
    v = value.strip().replace(",", ".")
    if "%" in v:
        return v
    try:
        float(v)
        return f"{v}%"
    except ValueError:
        return None


def parse_cards_from_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for table in tables:
        headers = [str(h).strip() for h in (table.get("headers") or [])]
        rows = table.get("rows") or []
        objects = table.get("objects") or []
        if objects and not headers:
            for obj in objects:
                name = None
                for key, val in obj.items():
                    if not val or not isinstance(val, str):
                        continue
                    kl = key.lower()
                    if "card" in kl or kl == "карта" or key == "column_1":
                        if len(val) > 2 and not _is_percent(val):
                            name = val
                            break
                if not name:
                    continue
                resolved = resolve_card_name(name)
                if not resolved.get("id"):
                    continue
                entry: dict[str, Any] = {"name": name, **resolved}
                for key, val in obj.items():
                    kl = key.lower()
                    if not val:
                        continue
                    if "winrate" in kl or "винрейт" in kl or "побед" in kl:
                        entry["deck_winrate"] = val
                    elif "popularity" in kl or ("%" in str(val) and "deck" in kl):
                        entry["deck_popularity"] = val
                    elif "copies" in kl or "копи" in kl:
                        entry["avg_copies"] = val
                    elif "played" in kl or "разыгран" in kl:
                        entry["times_played"] = val
                    elif "pick" in kl or "частота" in kl:
                        entry["pick_rate"] = val
                    elif val.replace(",", ".").replace("%", "").replace(".", "", 1).isdigit() and "%" in str(val):
                        entry.setdefault("deck_popularity", val)
                cards.append(entry)
            continue
        if not headers:
            continue
        header_lc = [h.lower() for h in headers]
        if not any("card" in h or "карт" in h for h in header_lc):
            if len(headers) >= 2 and rows:
                headers = ["Card"] + [f"stat_{i}" for i in range(1, len(headers))]
                header_lc = [h.lower() for h in headers]
            else:
                continue
        name_idx = next((i for i, h in enumerate(header_lc) if "card" in h or h == "карта"), 0)
        stat_map: dict[str, int] = {}
        for i, h in enumerate(header_lc):
            if "winrate" in h or "винрейт" in h or "побед" in h:
                stat_map.setdefault("deck_winrate", i)
            elif "popularity" in h or "%" in h and "deck" in h:
                stat_map.setdefault("deck_popularity", i)
            elif "copies" in h or "копи" in h:
                stat_map.setdefault("avg_copies", i)
            elif "played" in h or "разыгран" in h:
                stat_map.setdefault("times_played", i)
            elif "pick" in h or "выбор" in h or "частота" in h:
                stat_map.setdefault("pick_rate", i)
        for row in table.get("rows") or []:
            if name_idx >= len(row):
                continue
            name = str(row[name_idx]).strip()
            if len(name) < 2:
                continue
            resolved = resolve_card_name(name)
            entry: dict[str, Any] = {"name": name, **resolved}
            for key, idx in stat_map.items():
                if idx < len(row):
                    entry[key] = row[idx]
            if resolved.get("id"):
                cards.append(entry)
    return cards


def parse_card_stats_lines(lines: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i] == "★":
            i += 1
            continue
        if lines[i].isdigit() and int(lines[i]) <= 10:
            mana = int(lines[i])
            i += 1
            if i < len(lines) and lines[i] == "★":
                i += 1
            if i >= len(lines):
                break
            name = lines[i]
            resolved = resolve_card_name(name)
            if resolved.get("id"):
                entry: dict[str, Any] = {"name": name, "mana": mana, **resolved}
                i += 1
                stats: list[str] = []
                while i < len(lines):
                    if lines[i] == "★" or (lines[i].isdigit() and int(lines[i]) <= 10):
                        break
                    if _is_percent(lines[i]) or lines[i].replace(",", ".").replace(".", "", 1).isdigit():
                        stats.append(lines[i])
                        i += 1
                        continue
                    if resolve_card_name(lines[i]).get("id"):
                        break
                    i += 1
                if stats:
                    entry["deck_popularity"] = next((s for s in stats if "%" in s), stats[0])
                    if len(stats) > 1:
                        entry["avg_copies"] = stats[1] if "%" not in stats[1] else None
                cards.append(entry)
            continue
        i += 1
    return cards


def parse_arena_card_lines(lines: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i] == "★":
            i += 1
            continue
        if lines[i].isdigit() and int(lines[i]) <= 10:
            mana = int(lines[i])
            i += 1
            if i < len(lines) and lines[i] == "★":
                i += 1
            if i >= len(lines):
                break
            name = lines[i]
            resolved = resolve_card_name(name)
            if resolved.get("id"):
                cards.append({"name": name, "mana": mana, **resolved})
            i += 1
            continue
        i += 1
    return cards


_TRINKET_SKIP = {
    "Tier", "Trinket", "Pick Rate", "Avg. Placement", "Placement Distribution",
    "APPLY", "RESET", "SUBSCRIBE NOW", "Tier7", "Trinket Guide", "Top BGs Player",
    "s", "—", ".",
}


def _looks_like_trinket_name(line: str) -> bool:
    if line in _TRINKET_SKIP or len(line) < 4 or len(line) > 60:
        return False
    if _is_percent(line) or line[0].islower() or line.startswith(_DESC_PREFIXES):
        return False
    if line.isdigit() or line.endswith(" Place") or "Place:" in line:
        return False
    if line.endswith(".") or line.endswith(","):
        return False
    return True


def parse_bg_trinkets(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start = 0
    for i, line in enumerate(lines):
        if line == "Placement Distribution":
            start = i + 1
            break
    i = start
    current: dict[str, Any] | None = None
    while i < len(lines):
        line = lines[i]
        if _is_percent(line) and "Place" not in line:
            if current is not None:
                current["pick_rate"] = line
                if i + 1 < len(lines) and not _is_percent(lines[i + 1]) and lines[i + 1].replace(".", "", 1).isdigit():
                    current["avg_placement"] = lines[i + 1]
                items.append(current)
                current = None
            i += 1
            continue
        if line in _TRINKET_SKIP or line.startswith("(") or "Place:" in line:
            i += 1
            continue
        if _looks_like_trinket_name(line):
            if current is not None:
                items.append(current)
            current = {"name": line, "description": ""}
            i += 1
            continue
        if current is not None and not _looks_like_trinket_name(line):
            current["description"] = (current.get("description", "") + " " + line).strip()[:180]
        i += 1
    if current is not None:
        items.append(current)
    return [t for t in items if t.get("pick_rate")][:80]


def parse_arena_matrix(tables: list[dict[str, Any]], lines: list[str]) -> list[dict[str, Any]]:
    if tables and tables[0].get("objects"):
        return tables[0]["objects"][:50]
    pairs: list[dict[str, Any]] = []
    classes = [
        "Death Knight", "Demon Hunter", "Druid", "Hunter", "Mage",
        "Paladin", "Priest", "Rogue", "Shaman", "Warlock", "Warrior",
    ]
    i = 0
    while i + 2 < len(lines):
        if lines[i] in classes and _is_percent(lines[i + 2]):
            pairs.append({"class_a": lines[i], "class_b": lines[i + 1], "winrate": lines[i + 2]})
            i += 3
        else:
            i += 1
    return pairs[:60]


def build_structured(source: Source, data: dict[str, Any]) -> dict[str, Any]:
    extracted = data.get("hsreplay_extracted") or {}
    if extracted.get("type"):
        return extracted

    lines = data.get("text_preview") or []
    tables = data.get("tables") or []
    links = data.get("links") or []
    sid = source.id

    if source.site == "hsguru":
        if source.category == "meta":
            rows = []
            for table in tables:
                rows.extend(table.get("objects") or [])
            return {"type": "meta", "strategies": rows}
        if source.category == "streamer_decks":
            return {"type": "streamer_decks", "rows": tables[0].get("objects") if tables else []}
        if source.category == "matchups":
            return {"type": "matchups", "matchups": parse_hsguru_matchups(tables)}

    if sid == "hsreplay_arena_legendaries":
        return {"type": "arena_legendary_groups", "groups": parse_legendary_groups(lines)}
    if sid == "hsreplay_arena_winning_decks":
        return {"type": "arena_winning_decks", "decks": parse_winning_decks(lines)}
    if sid == "hsreplay_decks_trending":
        return {"type": "trending_decks", "decks": parse_trending_decks(links)}
    if sid == "hsreplay_battlegrounds_heroes":
        blocked = any("повторите попытку" in l.lower() or "try again later" in l.lower() for l in lines)
        heroes = [] if blocked else parse_bg_heroes(lines)
        return {"type": "bg_heroes", "heroes": heroes, "blocked": blocked}
    if sid == "hsreplay_arena":
        return {"type": "arena_class_matrix", "matchups": parse_arena_matrix(tables, lines)}
    if sid == "hsreplay_battlegrounds_comps":
        blocked = any("sign in" in l.lower() for l in lines[:40]) and not any(
            "comp" in l.lower() and "%" in l for l in lines
        )
        comps = [
            l for l in lines
            if len(l) > 5 and len(l) < 80 and any(k in l.lower() for k in ("comp", "build", "tier"))
        ][:40]
        return {"type": "bg_comps", "blocked": blocked, "comps": comps}
    if sid in ("hsreplay_battlegrounds_trinkets_lesser", "hsreplay_battlegrounds_trinkets_greater"):
        return {"type": "bg_trinkets", "trinkets": parse_bg_trinkets(lines)}
    if sid.startswith("hsreplay_cards_"):
        blocked = any("could not load" in l.lower() for l in lines)
        cards = parse_cards_from_tables(tables) if not blocked else []
        if len(cards) < 10:
            start = 0
            for i, line in enumerate(lines):
                if line in ("Карта", "Card"):
                    start = i + 1
                    break
            cards = parse_card_stats_lines(lines[start:]) if not blocked else []
        return {"type": "card_stats", "blocked": blocked, "cards": cards}
    if sid == "hsreplay_arena_cards_advanced":
        cards = parse_cards_from_tables(tables)
        if len(cards) < 10:
            cards = parse_arena_card_lines(lines)
        return {
            "type": "arena_card_tiers",
            "cards": cards,
            "total_cards": next((l for l in lines if l.isdigit() and int(l) > 100), None),
        }

    return {"type": "raw", "lines": lines[:80]}
