from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .deck_decode import first_deck_code_from_text
from .firecrawl_backend import scrape_source_with_options
from .sources import Source


HSGURU_DECKS_URL = "https://www.hsguru.com/decks"
_CACHE_TTL_SECONDS = 6 * 60 * 60
_EMPTY_CACHE_TTL_SECONDS = 10 * 60
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_inflight: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}
_inflight_lock = asyncio.Lock()

_CLASS_NAMES = {
    "deathknight": "DeathKnight",
    "demonhunter": "DemonHunter",
    "druid": "Druid",
    "hunter": "Hunter",
    "mage": "Mage",
    "paladin": "Paladin",
    "priest": "Priest",
    "rogue": "Rogue",
    "shaman": "Shaman",
    "warlock": "Warlock",
    "warrior": "Warrior",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(value).lower()).strip()


def _number(value: str) -> float | None:
    match = re.search(r"-?[\d.,]+", value)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_hsguru_decks_html(
    page_html: str,
    *,
    archetype: str,
    format_name: str,
    fetched_at: str | None = None,
    trust_exact_filter: bool = False,
) -> list[dict[str, Any]]:
    """Parse only exact-archetype deck cards from a filtered HSGuru page."""
    expected_archetype = _key(archetype)
    expected_format = format_name.strip().lower()
    timestamp = fetched_at or datetime.now(UTC).isoformat()
    soup = BeautifulSoup(page_html, "lxml")
    rows: list[dict[str, Any]] = []

    for card in soup.select('[id^="deck_stats-"]'):
        copy_button = card.select_one("button[data-clipboard-text]")
        deck_text = html.unescape(str(copy_button.get("data-clipboard-text") or "")) if copy_button else ""
        title_match = re.search(r"^###\s+(.+?)\s*$", deck_text, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""
        if not trust_exact_filter and _key(title) != expected_archetype:
            continue

        parsed_format = re.search(r"^#\s*Format:\s*(.+?)\s*$", deck_text, flags=re.MULTILINE)
        deck_format = parsed_format.group(1).strip() if parsed_format else format_name.title()
        if deck_format.lower() != expected_format:
            continue
        deck_code = first_deck_code_from_text(deck_text) or ""
        if not deck_code:
            continue

        deck_info = card.select_one(".decklist-info")
        class_token = next(
            (token for token in (deck_info.get("class") or []) if token in _CLASS_NAMES),
            "",
        ) if deck_info else ""
        class_name = _CLASS_NAMES.get(class_token, "Neutral")
        card_text = card.get_text(" ", strip=True)
        games_match = re.search(r"Games:\s*([\d\s,]+)", card_text, flags=re.IGNORECASE)
        games = int(re.sub(r"\D", "", games_match.group(1))) if games_match else None
        winrate_node = card.select_one("span.tag.column span")
        winrate = _number(winrate_node.get_text(" ", strip=True)) if winrate_node else None
        url_match = re.search(r"https://www\.hsguru\.com/deck/\d+", deck_text)
        source_url = url_match.group(0) if url_match else ""

        rows.append(
            {
                "source_id": "hsguru_decks",
                "title": title,
                # HSGuru's exact archetype filter may return deck titles with
                # rune prefixes (for example FUU/BUU/UUB). Keep the requested
                # aggregate archetype as the API identity and the full build
                # title separately.
                "archetype": archetype if trust_exact_filter else title,
                "class": class_name,
                "format": deck_format,
                "deck_code": deck_code,
                "win_rate": winrate,
                "score": f"{games} games" if games is not None else None,
                "games": games,
                "url": source_url,
                "updated_at": timestamp,
            }
        )

    return sorted(
        rows,
        key=lambda row: (int(row.get("games") or 0), float(row.get("win_rate") or 0)),
        reverse=True,
    )


async def _fetch_attempt(archetype: str, format_name: str, params: list[tuple[str, object]]) -> list[dict[str, Any]]:
    format_id = 2 if format_name == "standard" else 1
    url = str(
        httpx.URL(
            HSGURU_DECKS_URL,
            params=[
                ("format", format_id),
                ("player_deck_archetype[]", archetype),
                *params,
            ],
        )
    )
    source = Source(
        id="hsguru_exact_deck",
        url=url,
        site="hsguru",
        category="exact_deck",
    )
    result = await scrape_source_with_options(
        source,
        formats=["html"],
        only_main_content=True,
        # Firecrawl can reuse a recent identical lookup across API restarts. The
        # in-process result cache below still controls the public response TTL.
        max_age_ms=_CACHE_TTL_SECONDS * 1_000,
        wait_ms=3_000,
        timeout_ms=25_000,
    )
    if "deck_stats_viewport" not in result.html:
        raise RuntimeError("HSGuru exact deck page is incomplete")
    return parse_hsguru_decks_html(
        result.html,
        archetype=archetype,
        format_name=format_name,
        trust_exact_filter=True,
    )


async def _fetch_exact(archetype: str, format_name: str, rank: str) -> list[dict[str, Any]]:
    attempts = [[("rank", rank), ("period", "past_30_days"), ("min_games", 10)]]
    if rank != "all":
        attempts.append([("rank", "all"), ("period", "past_30_days"), ("min_games", 10)])
    last_error: Exception | None = None
    for params in attempts:
        try:
            rows = await _fetch_attempt(archetype, format_name, params)
        except Exception as exc:
            last_error = exc
            continue
        if rows:
            return rows
    if last_error is not None:
        raise last_error
    return []


async def exact_hsguru_decks(archetype: str, format_name: str, rank: str) -> list[dict[str, Any]]:
    cache_key = f"{format_name}:{rank}:{_key(archetype)}"
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    async with _inflight_lock:
        task = _inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(_fetch_exact(archetype, format_name, rank))
            _inflight[cache_key] = task
    try:
        rows = await task
        ttl = _CACHE_TTL_SECONDS if rows else _EMPTY_CACHE_TTL_SECONDS
        _cache[cache_key] = (time.monotonic() + ttl, rows)
        return rows
    finally:
        async with _inflight_lock:
            if _inflight.get(cache_key) is task:
                _inflight.pop(cache_key, None)
