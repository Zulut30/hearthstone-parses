from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import data_dir

HSJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
CACHE_PATH = Path(data_dir()) / "hearthstonejson.cards.enUS.json"
CACHE_TTL_SECONDS = 86400

_cache: dict[str, Any] | None = None


def _load_raw_cards() -> list[dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache["cards"]

    if CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _cache = payload
            return payload["cards"]

    response = httpx.get(HSJSON_URL, timeout=120.0)
    response.raise_for_status()
    cards = response.json()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"fetched_at": time.time(), "cards": cards}, ensure_ascii=False),
        encoding="utf-8",
    )
    _cache = {"cards": cards}
    return cards


def cards_by_dbfid() -> dict[int, dict[str, Any]]:
    index: dict[int, dict[str, Any]] = {}
    for card in _load_raw_cards():
        dbf = card.get("dbfId")
        if dbf is not None:
            index[int(dbf)] = card
    return index


def card_label(card: dict[str, Any] | None) -> dict[str, Any]:
    if not card:
        return {"id": None, "dbfId": None, "name": "Unknown", "cost": None, "type": None}
    return {
        "id": card.get("id"),
        "dbfId": card.get("dbfId"),
        "name": card.get("name"),
        "cost": card.get("cost"),
        "type": card.get("type"),
        "rarity": card.get("rarity"),
    }
