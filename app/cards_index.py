from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .config import data_dir
from .refresh_log import log_action

HSJSON_URL_EN = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
HSJSON_URL_RU = "https://api.hearthstonejson.com/v1/latest/ruRU/cards.json"
CACHE_PATH_EN = Path(data_dir()) / "hearthstonejson.cards.enUS.json"
CACHE_PATH_RU = Path(data_dir()) / "hearthstonejson.cards.ruRU.json"
CACHE_TTL_SECONDS = 86400
STALE_RETRY_SECONDS = 300
MIN_CARD_COUNT = 5_000

logger = logging.getLogger(__name__)
_cache_lock = threading.RLock()

_cache_en: dict[str, Any] | None = None
_cache_ru: dict[str, Any] | None = None
_by_dbf: dict[int, dict[str, Any]] | None = None
_by_id: dict[str, dict[str, Any]] | None = None
_by_name_en: dict[str, dict[str, Any]] | None = None
_by_name_ru: dict[str, dict[str, Any]] | None = None


def _invalidate_indexes(locale: str) -> None:
    global _by_dbf, _by_id, _by_name_en, _by_name_ru
    if locale == "ruRU":
        _by_name_ru = None
        return
    _by_dbf = None
    _by_id = None
    _by_name_en = None


def _set_memory_cache(locale: str, payload: dict[str, Any]) -> None:
    global _cache_en, _cache_ru
    if locale == "ruRU":
        if _cache_ru is not payload:
            _invalidate_indexes(locale)
        _cache_ru = payload
    else:
        if _cache_en is not payload:
            _invalidate_indexes(locale)
        _cache_en = payload


def _read_cache_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    cards = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards, list) or not cards:
        return None
    fetched_at = payload.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        try:
            fetched_at = path.stat().st_mtime
        except OSError:
            fetched_at = 0.0
    return {"fetched_at": float(fetched_at), "cards": cards}


def _write_cache_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _valid_fresh_payload(cards: Any, *, previous_count: int) -> list[dict[str, Any]]:
    if not isinstance(cards, list) or not all(isinstance(card, dict) for card in cards):
        raise RuntimeError("HearthstoneJSON cards payload is not a list of objects")
    minimum = MIN_CARD_COUNT if previous_count == 0 else max(MIN_CARD_COUNT, int(previous_count * 0.70))
    if len(cards) < minimum:
        raise RuntimeError(
            f"HearthstoneJSON truncation guard rejected {len(cards)} cards; minimum {minimum}"
        )
    return cards


def _load_raw_cards(locale: str = "enUS") -> list[dict[str, Any]]:
    path = CACHE_PATH_RU if locale == "ruRU" else CACHE_PATH_EN
    url = HSJSON_URL_RU if locale == "ruRU" else HSJSON_URL_EN
    with _cache_lock:
        now = time.time()
        cached = _cache_ru if locale == "ruRU" else _cache_en
        if cached is not None and now < float(cached.get("retry_after") or 0):
            return cached["cards"]
        if cached is not None and now - float(cached.get("fetched_at") or 0) < CACHE_TTL_SECONDS:
            return cached["cards"]

        disk_payload = _read_cache_file(path) if path.exists() else None
        if disk_payload is not None and now - disk_payload["fetched_at"] < CACHE_TTL_SECONDS:
            _set_memory_cache(locale, disk_payload)
            return disk_payload["cards"]

        stale_payload = disk_payload or cached
        previous_count = len((stale_payload or {}).get("cards") or [])
        try:
            response = httpx.get(url, timeout=120.0)
            response.raise_for_status()
            cards = _valid_fresh_payload(response.json(), previous_count=previous_count)
        except Exception as exc:
            if stale_payload is None:
                raise
            logger.warning(
                "HearthstoneJSON refresh failed for %s; serving %s stale cards: %s",
                locale,
                previous_count,
                exc,
            )
            retry_payload = {**stale_payload, "retry_after": now + STALE_RETRY_SECONDS}
            _set_memory_cache(locale, retry_payload)
            return retry_payload["cards"]

        payload = {"fetched_at": now, "cards": cards}
        _write_cache_file(path, payload)
        _set_memory_cache(locale, payload)
        try:
            log_action(
                "refresh.hearthstonejson.updated",
                extra={"locale": locale, "cards": len(cards)},
            )
        except Exception:
            logger.debug("Failed to log HearthstoneJSON cache refresh", exc_info=True)
        return cards


def cards_by_id() -> dict[str, dict[str, Any]]:
    global _by_id
    cards = _load_raw_cards()
    if _by_id is None:
        _by_id = {}
        for card in cards:
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
    cards = _load_raw_cards()
    if _by_dbf is None:
        _by_dbf = {}
        for card in cards:
            dbf = card.get("dbfId")
            if dbf is not None:
                _by_dbf[int(dbf)] = card
    return _by_dbf


def cards_by_name(locale: str = "enUS") -> dict[str, dict[str, Any]]:
    global _by_name_en, _by_name_ru
    cards = _load_raw_cards(locale)
    if locale == "ruRU":
        if _by_name_ru is None:
            _by_name_ru = {}
            for card in cards:
                name = card.get("name")
                if name:
                    _by_name_ru[name.lower()] = card
        return _by_name_ru
    if _by_name_en is None:
        _by_name_en = {}
        for card in cards:
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


def prefetch_hearthstonejson() -> None:
    """Load enUS + ruRU card indexes into memory before parallel API refresh."""
    _load_raw_cards("enUS")
    _load_raw_cards("ruRU")
    cards_by_id()
    log_action("refresh.prefetch.cards", extra={"locales": ["enUS", "ruRU"]})


async def prefetch_hearthstonejson_async() -> None:
    await asyncio.to_thread(prefetch_hearthstonejson)


def card_label(card: dict[str, Any] | None) -> dict[str, Any]:
    if not card:
        return {
            "id": None,
            "dbfId": None,
            "name": "Unknown",
            "cost": None,
            "type": None,
            "rarity": None,
            "techLevel": None,
            "isBattlegroundsPoolMinion": None,
            "isBattlegroundsPoolSpell": None,
        }
    return {
        "id": card.get("id"),
        "dbfId": card.get("dbfId"),
        "name": card.get("name"),
        "cost": card.get("cost"),
        "type": card.get("type"),
        "rarity": card.get("rarity"),
        "cardClass": card.get("cardClass"),
        "techLevel": card.get("techLevel"),
        "isBattlegroundsPoolMinion": card.get("isBattlegroundsPoolMinion"),
        "isBattlegroundsPoolSpell": card.get("isBattlegroundsPoolSpell"),
    }
