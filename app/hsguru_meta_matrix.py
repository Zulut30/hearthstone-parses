from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .firecrawl_backend import FirecrawlScrape, scrape_source_with_options
from .source_state import SourceState
from .sources import Source
from .storage import load_dataset, save_dataset, save_status


SOURCE_ID = "hsguru_meta_matrix"
HSGURU_META_URL = "https://www.hsguru.com/meta"
FORMATS = ("standard", "wild")
RANKS = ("all", "legend", "diamond_4to1", "top_5k", "top_legend")
PERIODS = ("past_day", "past_3_days", "past_week", "past_2_weeks")
COINS = ("any_player",)
MIN_GAMES = (100, 250, 500, 1000, 2500, 5000)

_FORMAT_QUERY = {"standard": "2", "wild": "1"}
_REQUIRED_HEADERS = {
    "archetype": "archetype",
    "winrate": "winrate",
    "popularity": "popularity",
    "turns": "turns",
    "duration": "duration_minutes",
    "climbing speed": "climbing_speed",
}


@dataclass(frozen=True)
class SliceSpec:
    format: str
    rank: str
    period: str
    coin: str
    key: str
    url: str


def iter_slice_specs() -> tuple[SliceSpec, ...]:
    specs = []
    for format_name, rank, period, coin in product(FORMATS, RANKS, PERIODS, COINS):
        params = {
            "format": _FORMAT_QUERY[format_name],
            "rank": rank,
            "period": period,
            "min_games": MIN_GAMES[0],
        }
        query = urlencode(params)
        key = "|".join((format_name, rank, period, coin))
        specs.append(SliceSpec(format_name, rank, period, coin, key, f"{HSGURU_META_URL}?{query}"))
    return tuple(specs)


def _number(value: str) -> float | None:
    match = re.search(r"[-+]?\d[\d\s.,]*", value.replace("\u00a0", " "))
    if not match:
        return None
    token = match.group(0).replace(" ", "")
    if token.count(",") == 1 and "." not in token:
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def _games(value: str) -> int | None:
    match = re.search(r"\(([\d\s,.]+)\)", value)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def _header(value: str) -> str:
    return re.sub(r"[^a-z]+", " ", value.lower()).strip()


def _validate_row(row: dict[str, Any]) -> bool:
    return (
        bool(row["archetype"])
        and isinstance(row["games"], int)
        and row["games"] >= 0
        and row["winrate"] is not None
        and 0 <= row["winrate"] <= 100
        and row["popularity"] is not None
        and 0 <= row["popularity"] <= 100
        and row["turns"] is not None
        and row["turns"] >= 0
        and row["duration_minutes"] is not None
        and row["duration_minutes"] >= 0
        and row["climbing_speed"] is not None
    )


def parse_meta_rows(page_html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(page_html, "lxml")
    selected = None
    indexes: dict[str, int] = {}
    for table in soup.find_all("table"):
        header_row = table.find("thead") or table.find("tr")
        headers = [_header(cell.get_text(" ", strip=True)) for cell in header_row.find_all("th")]
        candidate = {
            field: headers.index(label)
            for label, field in _REQUIRED_HEADERS.items()
            if label in headers
        }
        if len(candidate) == len(_REQUIRED_HEADERS):
            selected = table
            indexes = candidate
            break
    if selected is None:
        return []

    rows: list[dict[str, Any]] = []
    table_rows = selected.select("tbody tr") or selected.find_all("tr")[1:]
    for row_number, tr in enumerate(table_rows, start=1):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if len(cells) <= max(indexes.values()):
            raise ValueError(f"HSGuru meta row {row_number} has missing columns")
        archetype = re.sub(r"\s+", " ", cells[indexes["archetype"]]).strip()
        popularity_cell = cells[indexes["popularity"]]
        games = _games(popularity_cell)
        if not archetype or games is None:
            raise ValueError(f"HSGuru meta row {row_number} has no archetype or game count")
        row = {
            "archetype": archetype,
            "winrate": _number(cells[indexes["winrate"]]),
            "popularity": _number(popularity_cell),
            "games": games,
            "turns": _number(cells[indexes["turns"]]),
            "duration_minutes": _number(cells[indexes["duration_minutes"]]),
            "climbing_speed": _number(cells[indexes["climbing_speed"]]),
        }
        if not _validate_row(row):
            raise ValueError(f"HSGuru meta row {row_number} has invalid statistics")
        rows.append(row)
    archetypes = [row["archetype"].casefold() for row in rows]
    if len(archetypes) != len(set(archetypes)):
        raise ValueError("HSGuru meta table contains duplicate archetypes")
    return rows


async def _default_scrape(spec: SliceSpec) -> FirecrawlScrape:
    source = Source(
        id=f"{SOURCE_ID}:{spec.key}",
        url=spec.url,
        site="hsguru",
        category="meta_matrix_slice",
    )
    return await scrape_source_with_options(
        source,
        formats=["html"],
        only_main_content=True,
        max_age_ms=0,
        wait_ms=5_000,
        timeout_ms=120_000,
    )


async def refresh_hsguru_meta_matrix(
    *,
    concurrency: int = 2,
    attempts: int = 3,
    scrape: Callable[[SliceSpec], Awaitable[FirecrawlScrape]] = _default_scrape,
) -> dict[str, Any]:
    fetched_at = datetime.now(UTC).isoformat()
    specs = iter_slice_specs()
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 5)))
    errors: list[dict[str, str]] = []

    async def fetch_one(spec: SliceSpec) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                async with semaphore:
                    result = await scrape(spec)
                rows = parse_meta_rows(result.html)
                if not rows:
                    raise RuntimeError("HSGuru meta table is missing or empty")
                return {
                    "key": spec.key,
                    "format": spec.format,
                    "rank": spec.rank,
                    "period": spec.period,
                    "coin": spec.coin,
                    "source_url": spec.url,
                    "rows": rows,
                    "row_counts": {
                        str(min_games): sum(1 for row in rows if int(row["games"]) >= min_games)
                        for min_games in MIN_GAMES
                    },
                    "content_length": result.content_length,
                    "credits_used": result.metadata.get("creditsUsed"),
                }
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
        errors.append(
            {
                "key": spec.key,
                "error": f"{type(last_error).__name__}: {str(last_error)[:300]}",
            }
        )
        return None

    slices = [item for item in await asyncio.gather(*(fetch_one(spec) for spec in specs)) if item]
    slices.sort(key=lambda item: item["key"])
    content_length = sum(int(item.pop("content_length", 0)) for item in slices)
    credits_used = sum(float(item.pop("credits_used") or 0) for item in slices)
    complete = len(slices) == len(specs) and not errors
    structured = {
        "type": "hsguru_meta_matrix",
        "schema_version": 3,
        "fetched_at": fetched_at,
        "dimensions": {
            "formats": list(FORMATS),
            "ranks": list(RANKS),
            "periods": list(PERIODS),
            "coins": list(COINS),
            "min_games": list(MIN_GAMES),
        },
        "base_slice_count": len(slices),
        "logical_slice_count": len(slices) * len(MIN_GAMES),
        "slices": slices,
        "firecrawl": {
            "requests": len(slices),
            "credits_used": int(credits_used) if credits_used.is_integer() else credits_used,
            "content_length": content_length,
        },
    }
    dataset = {
        "source_id": SOURCE_ID,
        "state": SourceState.OK,
        "fetched_at": fetched_at,
        "http_status": 200,
        "final_url": HSGURU_META_URL,
        "content_length": content_length,
        "backend": "firecrawl",
        "data": {"structured": structured},
    }
    cached_dataset = load_dataset(SOURCE_ID)
    if complete:
        save_dataset(SOURCE_ID, dataset)
    save_status(
        SOURCE_ID,
        {
            "source_id": SOURCE_ID,
            "site": "hsguru",
            "category": "meta_matrix",
            "url": HSGURU_META_URL,
            "state": SourceState.OK if complete else SourceState.PARTIAL,
            "fetched_at": fetched_at,
            "http_status": 200 if complete else None,
            "backend": "firecrawl",
            "detail": (
                f"HSGuru matrix: {len(slices)}/{len(specs)} slices, "
                f"{len(slices) * len(MIN_GAMES)}/{len(specs) * len(MIN_GAMES)} logical slices."
            ),
            "errors": errors[:20],
            "serving_cached_dataset": bool(cached_dataset) and not complete,
            "last_refresh_state": SourceState.OK if complete else SourceState.PARTIAL,
            "last_refresh_at": fetched_at,
            "firecrawl_requests": len(slices),
            "firecrawl_credits_used": structured["firecrawl"]["credits_used"],
        },
    )
    return {
        "ok": complete,
        "published": complete,
        "serving_cached_dataset": bool(cached_dataset) and not complete,
        "source_id": SOURCE_ID,
        "fetched_at": fetched_at,
        "base_slices": len(slices),
        "logical_slices": len(slices) * len(MIN_GAMES),
        "firecrawl_credits_used": structured["firecrawl"]["credits_used"],
        "content_length": content_length,
        "errors": errors,
    }
