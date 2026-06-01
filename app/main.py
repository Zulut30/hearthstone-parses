from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

from .config import api_key
from .fetcher import refresh_sources
from .sources import SOURCES, SOURCE_BY_ID
from .storage import load_dataset, load_status, root_dir, save_dataset, save_status


app = FastAPI(
    title="Hearthstone Data API",
    version="0.1.0",
    description="Cached API for configured Hearthstone public data sources.",
)


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
