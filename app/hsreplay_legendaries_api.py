from __future__ import annotations

from typing import Any

from hearthstone.enums import CardClass

from .cards_index import card_from_id
from .hsreplay_client import fetch_hsreplay_json

LEGENDARIES_URL = "https://hsreplay.net/arena/legendaries/"
LEGENDARIES_API_URL = "https://hsreplay.net/api/v1/arena/card_packages/free/"

HS_CLASS_MAP = {
    "DEATHKNIGHT": "Death Knight",
    "DEMONHUNTER": "Demon Hunter",
    "DRUID": "Druid",
    "HUNTER": "Hunter",
    "MAGE": "Mage",
    "PALADIN": "Paladin",
    "PRIEST": "Priest",
    "ROGUE": "Rogue",
    "SHAMAN": "Shaman",
    "WARLOCK": "Warlock",
    "WARRIOR": "Warrior",
    "NEUTRAL": "Neutral",
}


def _class_name_from_card(card_id: str) -> str | None:
    from .cards_index import cards_by_id

    raw = cards_by_id().get(card_id) or {}
    cc = raw.get("cardClass") or raw.get("class")
    if cc:
        return HS_CLASS_MAP.get(str(cc).upper(), str(cc).replace("_", " ").title())
    return None


def _group_package_cards(card_ids: list[str], *, locale: str = "ruRU") -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for card_id in card_ids:
        if not card_id:
            continue
        if card_id in grouped:
            grouped[card_id]["count"] = int(grouped[card_id].get("count") or 1) + 1
        else:
            grouped[card_id] = {"count": 1, "card_id": card_id, **card_from_id(card_id, locale=locale)}
    return list(grouped.values())


def normalize_legendary_package(pkg: dict[str, Any], *, locale: str = "ruRU") -> dict[str, Any] | None:
    key_id = pkg.get("package_key_card_id")
    if not key_id:
        return None
    key_card = {"card_id": key_id, **card_from_id(str(key_id), locale=locale)}
    included = _group_package_cards(list(pkg.get("package_card_ids") or []), locale=locale)
    win_rate = pkg.get("win_rate")
    winrate = f"{win_rate}%" if win_rate is not None and "%" not in str(win_rate) else win_rate
    pick_rate = pkg.get("pick_rate") or pkg.get("pickRate")
    offer_rate = pkg.get("offer_rate") or pkg.get("offerRate")
    return {
        "key_card": key_card,
        "legendary_card": key_card,
        "cards": included,
        "winrate": winrate,
        "pick_rate": f"{pick_rate}%" if pick_rate is not None and "%" not in str(pick_rate) else pick_rate,
        "offer_rate": f"{offer_rate}%" if offer_rate is not None and "%" not in str(offer_rate) else offer_rate,
        "class": _class_name_from_card(str(key_id)),
    }


async def fetch_legendary_groups(
    *,
    source_id: str = "hsreplay_arena_legendaries",
    locale: str = "ruRU",
) -> dict[str, Any]:
    payload = await fetch_hsreplay_json(LEGENDARIES_API_URL, source_id=source_id)
    data = payload.get("data") or {}
    packages = data.get("ALL") if isinstance(data, dict) else []
    if not isinstance(packages, list):
        packages = []

    groups: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        group = normalize_legendary_package(pkg, locale=locale)
        if group:
            groups.append(group)

    return {
        "type": "arena_legendary_groups",
        "groups": groups,
        "source": {
            "key": "hsreplay",
            "url": LEGENDARIES_URL,
            "api_url": LEGENDARIES_API_URL,
            "backend": "hsreplay_api",
        },
    }
