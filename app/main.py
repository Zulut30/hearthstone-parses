from __future__ import annotations

import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import api_key, cors_allowed_origins, python_environment
from .demo import build_demo_view, build_overview
from .fetcher import refresh_sources
from .source_state import SourceState
from .sources import SOURCES, SOURCE_BY_ID
from .storage import load_dataset, load_status, root_dir, save_dataset, save_status
from .routers.constructed import router as constructed_v1_router
from .routers.bg import router as bg_v1_router
from .routers.arena import router as arena_v1_router
from .routers.system import router as system_v1_router
from .public_cache import PublicCacheMiddleware
from .http_observability import RequestObservabilityMiddleware, generic_server_error


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ACTIVE_TRINKET_SOURCE_IDS = {
    "hsreplay_battlegrounds_trinkets_lesser",
    "hsreplay_battlegrounds_trinkets_greater",
}
_HEALTH_CACHE_SECONDS = 15.0
_health_cache_lock = threading.Lock()
_health_cache_at = 0.0
_health_cache_payload: dict[str, Any] | None = None

app = FastAPI(
    title="Hearthstone Data API",
    version="0.1.0",
    description="Cached API for configured Hearthstone public data sources.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(PublicCacheMiddleware)
app.include_router(constructed_v1_router)
app.include_router(bg_v1_router)
app.include_router(arena_v1_router)
app.include_router(system_v1_router)


@app.on_event("startup")
def start_parser_control_worker() -> None:
    # Queued runs are persisted in the data directory. Starting the worker as
    # part of application startup resumes them after an API process restart.
    from .parser_control import parser_run_worker

    parser_run_worker().start()


@app.middleware("http")
async def no_cache_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/admin"):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Keep request correlation outside CORS, cache, and UI cache-control middleware
# so every HTTP response, including preflights and handled errors, gets an ID.
app.add_middleware(RequestObservabilityMiddleware)
app.add_exception_handler(Exception, generic_server_error)


if WEB_DIR.is_dir():
    app.mount("/ui/assets", StaticFiles(directory=WEB_DIR), name="ui-assets")


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API key is not configured")
    if x_api_key and secrets.compare_digest(x_api_key, expected):
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
    return cached_health_diagnostics()


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
        "semantic_quality": _semantic_dataset_quality(source_id, dataset),
    }


def _semantic_dataset_quality(
    source_id: str,
    dataset: dict[str, Any] | None,
) -> dict[str, Any] | None:
    structured = (((dataset or {}).get("data") or {}).get("structured") or {})
    if not structured:
        return None
    from .source_contracts import contract_quality_report
    from .source_validators import validate_structured

    semantic_report = validate_structured(source_id, structured)
    contract_report = contract_quality_report(source_id, structured)
    semantic_issues = [
        {
            "code": issue.code,
            "message": issue.message,
            "field": issue.field,
            "severity": issue.severity,
        }
        for issue in semantic_report.issues
    ]
    contract_issues = [
        {
            "code": "source_contract.failed",
            "message": warning,
            "field": None,
            "severity": "error",
        }
        for warning in contract_report.get("warnings") or []
    ]
    score_candidates = [semantic_report.score]
    if isinstance(contract_report.get("quality_score"), (int, float)):
        score_candidates.append(float(contract_report["quality_score"]))
    return {
        "ok": semantic_report.ok and bool(contract_report.get("ok")),
        "score": min(score_candidates),
        "issues": [*semantic_issues, *contract_issues],
        "metrics": semantic_report.metrics,
        "contract": contract_report,
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
    payload = dict(dataset)
    if source_id in ACTIVE_TRINKET_SOURCE_IDS:
        data = dict(payload.get("data") or {})
        for key in ("structured", "hsreplay_extracted"):
            if isinstance(data.get(key), dict):
                data[key] = _active_trinkets_only(data[key])
        payload["data"] = data

    # This metadata describes the exact document selected by
    # resolve_public_dataset(), not the current mutable admin policy. Consumers
    # can therefore distinguish an early publication from a stable baseline
    # without a race against a later mode switch.
    from .parser_control import dataset_publication_mode

    mode = dataset_publication_mode(dataset)
    payload["publication"] = {
        "schema_version": 1,
        "source_id": source_id,
        "mode": mode,
        "channel": mode,
        "published_at": dataset.get("fetched_at"),
    }
    return payload


def _trinket_rows_for_api(source_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    from .structured import enrich_trinket_variant_fields

    trinket_type = "Lesser" if source_id.endswith("_lesser") else "Greater"
    dataset = load_dataset(source_id) or {}
    structured = (dataset.get("data") or {}).get("structured") or {}
    rows = structured.get("trinkets") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if active_only and not (row.get("pick_rate") or row.get("avg_placement")):
            continue
        item = enrich_trinket_variant_fields(dict(row), trinket_type=trinket_type)
        item["source_id"] = source_id
        item["source_url"] = SOURCE_BY_ID[source_id].url
        out.append(item)
    return out


@app.get("/api/bg/trinkets")
def bg_trinkets(
    trinket_tier: str = Query("all", pattern="^(all|lesser|greater)$"),
    active_only: bool = Query(True),
) -> dict[str, Any]:
    source_ids = list(ACTIVE_TRINKET_SOURCE_IDS)
    if trinket_tier == "lesser":
        source_ids = ["hsreplay_battlegrounds_trinkets_lesser"]
    elif trinket_tier == "greater":
        source_ids = ["hsreplay_battlegrounds_trinkets_greater"]
    rows: list[dict[str, Any]] = []
    fetched_at: list[str] = []
    for source_id in source_ids:
        dataset = load_dataset(source_id)
        if dataset and dataset.get("fetched_at"):
            fetched_at.append(str(dataset["fetched_at"]))
        rows.extend(_trinket_rows_for_api(source_id, active_only=active_only))
    rows.sort(
        key=lambda row: (
            row.get("trinket_tier") or "",
            str(row.get("tier") or "Z"),
            float(row.get("avg_placement") or 99),
            row.get("name") or "",
            row.get("tribe") or "",
        )
    )
    return {
        "type": "bg_trinkets",
        "count": len(rows),
        "active_only": active_only,
        "trinket_tier": trinket_tier,
        "fetched_at": max(fetched_at) if fetched_at else None,
        "trinkets": rows,
    }


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
    semantic_failed_sources: list[str] = []
    semantic_failures: list[dict[str, Any]] = []
    for source, status in zip(SOURCES, statuses, strict=True):
        state = status["state"] if status else SourceState.NEVER_FETCHED
        states[state] = states.get(state, 0) + 1
        if status and status.get("serving_cached_dataset"):
            cached_sources.append(source.id)
            if status.get("last_refresh_state") not in (None, SourceState.OK):
                cached_after_failure_sources.append(source.id)
        if state != SourceState.OK:
            hard_failed_sources.append(source.id)
        semantic_quality = _semantic_dataset_quality(source.id, load_dataset(source.id))
        if semantic_quality and not semantic_quality["ok"]:
            semantic_failed_sources.append(source.id)
            semantic_failures.append(
                {
                    "source_id": source.id,
                    "score": semantic_quality["score"],
                    "issues": semantic_quality["issues"],
                    "metrics": semantic_quality["metrics"],
                }
            )

    from .stale_monitor import find_stale_sources

    stale_sources = find_stale_sources(include_ok=True)
    stale_ids = [str(item["source_id"]) for item in stale_sources]
    serving_ok = not hard_failed_sources and not semantic_failed_sources
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
        "semantic_failed_sources": semantic_failed_sources,
        "semantic_failures": semantic_failures,
        "cached_sources": cached_sources,
        "cached_after_failure_sources": cached_after_failure_sources,
        "stale_sources": stale_ids,
        "stale_count": len(stale_ids),
        "cached_count": len(cached_sources),
        "cached_after_failure_count": len(cached_after_failure_sources),
    }


def cached_health_diagnostics() -> dict:
    """Bound repeated health polling while keeping tests and CLI checks exact."""
    global _health_cache_at, _health_cache_payload
    if python_environment() == "test":
        return build_health_diagnostics()
    now = time.monotonic()
    with _health_cache_lock:
        if _health_cache_payload is not None and now - _health_cache_at < _HEALTH_CACHE_SECONDS:
            return _health_cache_payload
        payload = build_health_diagnostics()
        _health_cache_payload = payload
        _health_cache_at = now
        return payload


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
    from .parser_control import resolve_public_dataset

    published = resolve_public_dataset(source_id, dataset)
    if published is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Stable dataset is not available yet",
                "source_id": source_id,
                "publication_mode": "stable",
            },
        )
    return public_dataset_payload(source_id, published)


def _control_expected_revision(payload: dict[str, Any]) -> int:
    value = payload.get("expectedRevision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HTTPException(status_code=422, detail="expectedRevision must be a positive integer")
    return value


def _control_list_of_strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HTTPException(status_code=422, detail=f"{key} must be an array of strings")
    return [item.strip() for item in value if item.strip()]


def _raise_parser_control_http_error(exc: Exception) -> None:
    from .parser_control import (
        InvalidControlRequest,
        ParserControlStorageError,
        RevisionConflict,
    )

    if isinstance(exc, RevisionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVISION_CONFLICT",
                "message": str(exc),
                "expectedRevision": exc.expected,
                "currentRevision": exc.current,
            },
        ) from exc
    if isinstance(exc, InvalidControlRequest):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc
    if isinstance(exc, ParserControlStorageError):
        raise HTTPException(
            status_code=503,
            detail={"code": "CONTROL_STORAGE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    raise exc


@app.get("/admin/parser-control", dependencies=[Depends(require_admin)])
def get_parser_control() -> dict[str, Any]:
    from .parser_control import parser_control_store

    try:
        return parser_control_store().snapshot()
    except Exception as exc:
        _raise_parser_control_http_error(exc)
        raise


@app.patch("/admin/parser-control/policy", dependencies=[Depends(require_admin)])
def update_parser_control_policy(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .parser_control import parser_control_store

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be an object")
    try:
        return parser_control_store().update_policy(
            expected_revision=_control_expected_revision(payload),
            mode=str(payload.get("mode") or ""),
            early_until=payload.get("earlyUntil"),
            reason=payload.get("reason"),
            updated_by=str(payload.get("updatedBy") or "admin-api"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_parser_control_http_error(exc)
        raise


@app.patch("/admin/parser-control/sections", dependencies=[Depends(require_admin)])
def update_parser_control_sections(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .parser_control import parser_control_store

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be an object")
    rows = payload.get("sections")
    changes: dict[str, bool] = {}
    if isinstance(rows, dict):
        changes = dict(rows)
    elif isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise HTTPException(
                    status_code=422,
                    detail="sections entries must contain id and enabled",
                )
            changes[row["id"]] = row.get("enabled")
    else:
        raise HTTPException(status_code=422, detail="sections must be an object or array")
    try:
        return parser_control_store().update_sections(
            expected_revision=_control_expected_revision(payload),
            changes=changes,
            updated_by=str(payload.get("updatedBy") or "admin-api"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        _raise_parser_control_http_error(exc)
        raise


@app.post(
    "/admin/parser-runs",
    dependencies=[Depends(require_admin)],
    status_code=202,
)
def create_parser_run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .parser_control import expand_run_selection, parser_run_worker

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be an object")
    try:
        selected = expand_run_selection(
            source_ids=_control_list_of_strings(payload, "sourceIds"),
            section_ids=_control_list_of_strings(payload, "sectionIds"),
        )
        run, deduplicated = parser_run_worker().enqueue(
            source_ids=selected,
            requested_by=str(payload.get("requestedBy") or "admin-api"),
            reason=payload.get("reason"),
        )
        return {"run": run, "deduplicated": deduplicated}
    except HTTPException:
        raise
    except Exception as exc:
        _raise_parser_control_http_error(exc)
        raise


@app.get("/admin/parser-runs", dependencies=[Depends(require_admin)])
def list_parser_runs(limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    from .parser_control import parser_control_store

    try:
        return parser_control_store().list_runs(limit=limit)
    except Exception as exc:
        _raise_parser_control_http_error(exc)
        raise


@app.post("/admin/refresh", dependencies=[Depends(require_admin)])
async def refresh(
    source_id: Annotated[list[str] | None, Query()] = None,
) -> dict:
    if source_id:
        missing = [item for item in source_id if item not in SOURCE_BY_ID]
        if missing:
            raise HTTPException(status_code=404, detail={"unknown_sources": missing})
        pipeline = [item for item in source_id if SOURCE_BY_ID[item].kind == "pipeline"]
        if pipeline:
            raise HTTPException(
                status_code=400,
                detail={
                    "pipeline_sources": pipeline,
                    "message": (
                        "Pipeline sources are refreshed by their dedicated systemd "
                        "timers/endpoints, not by /admin/refresh."
                    ),
                },
            )
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


@app.post("/admin/refresh/bg-minions-db", dependencies=[Depends(require_admin)])
async def refresh_bg_minions_db() -> dict:
    from .hsreplay_bg_minions_db import export_latest_bg_minions_json, refresh_bg_minion_database

    result = await refresh_bg_minion_database()
    result["export_path"] = str(export_latest_bg_minions_json())
    return result


@app.post("/admin/refresh/bg-hero-details", dependencies=[Depends(require_admin)])
async def refresh_bg_hero_details(
    limit: int | None = Query(None, ge=1, le=500),
    concurrency: int = Query(3, ge=1, le=6),
    mmr: str = Query("TOP_50_PERCENT", min_length=1, max_length=80),
    time_range: str = Query("CURRENT_BATTLEGROUNDS_PATCH", min_length=1, max_length=80),
) -> dict:
    from .hsreplay_bg_hero_details import refresh_bg_hero_details as refresh_details

    return await refresh_details(limit=limit, concurrency=concurrency, mmr=mmr, time_range=time_range)


@app.post("/admin/capture/bg-compositions-screenshot", dependencies=[Depends(require_admin)])
async def capture_bg_compositions_screenshot() -> dict:
    from .hsreplay_bg_screenshots import capture_compositions_screenshot

    return await capture_compositions_screenshot()


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
        "state": SourceState.OK,
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
        "state": SourceState.OK,
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
            query += " AND LOWER(class) = LOWER(?)"
            params.append(class_name)
        if format_name:
            query += " AND LOWER(format) = LOWER(?)"
            params.append(format_name)
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        else:
            query += " AND source_id != ?"
            params.append("hsreplay_arena_winning_decks")
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


@app.get("/api/db/bg/minions")
def db_bg_minions(
    q: str | None = Query(None, min_length=1, max_length=120),
    tavern_tier: int | None = Query(None, ge=1, le=7),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
) -> dict:
    from .hsreplay_bg_minions_db import latest_run, list_minion_snapshots

    return {
        "latest_run": latest_run(),
        **list_minion_snapshots(q=q, tavern_tier=tavern_tier, limit=limit, offset=offset),
    }


@app.get("/api/db/bg/minions/{dbf_id}")
def db_bg_minion_detail(dbf_id: int) -> dict:
    from .hsreplay_bg_minions_db import get_minion_detail

    payload = get_minion_detail(dbf_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds minion snapshot not found")
    return payload


@app.get("/api/db/bg/minions/{dbf_id}/history")
def db_bg_minion_history(
    dbf_id: int,
    limit: int = Query(120, ge=1, le=1000),
) -> dict:
    from .hsreplay_bg_minions_db import get_minion_history

    payload = get_minion_history(dbf_id, limit=limit)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds minion not found")
    return payload


@app.get("/api/bg/heroes")
def api_bg_heroes(
    mode: str = Query("solo", pattern="^(solo|duos)$"),
    q: str | None = Query(None, min_length=1, max_length=120),
) -> dict:
    from .hsreplay_bg_hero_details import list_bg_heroes

    return list_bg_heroes(mode=mode, q=q)


@app.get("/api/bg/heroes/duos")
def api_bg_heroes_duos(q: str | None = Query(None, min_length=1, max_length=120)) -> dict:
    from .hsreplay_bg_hero_details import list_bg_heroes

    return list_bg_heroes(mode="duos", q=q)


@app.get("/api/bg/heroes/{dbf_id}")
def api_bg_hero_detail(dbf_id: int) -> dict:
    from .hsreplay_bg_hero_details import get_bg_hero

    payload = get_bg_hero(dbf_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds hero not found")
    return payload


@app.get("/api/bg/heroes/{dbf_id}/tavern-up")
def api_bg_hero_tavern_up(dbf_id: int) -> dict:
    from .hsreplay_bg_hero_details import get_bg_hero

    payload = get_bg_hero(dbf_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds hero not found")
    return {
        "hero": payload.get("hero"),
        "filters": payload.get("filters"),
        "as_of": (payload.get("as_of") or {}).get("tavern_up") if isinstance(payload.get("as_of"), dict) else None,
        "tavern_up": payload.get("tavern_up") or [],
        "tavern_up_by_turn": payload.get("tavern_up_by_turn") or [],
    }


@app.get("/api/bg/heroes/{dbf_id}/hero-power")
def api_bg_hero_power(dbf_id: int) -> dict:
    from .hsreplay_bg_hero_details import get_bg_hero

    payload = get_bg_hero(dbf_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds hero not found")
    return {
        "hero": payload.get("hero"),
        "filters": payload.get("filters"),
        "as_of": (payload.get("as_of") or {}).get("hero_power") if isinstance(payload.get("as_of"), dict) else None,
        "hero_power": payload.get("hero_power") or [],
        "hero_power_by_turn": payload.get("hero_power_by_turn") or [],
    }


@app.get("/api/bg/heroes/{dbf_id}/best-composition")
def api_bg_hero_best_composition(dbf_id: int) -> dict:
    from .hsreplay_bg_hero_details import get_bg_hero

    payload = get_bg_hero(dbf_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Battlegrounds hero not found")
    return {
        "hero": payload.get("hero"),
        "filters": payload.get("filters"),
        "as_of": payload.get("as_of"),
        "best_composition": payload.get("best_composition"),
        "compositions": payload.get("compositions") or [],
    }


@app.get("/api/patches")
def api_patches(
    q: str | None = Query(None, min_length=1, max_length=120),
    match_state: str | None = Query(None, pattern="^(matched|missing_manacost)$"),
    include_content: bool = Query(False),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10000),
) -> dict:
    from .patches_db import list_patches

    return list_patches(
        q=q,
        match_state=match_state,
        include_content=include_content,
        limit=limit,
        offset=offset,
    )


@app.get("/api/patches/{version}")
def api_patch_detail(
    version: str,
    include_content: bool = Query(True),
) -> dict:
    from .patches_db import get_patch

    payload = get_patch(version, include_content=include_content)
    if payload is None:
        raise HTTPException(status_code=404, detail="Patch not found")
    return payload


@app.get("/api/bg/compositions/screenshot/latest")
def bg_compositions_latest_screenshot() -> dict:
    from .hsreplay_bg_screenshots import latest_compositions_screenshot

    payload = latest_compositions_screenshot()
    if payload is None:
        raise HTTPException(status_code=404, detail="No Battlegrounds compositions screenshot captured yet")
    return payload


@app.get("/api/bg/compositions/screenshot/latest/image")
def bg_compositions_latest_screenshot_image() -> FileResponse:
    from .hsreplay_bg_screenshots import latest_compositions_screenshot

    payload = latest_compositions_screenshot()
    if payload is None or not payload.get("image_path"):
        raise HTTPException(status_code=404, detail="No Battlegrounds compositions screenshot image captured yet")
    path = Path(str(payload["image_path"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot image file is missing")
    return FileResponse(path)


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
