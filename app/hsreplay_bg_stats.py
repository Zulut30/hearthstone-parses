from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from .cards_index import card_label, cards_by_dbfid
from .hsreplay_client import fetch_hsreplay_json, fetch_text_via_flaresolverr

BG_MMR = "TOP_50_PERCENT"
BG_TIME_RANGE = "LAST_7_DAYS"
BG_ANALYTICS_BASE = "https://hsreplay.net/analytics/query"
BG_COMPOSITION_NAMES_API = "https://hsreplay.net/api/v1/battlegrounds/compositions/?hl=en"
COMPOSITION_RU_NAMES = {
    "Beasts": "Звери",
    "Demons": "Демоны",
    "Dragons": "Драконы",
    "Elementals": "Элементали",
    "Mechs": "Механизмы",
    "Murlocs": "Мурлоки",
    "Naga": "Нага",
    "Pirates": "Пираты",
    "Quilboar": "Свинобраз",
    "Undead": "Нежить",
}


def _pct(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}%"


def _round(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _pct_number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return 0.0


def _query_url(key: str) -> str:
    return (
        f"{BG_ANALYTICS_BASE}/{key}/"
        f"?BattlegroundsMMRPercentile={BG_MMR}&BattlegroundsTimeRange={BG_TIME_RANGE}"
    )


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = (payload.get("series") or {}).get("data")
    return data if isinstance(data, list) else []


def _card_from_dbf(dbf_id: int) -> dict[str, Any]:
    return card_label(cards_by_dbfid().get(int(dbf_id)))


def _minion_stats(row: dict[str, Any]) -> dict[str, Any] | None:
    dbf_id = row.get("minion_dbf_id")
    if dbf_id is None:
        return None
    card = _card_from_dbf(int(dbf_id))
    if not card.get("id"):
        return None
    aggregates = row.get("normal_aggregates") or []
    if not isinstance(aggregates, list):
        aggregates = []

    with_count = 0.0
    without_count = 0.0
    with_places = 0.0
    without_places = 0.0
    wins = 0.0
    losses = 0.0

    for item in aggregates:
        if not isinstance(item, dict):
            continue
        combat_round = item.get("combat_round")
        if isinstance(combat_round, int) and not 1 <= combat_round <= 16:
            continue
        c_with = float(item.get("count_of_games_with_minion") or 0)
        c_without = float(item.get("count_of_games_without_minion") or 0)
        with_count += c_with
        without_count += c_without
        with_places += float(item.get("sum_of_placements_for_players_with_minion") or 0)
        without_places += float(item.get("sum_of_placements_for_players_without_minion") or 0)
        wins += float(item.get("total_wins") or 0)
        losses += float(item.get("total_losses") or 0)

    avg_with = with_places / with_count if with_count else None
    avg_without = without_places / without_count if without_count else None
    impact = (
        avg_without - avg_with
        if avg_with is not None and avg_without is not None
        else None
    )
    combat_winrate = wins / (wins + losses) * 100 if wins + losses else None
    popularity = with_count / (with_count + without_count) * 100 if with_count + without_count else None

    return {
        **card,
        "minion": card.get("name"),
        "minion_dbf_id": int(dbf_id),
        "tavern_tier": row.get("minion_tier") or card.get("techLevel"),
        "impact": _round(impact),
        "combat_winrate": _pct(combat_winrate),
        "win_share": _pct(combat_winrate),
        "popularity": _pct(popularity),
        "games_with_minion": int(with_count) if with_count else None,
    }


async def fetch_battlegrounds_minions(source_id: str) -> dict[str, Any]:
    url = _query_url("battlegrounds_minion_list")
    payload = await fetch_hsreplay_json(
        url,
        source_id=source_id,
        cache_key=f"bg:minions:{BG_MMR}:{BG_TIME_RANGE}",
    )
    minions = [
        item for row in _rows(payload) if (item := _minion_stats(row)) is not None
    ]
    minions.sort(key=lambda item: _pct_number(item.get("popularity")), reverse=True)
    return {
        "type": "bg_minions",
        "minions": minions,
        "filters": {"mmr_percentile": BG_MMR, "time_range": BG_TIME_RANGE, "turns": "1-16"},
        "source": {
            "key": "hsreplay",
            "url": "https://hsreplay.net/battlegrounds/minions/#view=advanced",
            "api_url": url,
            "backend": "hsreplay_bg_api",
            "rows": len(minions),
        },
    }


def _composition_names_from_text(text: str) -> dict[int, str]:
    soup = BeautifulSoup(text, "html.parser")
    pre = soup.find("pre")
    raw_text = pre.get_text() if pre else text
    try:
        raw = json.loads(raw_text or "[]")
    except json.JSONDecodeError:
        return {}
    out: dict[int, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            comp_id = item.get("comp_id")
            if comp_id is None:
                comp_id = item.get("id")
            if comp_id is None and isinstance(item.get("friendly_composition"), int):
                comp_id = item.get("friendly_composition")
            friendly_name = item.get("friendly_composition")
            name = item.get("comp_name") or item.get("name")
            if not name and isinstance(friendly_name, str):
                name = friendly_name
            if comp_id is not None and name:
                out[int(comp_id)] = COMPOSITION_RU_NAMES.get(str(name), str(name))
    return out


async def _fetch_composition_names(source_id: str) -> dict[int, str]:
    text = await fetch_text_via_flaresolverr(BG_COMPOSITION_NAMES_API, source_id=source_id)
    return _composition_names_from_text(text)


def _first_place_share(rows: list[dict[str, Any]]) -> dict[int, float]:
    weights: dict[int, float] = {}
    total = 0.0
    for row in rows:
        comp_id = row.get("friendly_composition")
        if comp_id is None or int(comp_id) < 0:
            continue
        distribution = row.get("final_placement_distribution") or []
        if not isinstance(distribution, list) or not distribution:
            continue
        weight = float(row.get("popularity") or 0) / 100 * float(distribution[0] or 0) / 100
        weights[int(comp_id)] = weight
        total += weight
    if not total:
        return {}
    return {comp_id: weight / total * 100 for comp_id, weight in weights.items()}


def _composition_row(
    row: dict[str, Any],
    names: dict[int, str],
    first_place_shares: dict[int, float] | None = None,
) -> dict[str, Any] | None:
    comp_id = row.get("friendly_composition")
    if comp_id is None or int(comp_id) < 0:
        return None
    distribution = row.get("final_placement_distribution") or []
    if not isinstance(distribution, list):
        distribution = []
    first_raw = float(distribution[0] if distribution else 0)
    popularity = float(row.get("popularity") or 0)
    first_place = (
        first_place_shares.get(int(comp_id))
        if first_place_shares is not None
        else first_raw
    )
    return {
        "composition_id": int(comp_id),
        "type": names.get(int(comp_id)) or f"Composition {comp_id}",
        "first_place": _pct(first_place),
        "avg_placement": _round(row.get("avg_final_placement")),
        "popularity": _pct(popularity),
        "placement_distribution": [_pct(value) for value in distribution],
        "games": row.get("num_games"),
    }


async def fetch_battlegrounds_compositions(source_id: str) -> dict[str, Any]:
    stats_url = _query_url("battlegrounds_comp_stats")
    payload = await fetch_hsreplay_json(
        stats_url,
        source_id=source_id,
        cache_key=f"bg:compositions:{BG_MMR}:{BG_TIME_RANGE}",
    )
    names = await _fetch_composition_names(source_id)
    rows = _rows(payload)
    first_place_shares = _first_place_share(rows)
    comps = [
        item
        for row in rows
        if isinstance(row, dict)
        if (item := _composition_row(row, names, first_place_shares)) is not None
    ]
    comps.sort(key=lambda item: _pct_number(item.get("first_place")), reverse=True)
    return {
        "type": "bg_compositions",
        "compositions": comps,
        "filters": {"mmr_percentile": BG_MMR, "time_range": BG_TIME_RANGE},
        "source": {
            "key": "hsreplay",
            "url": "https://hsreplay.net/battlegrounds/compositions/",
            "api_url": stats_url,
            "backend": "hsreplay_bg_api",
            "rows": len(comps),
        },
    }
