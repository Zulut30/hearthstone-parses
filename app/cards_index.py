from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .config import data_dir

HSJSON_URL_EN = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
HSJSON_URL_RU = "https://api.hearthstonejson.com/v1/latest/ruRU/cards.json"
CACHE_PATH_EN = Path(data_dir()) / "hearthstonejson.cards.enUS.json"
CACHE_PATH_RU = Path(data_dir()) / "hearthstonejson.cards.ruRU.json"
CACHE_TTL_SECONDS = 86400

_cache_en: dict[str, Any] | None = None
_cache_ru: dict[str, Any] | None = None
_by_dbf: dict[int, dict[str, Any]] | None = None
_by_id: dict[str, dict[str, Any]] | None = None
_by_name_en: dict[str, dict[str, Any]] | None = None
_by_name_ru: dict[str, dict[str, Any]] | None = None


def _load_raw_cards(locale: str = "enUS") -> list[dict[str, Any]]:
    global _cache_en, _cache_ru
    cache_attr = "_cache_ru" if locale == "ruRU" else "_cache_en"
    path = CACHE_PATH_RU if locale == "ruRU" else CACHE_PATH_EN
    url = HSJSON_URL_RU if locale == "ruRU" else HSJSON_URL_EN
    cached = _cache_ru if locale == "ruRU" else _cache_en
    if cached is not None:
        return cached["cards"]

    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if locale == "ruRU":
                _cache_ru = payload
            else:
                _cache_en = payload
            return payload["cards"]

    response = httpx.get(url, timeout=120.0)
    response.raise_for_status()
    cards = response.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fetched_at": time.time(), "cards": cards}, ensure_ascii=False),
        encoding="utf-8",
    )
    payload = {"cards": cards}
    if locale == "ruRU":
        _cache_ru = payload
    else:
        _cache_en = payload
    return cards


def cards_by_id() -> dict[str, dict[str, Any]]:
    global _by_id
    if _by_id is None:
        _by_id = {}
        for card in _load_raw_cards():
            card_id = card.get("id")
            if card_id:
                _by_id[str(card_id)] = card
    return _by_id


def card_from_id(card_id: str, *, locale: str = "ruRU") -> dict[str, Any]:
    card = cards_by_id().get(card_id)
    if not card and locale == "ruRU":
        card = cards_by_id().get(card_id)
    meta = card_label(card)
    if locale == "ruRU" and card:
        ru = cards_by_name("ruRU").get((card.get("name") or "").lower())
        if ru and ru.get("name"):
            meta["name"] = ru["name"]
    return meta


def cards_by_dbfid() -> dict[int, dict[str, Any]]:
    global _by_dbf
    if _by_dbf is None:
        _by_dbf = {}
        for card in _load_raw_cards():
            dbf = card.get("dbfId")
            if dbf is not None:
                _by_dbf[int(dbf)] = card
    return _by_dbf


def cards_by_name(locale: str = "enUS") -> dict[str, dict[str, Any]]:
    global _by_name_en, _by_name_ru
    if locale == "ruRU":
        if _by_name_ru is None:
            _by_name_ru = {}
            for card in _load_raw_cards("ruRU"):
                name = card.get("name")
                if name:
                    _by_name_ru[name.lower()] = card
        return _by_name_ru
    if _by_name_en is None:
        _by_name_en = {}
        for card in _load_raw_cards("enUS"):
            name = card.get("name")
            if name:
                _by_name_en[name.lower()] = card
    return _by_name_en


def resolve_card_name(name: str) -> dict[str, Any]:
    clean = re.sub(r"^★\s*", "", name.strip())
    card = cards_by_name("enUS").get(clean.lower())
    if not card:
        card = cards_by_name("ruRU").get(clean.lower())
    return card_label(card)


def card_label(card: dict[str, Any] | None) -> dict[str, Any]:
    if not card:
        return {"id": None, "dbfId": None, "name": "Unknown", "cost": None, "type": None, "rarity": None}
    return {
        "id": card.get("id"),
        "dbfId": card.get("dbfId"),
        "name": card.get("name"),
        "cost": card.get("cost"),
        "type": card.get("type"),
        "rarity": card.get("rarity"),
        "cardClass": card.get("cardClass"),
    }
