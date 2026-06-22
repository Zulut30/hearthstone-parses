from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import api_key, cors_allowed_origins
from .demo import build_demo_view, build_overview
from .fetcher import refresh_sources
from .sources import SOURCES, SOURCE_BY_ID
from .storage import load_dataset, load_status, root_dir, save_dataset, save_status


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ACTIVE_TRINKET_SOURCE_IDS = {
    "hsreplay_battlegrounds_trinkets_lesser",
    "hsreplay_battlegrounds_trinkets_greater",
}

app = FastAPI(
    title="Hearthstone Data API",
    version="0.1.0",
    description="Cached API for configured Hearthstone public data sources.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "X-API-Key"],
)

if WEB_DIR.is_dir():
    app.mount("/ui/assets", StaticFiles(directory=WEB_DIR), name="ui-assets")


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API key is not configured")
    if x_api_key == expected:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


@app.get("/")
def redirect_to_ui() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/ui")
def demo_index() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Demo UI not installed")
    return FileResponse(index)


@app.get("/ui/logs")
def ops_logs_ui() -> FileResponse:
    page = WEB_DIR / "logs.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Ops logs UI not installed")
    return FileResponse(page)


@app.get("/ui/technologies")
def technologies_ui() -> FileResponse:
    page = WEB_DIR / "technologies.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Technologies UI not installed")
    return FileResponse(page)


@app.get("/ops/summary", dependencies=[Depends(require_admin)])
def ops_summary(since_hours: float = Query(24.0, ge=1.0, le=168.0)) -> dict:
    from .refresh_log import build_summary

    return build_summary(since_hours=since_hours)


@app.get("/ops/events", dependencies=[Depends(require_admin)])
def ops_events(
    limit: int = Query(200, ge=1, le=2000),
    source_id: str | None = None,
    event: str | None = None,
    action: str | None = None,
    action_group: str | None = None,
    level: str | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    since_hours: float | None = Query(None, ge=0.1, le=168.0),
) -> dict:
    from .refresh_log import read_events

    return {
        "events": read_events(
            limit=limit,
            source_id=source_id,
            event=event,
            action=action,
            action_group=action_group,
            level=level,
            trace_id=trace_id,
            run_id=run_id,
            since_hours=since_hours,
        )
    }


@app.get("/ops/trace/{trace_id}", dependencies=[Depends(require_admin)])
def ops_trace(trace_id: str) -> dict:
    from .refresh_log import build_trace_timeline

    return build_trace_timeline(trace_id)


@app.get("/ops/run/{run_id}", dependencies=[Depends(require_admin)])
def ops_run(run_id: str) -> dict:
    from .refresh_log import build_run_timeline

    return build_run_timeline(run_id)


@app.get("/ops/health", dependencies=[Depends(require_admin)])
def ops_health() -> dict:
    return build_health_diagnostics()


@app.get("/demo/overview")
def demo_overview() -> dict:
    return build_overview()


@app.get("/demo/view/{source_id}")
def demo_view(source_id: str) -> dict:
    if source_id not in SOURCE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown source")
    return build_demo_view(source_id)


def source_payload(source_id: str) -> dict:
    source = SOURCE_BY_ID[source_id]
    status = load_status(source_id)
    dataset = load_dataset(source_id)
    return {
        "id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "description": source.description,
        "status": status,
        "has_dataset": dataset is not None,
        "dataset_fetched_at": dataset.get("fetched_at") if dataset else None,
    }


def _active_trinkets_only(structured: dict[str, Any]) -> dict[str, Any]:
    trinkets = structured.get("trinkets")
    if not isinstance(trinkets, list):
        return structured
    active = [
        row
        for row in trinkets
        if isinstance(row, dict) and (row.get("pick_rate") or row.get("avg_placement"))
    ]
    filtered = dict(structured)
    filtered["trinkets"] = active
    filtered["active_trinkets"] = len(active)
    filtered["hidden_inactive_trinkets"] = len(trinkets) - len(active)
    return filtered


def public_dataset_payload(source_id: str, dataset: dict[str, Any]) -> dict[str, Any]:
    if source_id not in ACTIVE_TRINKET_SOURCE_IDS:
        return dataset
    payload = dict(dataset)
    data = dict(payload.get("data") or {})
    for key in ("structured", "hsreplay_extracted"):
        if isinstance(data.get(key), dict):
            data[key] = _active_trinkets_only(data[key])
    payload["data"] = data
    return payload


@app.get("/system/technologies")
def system_technologies() -> dict:
    from .tech_stack import build_technologies_payload

    return build_technologies_payload()


@app.get("/firecrawl/hsreplay/map")
def firecrawl_hsreplay_map() -> dict:
    from .firecrawl_map import load_hsreplay_map

    payload = load_hsreplay_map()
    if payload is None:
        raise HTTPException(status_code=404, detail="HSReplay Firecrawl map has not been generated yet")
    return payload


@app.get("/firecrawl/hsreplay/index")
def firecrawl_hsreplay_index() -> dict:
    from .firecrawl_map import load_hsreplay_index

    payload = load_hsreplay_index()
    if payload is None:
        raise HTTPException(status_code=404, detail="HSReplay Firecrawl index has not been generated yet")
    return payload


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "serving_ok": True,
        "degraded": False,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def build_health_diagnostics() -> dict:
    statuses = [load_status(source.id) for source in SOURCES]
    states: dict[str, int] = {}
    cached_sources: list[str] = []
    cached_after_failure_sources: list[str] = []
    hard_failed_sources: list[str] = []
    for source, status in zip(SOURCES, statuses, strict=True):
        state = status["state"] if status else "never_fetched"
        states[state] = states.get(state, 0) + 1
        if status and status.get("serving_cached_dataset"):
            cached_sources.append(source.id)
            if status.get("last_refresh_state") not in (None, "ok"):
                cached_after_failure_sources.append(source.id)
        if state != "ok":
            hard_failed_sources.append(source.id)

    from .stale_monitor import find_stale_sources

    stale_sources = find_stale_sources(include_ok=True)
    stale_ids = [str(item["source_id"]) for item in stale_sources]
    serving_ok = not hard_failed_sources
    freshness_ok = not stale_ids and not cached_sources
    return {
        "ok": serving_ok,
        "serving_ok": serving_ok,
        "freshness_ok": freshness_ok,
        "degraded": not (serving_ok and freshness_ok),
        "data_dir": str(root_dir()),
        "sources": len(SOURCES),
        "states": states,
        "hard_failed_sources": hard_failed_sources,
        "cached_sources": cached_sources,
        "cached_after_failure_sources": cached_after_failure_sources,
        "stale_sources": stale_ids,
        "stale_count": len(stale_ids),
        "cached_count": len(cached_sources),
        "cached_after_failure_count": len(cached_after_failure_sources),
    }


@app.get("/health/premium", dependencies=[Depends(require_admin)])
async def premium_health(live: bool = Query(False)) -> dict:
    from .premium_auth_health import build_premium_auth_health

    return await build_premium_auth_health(live=live)


@app.get("/sources")
def list_sources(site: str | None = None, category: str | None = None) -> dict:
    sources = SOURCES
    if site:
        sources = tuple(source for source in sources if source.site == site)
    if category:
        sources = tuple(source for source in sources if source.category == category)
    return {"sources": [source_payload(source.id) for source in sources]}


@app.get("/sources/{source_id}")
def get_source(source_id: str) -> dict:
    if source_id not in SOURCE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown source")
    return source_payload(source_id)


@app.get("/datasets")
def list_datasets() -> dict:
    return {
        "datasets": [
            {
                "source_id": source.id,
                "has_dataset": load_dataset(source.id) is not None,
                "status": load_status(source.id),
            }
            for source in SOURCES
        ]
    }


@app.get("/datasets/{source_id}")
def get_dataset(source_id: str) -> dict:
    if source_id not in SOURCE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown source")
    dataset = load_dataset(source_id)
    if dataset is None:
        status = load_status(source_id)
        raise HTTPException(
            status_code=404,
            detail={"message": "No successful dataset cached yet", "status": status},
        )
    return public_dataset_payload(source_id, dataset)


@app.post("/admin/refresh", dependencies=[Depends(require_admin)])
async def refresh(
    source_id: Annotated[list[str] | None, Query()] = None,
) -> dict:
    if source_id:
        missing = [item for item in source_id if item not in SOURCE_BY_ID]
        if missing:
            raise HTTPException(status_code=404, detail={"unknown_sources": missing})
    return {"results": await refresh_sources(source_id)}


@app.post("/admin/refresh/hsreplay-archetypes", dependencies=[Depends(require_admin)])
async def refresh_hsreplay_archetypes(
    limit: int | None = Query(None, ge=1, le=500),
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
    region: str = Query("REGION_EU", min_length=1, max_length=80),
) -> dict:
    from .hsreplay_archetypes_db import export_latest_archetypes_json, refresh_hsreplay_archetype_database

    result = await refresh_hsreplay_archetype_database(
        rank_range=rank_range,
        game_type=game_type,
        region=region,
        limit=limit,
    )
    result["export_path"] = str(export_latest_archetypes_json())
    return result


@app.put("/admin/datasets/{source_id}", dependencies=[Depends(require_admin)])
def upload_dataset(
    source_id: str,
    payload: Annotated[dict[str, Any], Body()],
) -> dict:
    if source_id not in SOURCE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown source")
    source = SOURCE_BY_ID[source_id]
    fetched_at = datetime.now(UTC).isoformat()
    dataset = {
        "state": "ok",
        "fetched_at": fetched_at,
        "http_status": None,
        "final_url": source.url,
        "content_length": None,
        "data": payload,
    }
    status = {
        "source_id": source.id,
        "site": source.site,
        "category": source.category,
        "url": source.url,
        "fetch_url": source.fetch_url,
        "fragment": source.fragment,
        "state": "ok",
        "fetched_at": fetched_at,
        "http_status": None,
        "final_url": source.url,
        "error": None,
        "detail": "Uploaded through the admin ingestion endpoint.",
        "content_length": None,
    }
    save_dataset(source_id, dataset)
    save_status(source_id, status)
    return {"ok": True, "source_id": source_id, "fetched_at": fetched_at}


@app.get("/api/db/decks")
def db_decks(
    class_name: str | None = Query(None, min_length=1, max_length=80),
    format_name: str | None = Query(None, min_length=1, max_length=80),
    source_id: str | None = Query(None, min_length=1, max_length=120),
    min_win_rate: float | None = None,
    q: str | None = Query(None, min_length=1, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
) -> dict:
    from .db import get_db_connection
    conn = get_db_connection()
    try:
        query = "SELECT * FROM decks WHERE 1=1"
        params = []
        if class_name:
            query += " AND class = ?"
            params.append(class_name)
        if format_name:
            query += " AND format = ?"
            params.append(format_name)
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if min_win_rate is not None:
            query += " AND win_rate >= ?"
            params.append(min_win_rate)
        if q:
            query += " AND (title LIKE ? OR archetype LIKE ? OR deck_code LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

        # Count total
        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = conn.execute(count_query, params).fetchone()[0]

        # Fetch page (sorted by updated_at or win_rate)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        decks = [dict(row) for row in rows]
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "decks": decks
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Database query failed")
    finally:
        conn.close()


@app.get("/api/db/archetypes")
def db_archetypes(
    class_name: str | None = Query(None, min_length=1, max_length=80),
    q: str | None = Query(None, min_length=1, max_length=120),
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
) -> dict:
    from .hsreplay_archetypes_db import latest_run, list_archetype_snapshots

    return {
        "latest_run": latest_run(),
        **list_archetype_snapshots(
            rank_range=rank_range,
            game_type=game_type,
            class_name=class_name,
            q=q,
            limit=limit,
            offset=offset,
        ),
    }


@app.get("/api/db/archetypes/{archetype_id}")
def db_archetype_detail(
    archetype_id: int,
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
) -> dict:
    from .hsreplay_archetypes_db import get_archetype_detail

    payload = get_archetype_detail(archetype_id, rank_range=rank_range, game_type=game_type)
    if payload is None:
        raise HTTPException(status_code=404, detail="Archetype snapshot not found")
    return payload


@app.get("/api/db/archetypes/{archetype_id}/mulligan")
def db_archetype_mulligan(
    archetype_id: int,
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
    display_only: bool = Query(True),
    limit: int = Query(40, ge=1, le=250),
) -> dict:
    from .db import get_db_connection
    from .hsreplay_archetypes_db import get_latest_archetype_snapshot

    snapshot = get_latest_archetype_snapshot(archetype_id, rank_range=rank_range, game_type=game_type)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Archetype snapshot not found")
    conn = get_db_connection()
    try:
        query = "SELECT * FROM archetype_mulligan WHERE snapshot_id = ?"
        params: list[Any] = [snapshot["id"]]
        if display_only:
            query += " AND display_row = 1"
        query += " ORDER BY hsreplay_rank ASC LIMIT ?"
        params.append(limit)
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        return {"snapshot": snapshot, "mulligan": rows}
    finally:
        conn.close()


@app.get("/api/db/archetypes/{archetype_id}/matchups")
def db_archetype_matchups(
    archetype_id: int,
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
    min_games: int = Query(0, ge=0, le=1000000),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    from .db import get_db_connection
    from .hsreplay_archetypes_db import get_latest_archetype_snapshot

    snapshot = get_latest_archetype_snapshot(archetype_id, rank_range=rank_range, game_type=game_type)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Archetype snapshot not found")
    conn = get_db_connection()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM archetype_matchups
                WHERE snapshot_id = ? AND COALESCE(total_games, 0) >= ?
                ORDER BY total_games DESC
                LIMIT ?
                """,
                (snapshot["id"], min_games, limit),
            ).fetchall()
        ]
        return {"snapshot": snapshot, "matchups": rows}
    finally:
        conn.close()


@app.get("/api/db/archetypes/{archetype_id}/decks")
def db_archetype_decks(
    archetype_id: int,
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
    include_cards: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    from .db import get_db_connection
    from .hsreplay_archetypes_db import get_archetype_deck_cards, get_latest_archetype_snapshot

    snapshot = get_latest_archetype_snapshot(archetype_id, rank_range=rank_range, game_type=game_type)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Archetype snapshot not found")
    conn = get_db_connection()
    try:
        decks = [
            dict(row)
            for row in conn.execute(
                """
                SELECT * FROM archetype_decks
                WHERE snapshot_id = ?
                ORDER BY total_games DESC
                LIMIT ?
                """,
                (snapshot["id"], limit),
            ).fetchall()
        ]
        if include_cards:
            for deck in decks:
                deck["cards"] = get_archetype_deck_cards(int(deck["id"]))
        return {"snapshot": snapshot, "decks": decks}
    finally:
        conn.close()


@app.get("/api/db/archetypes/{archetype_id}/history")
def db_archetype_history(
    archetype_id: int,
    rank_range: str = Query("LEGEND", min_length=1, max_length=80),
    game_type: str = Query("RANKED_STANDARD", min_length=1, max_length=80),
) -> dict:
    from .db import get_db_connection
    from .hsreplay_archetypes_db import get_latest_archetype_snapshot

    snapshot = get_latest_archetype_snapshot(archetype_id, rank_range=rank_range, game_type=game_type)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Archetype snapshot not found")
    conn = get_db_connection()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT series_name, point_date, value
                FROM archetype_time_series
                WHERE snapshot_id = ?
                ORDER BY series_name, point_date
                """,
                (snapshot["id"],),
            ).fetchall()
        ]
        return {"snapshot": snapshot, "history": rows}
    finally:
        conn.close()


@app.get("/api/db/cards/trends")
def db_card_trends(
    card_name: str = Query(..., min_length=1, max_length=120),
    source_id: str | None = Query(None, min_length=1, max_length=120),
    class_name: str | None = Query(None, min_length=1, max_length=80),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    from .db import get_db_connection
    conn = get_db_connection()
    try:
        query = "SELECT * FROM card_popularity_history WHERE card_name = ?"
        params = [card_name]
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if class_name:
            query += " AND class = ?"
            params.append(class_name)

        query += " ORDER BY recorded_at ASC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        trends = [dict(row) for row in rows]
        return {
            "card_name": card_name,
            "trends": trends
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Database query failed")
    finally:
        conn.close()
