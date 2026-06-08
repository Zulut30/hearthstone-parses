from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .config import flaresolverr_url, request_timeout_seconds
from .hsreplay_auth import hsreplay_cookies_for_fetch
from .hsreplay_client import fetch_text_via_flaresolverr
from .sources import Source

logger = logging.getLogger(__name__)

_HERO_RE = re.compile(r"/battlegrounds/heroes/(\d+)")
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?%")
_AVG_PLACEMENT_RE = re.compile(r"\d+[,.]\d+")
_TIER_LABELS = {"s", "a", "b", "c", "d", "e", "f"}
_AUTH_MARKERS = (
    "account/login",
    "sign in",
    "log in",
    "войти",
    "premium",
    "subscription",
    "подпис",
)
_HERO_STATS_API = (
    "https://hsreplay.net/api/v1/battlegrounds/heroes/"
    "?BattlegroundsMMRPercentile=TOP_50_PERCENT&BattlegroundsTimeRange=LAST_7_DAYS"
)


def _texts(element: Any) -> list[str]:
    return [text.strip() for text in element.stripped_strings if text.strip()]


def _tier_for_card(card: Any) -> str | None:
    node = card.parent
    while node and getattr(node, "name", None) != "body":
        parts = _texts(node)
        if parts and parts[0].lower() in _TIER_LABELS:
            return parts[0].upper()
        node = node.parent
    return None


def _hero_card_for_anchor(anchor: Any) -> Any | None:
    node = anchor
    while node and getattr(node, "name", None) != "body":
        if getattr(node, "name", None) in {"div", "li", "article", "section"}:
            parts = _texts(node)
            text = node.get_text(" ", strip=True)
            has_pick_rate = any(_PERCENT_RE.fullmatch(part) for part in parts) or bool(
                _PERCENT_RE.search(text)
            )
            has_avg = any(_AVG_PLACEMENT_RE.fullmatch(part) for part in parts) or bool(
                _AVG_PLACEMENT_RE.search(text)
            )
            text_len = len(text)
            if has_pick_rate and has_avg and text_len < 1200:
                return node
        node = node.parent
    return None


def _looks_unauthenticated(html: str) -> bool:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _pct(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}%"


def _json_rows_from_text(text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(text, "html.parser")
    candidates = [pre.get_text() for pre in soup.find_all("pre")] or [text]
    for candidate in candidates:
        if "hero_dbf_id" not in candidate:
            continue
        starts = [idx for idx in (candidate.find("["), candidate.find("{")) if idx >= 0]
        start = min(starts) if starts else -1
        if start < 0:
            continue
        try:
            raw = json.loads(candidate[start:])
        except ValueError:
            continue
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        if isinstance(raw, dict):
            data = raw.get("data") or raw.get("results") or raw.get("series", {}).get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
    return []


def parse_hsreplay_bg_hero_stats_text(text: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in _json_rows_from_text(text):
        dbf_id = row.get("hero_dbf_id")
        if dbf_id is None:
            continue
        distribution = row.get("final_placement_distribution") or []
        if not isinstance(distribution, list):
            distribution = []
        placement_distribution = [
            pct for value in distribution if (pct := _pct(value)) is not None
        ]
        out[int(dbf_id)] = {
            "hero_dbf_id": int(dbf_id),
            "placement_distribution": placement_distribution,
            "tier_v2": str(row.get("tier_v2")).upper() if row.get("tier_v2") else None,
            "api_pick_rate": _pct(row.get("pick_rate")),
            "api_avg_placement": round(float(row["avg_final_placement"]), 2)
            if row.get("avg_final_placement") is not None
            else None,
            "best_composition_id": row.get("best_composition"),
        }
    return out


def merge_hero_stats(
    heroes: list[dict[str, Any]],
    stats_by_dbf: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    for hero in heroes:
        dbf_id = hero.get("dbfId")
        if dbf_id is None:
            continue
        stats = stats_by_dbf.get(int(dbf_id))
        if not stats:
            continue
        if stats.get("placement_distribution"):
            hero["placement_distribution"] = stats["placement_distribution"]
        if stats.get("tier_v2"):
            hero["tier"] = stats["tier_v2"]
        hero["best_composition_id"] = stats.get("best_composition_id")
    return heroes


def parse_hsreplay_bg_heroes_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    heroes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for anchor in soup.find_all("a", href=_HERO_RE):
        match = _HERO_RE.search(anchor.get("href", ""))
        if not match:
            continue
        dbf_id = int(match.group(1))
        if dbf_id in seen:
            continue
        card = _hero_card_for_anchor(anchor)
        if card is None:
            continue
        parts = _texts(card)
        if not parts:
            continue
        pick_rate: str | None = None
        best_comp: str | None = None
        avg_placement: str | None = None
        pick_idx = next((i for i, part in enumerate(parts) if _PERCENT_RE.fullmatch(part)), None)
        if pick_idx is not None and pick_idx + 2 < len(parts):
            pick_rate = parts[pick_idx]
            best_comp = parts[pick_idx + 1]
            avg_placement = next(
                (part for part in parts[pick_idx + 2 :] if _AVG_PLACEMENT_RE.fullmatch(part)),
                None,
            )
        if not (pick_rate and best_comp and avg_placement):
            text = card.get_text(" ", strip=True)
            match_stats = re.search(
                r"(?P<pick>\d+(?:[.,]\d+)?%)\s+(?P<best>[^\d%]+?)\s+(?P<avg>\d+[,.]\d+)",
                text,
            )
            if match_stats:
                pick_rate = match_stats.group("pick")
                best_comp = match_stats.group("best").strip()
                avg_placement = match_stats.group("avg")
        if not (pick_rate and best_comp and avg_placement):
            continue
        heroes.append(
            {
                "hero": parts[0],
                "dbfId": dbf_id,
                "pick_rate": pick_rate,
                "best_comp": best_comp,
                "avg_placement": avg_placement,
                "tier": _tier_for_card(card),
            }
        )
        seen.add(dbf_id)
    return heroes


async def fetch_hsreplay_battlegrounds_heroes(source: Source) -> dict[str, Any]:
    cookies = hsreplay_cookies_for_fetch()
    if not any(cookie.get("name") == "sessionid" for cookie in cookies):
        raise RuntimeError("HSReplay auth storage does not contain sessionid")
    timeout = max(float(request_timeout_seconds()), 120.0) + 20.0
    payload = {
        "cmd": "request.get",
        "url": source.url,
        "maxTimeout": int(timeout * 1000),
        "cookies": cookies,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(flaresolverr_url(), json=payload)
        response.raise_for_status()
        result = response.json()
    solution = result.get("solution") or {}
    html = solution.get("response") or ""
    status = int(solution.get("status") or 0)
    if status >= 400 or "Just a moment" in html or "cf-browser-verification" in html:
        raise RuntimeError(f"HSReplay Battlegrounds heroes blocked or unavailable (status={status})")
    heroes = parse_hsreplay_bg_heroes_html(html)
    if len(heroes) < 30 and _looks_unauthenticated(html):
        raise RuntimeError("HSReplay session not authenticated or premium data unavailable")
    try:
        stats_text = await fetch_text_via_flaresolverr(
            _HERO_STATS_API,
            source_id=source.id,
        )
        heroes = merge_hero_stats(heroes, parse_hsreplay_bg_hero_stats_text(stats_text))
    except Exception as exc:
        logger.warning("Could not enrich HSReplay BG heroes placement distribution: %s", exc)
    return {
        "type": "bg_heroes",
        "heroes": heroes,
        "blocked": False,
        "source": {
            "backend": "hsreplay_premium_flaresolverr",
            "status": status,
            "url": solution.get("url") or source.url,
        },
        "filters": {
            "mmr_percentile": "TOP_50_PERCENT",
            "time_range": "LAST_7_DAYS",
        },
    }
