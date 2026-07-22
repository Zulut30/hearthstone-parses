from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from ..hsguru_meta_matrix import MIN_GAMES, SOURCE_ID
from ..storage import load_dataset
from .models import ApiMeta, timestamp_is_stale


router = APIRouter(prefix="/v1/hsguru", tags=["v1-hsguru"])


@router.get("/meta")
def hsguru_meta(
    format_name: Literal["standard", "wild"] = Query("standard", alias="format"),
    rank: Literal["all", "legend", "diamond_4to1", "top_5k", "top_legend"] = "all",
    period: Literal["past_day", "past_3_days", "past_week", "past_2_weeks"] = "past_day",
    coin: Literal["any_player", "going_first", "on_coin"] = "any_player",
    min_games: int = Query(100),
) -> dict:
    if min_games not in MIN_GAMES:
        raise HTTPException(status_code=422, detail={"allowed_min_games": MIN_GAMES})
    dataset = load_dataset(SOURCE_ID)
    if not dataset:
        raise HTTPException(status_code=503, detail="HSGuru meta matrix is not available yet")
    structured = ((dataset.get("data") or {}).get("structured") or {})
    key = "|".join((format_name, rank, period, coin))
    selected = next(
        (item for item in structured.get("slices") or [] if item.get("key") == key),
        None,
    )
    if selected is None:
        raise HTTPException(status_code=503, detail="Requested HSGuru meta slice is unavailable")
    items = [
        row for row in selected.get("rows") or []
        if int(row.get("games") or 0) >= min_games
    ]
    fetched_at = dataset.get("fetched_at") or structured.get("fetched_at")
    return {
        "data": {
            "format": format_name,
            "rank": rank,
            "period": period,
            "coin": coin,
            "min_games": min_games,
            "source_url": selected.get("source_url"),
            "items": items,
        },
        "meta": ApiMeta(
            source_id=SOURCE_ID,
            fetched_at=fetched_at,
            stale=timestamp_is_stale(fetched_at, max_age_hours=36),
            count=len(items),
        ).model_dump(exclude_none=True),
    }
