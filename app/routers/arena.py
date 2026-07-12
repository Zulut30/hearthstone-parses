from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..storage import load_dataset
from .models import ApiMeta, ArenaClassRow, Envelope, timestamp_is_stale


router = APIRouter(prefix="/v1/arena", tags=["v1-arena"])

ARENA_CLASS_SOURCES = {
    "hsreplay_arena",
    "hsreplay_arena_class_pages_firecrawl",
}


@router.get(
    "/classes",
    response_model=Envelope[list[ArenaClassRow]],
    response_model_exclude_none=True,
)
def classes(
    source_id: str = Query("hsreplay_arena_class_pages_firecrawl"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
) -> Envelope[list[ArenaClassRow]]:
    if source_id not in ARENA_CLASS_SOURCES:
        raise HTTPException(status_code=422, detail="Unsupported arena class source")
    dataset = load_dataset(source_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Arena class dataset is not cached")
    structured = ((dataset.get("data") or {}).get("structured") or {})
    all_rows = [row for row in (structured.get("classes") or []) if isinstance(row, dict)]
    rows = all_rows[offset : offset + limit]
    fetched_at = str(dataset.get("fetched_at")) if dataset.get("fetched_at") else None
    return Envelope(
        data=[ArenaClassRow.model_validate(row) for row in rows],
        meta=ApiMeta(
            source_id=source_id,
            fetched_at=fetched_at,
            stale=timestamp_is_stale(fetched_at),
            count=len(all_rows),
            limit=limit,
            offset=offset,
        ),
    )
