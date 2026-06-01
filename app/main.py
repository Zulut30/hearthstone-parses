from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import api_key
from .demo import build_demo_view, build_overview
from .fetcher import refresh_sources
from .sources import SOURCES, SOURCE_BY_ID
from .storage import load_dataset, load_status, root_dir, save_dataset, save_status


WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="Hearthstone Data API",
    version="0.1.0",
    description="Cached API for configured Hearthstone public data sources.",
)

if WEB_DIR.is_dir():
    app.mount("/ui/assets", StaticFiles(directory=WEB_DIR), name="ui-assets")


@app.get("/")
def redirect_to_ui() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/ui")
def demo_index() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Demo UI not installed")
    return FileResponse(index)


@app.get("/demo/overview")
def demo_overview() -> dict:
    return build_overview()


@app.get("/demo/view/{source_id}")
def demo_view(source_id: str) -> dict:
    if source_id not in SOURCE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown source")
    return build_demo_view(source_id)


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = api_key()
    if expected and x_api_key == expected:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


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


@app.get("/health")
def health() -> dict:
    statuses = [load_status(source.id) for source in SOURCES]
    states: dict[str, int] = {}
    for status in statuses:
        state = status["state"] if status else "never_fetched"
        states[state] = states.get(state, 0) + 1
    return {
        "ok": True,
        "data_dir": str(root_dir()),
        "sources": len(SOURCES),
        "states": states,
    }


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
    return dataset


@app.post("/admin/refresh", dependencies=[Depends(require_admin)])
async def refresh(
    source_id: Annotated[list[str] | None, Query()] = None,
) -> dict:
    if source_id:
        missing = [item for item in source_id if item not in SOURCE_BY_ID]
        if missing:
            raise HTTPException(status_code=404, detail={"unknown_sources": missing})
    return {"results": await refresh_sources(source_id)}


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
    class_name: str | None = None,
    format_name: str | None = None,
    source_id: str | None = None,
    min_win_rate: float | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
    finally:
        conn.close()


@app.get("/api/db/cards/trends")
def db_card_trends(
    card_name: str,
    source_id: str | None = None,
    class_name: str | None = None,
    limit: int = 100,
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
    finally:
        conn.close()
